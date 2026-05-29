# Sprint 3: Federação de Masters — Empréstimo e Devolução de Workers — Design (Brainstorming)

**Data:** 2026-05-20  
**Estado:** Implementado e verificado (26/26 testes passando). Ver plano em `docs/superpowers/plans/2026-05-20-sprint3-federacao-masters.md`.

---

## 1. Contexto

Extensão do sistema Master-Worker (Sprints 01 e 02) com **federação de Masters**: quando um Master A fica saturado, pode pedir Workers emprestados a Masters vizinhos (Master B). A comunicação entre Masters usa o mesmo canal TCP com um protocolo JSON próprio (M2M). Toda a lógica das Sprints 01/02 é **preservada integralmente** — nada foi apagado ou sobrescrito.

---

## 2. Decisões de desenho

| Decisão | Escolha |
|--------|---------|
| Canal M2M | **Mesmo porto TCP** do Master; primeira mensagem distingue origem (campo `type` minúsculo = M2M; campo `WORKER` = Worker Sprint 01/02). |
| Identificação de conexão | `is_m2m_message(payload)` em `protocol.py` verifica se `type` ∈ `M2M_KNOWN_TYPES` antes dos ramos Sprint 01/02. |
| Envelope M2M | `{"type": "<tipo>", "request_id": "<uuid4>", "payload": {}}` com `\n` final — fabricado por `make_m2m_message()`. |
| Strict parsing | `validate_m2m_message()`: campos obrigatórios ausentes → `ValueError` capturado e logado, processo nunca derruba. Campos desconhecidos ignorados. |
| `type` desconhecido | Log + return imediato, nunca exceção não tratada. |
| Pool de conexões M2M | `m2m_pool: dict[master_id, socket]` com lock; reutiliza conexões persistentes; cria nova se socket morto. |
| Histerese | `SATURATION_THRESHOLD` (100) e `RELEASE_THRESHOLD` (60) evitam ping-pong de empréstimo/devolução. |
| Separação de estado | `local_workers: set[str]` + `borrowed_workers: dict[str, dict]` thread-safe; Workers locais e emprestados contados separadamente. |
| Registos de ciclo de vida | Log completo: `borrowed_at`, `returned_at`, `orig_master` de cada Worker emprestado. |

---

## 3. Protocolo M2M

### 3.1 Regras globais

- **Envelope:** `{"type": "<minúsculo>", "request_id": "<uuid4>", "payload": {…}}` + `\n`.
- **Case-sensitive:** todos os `type` em **minúsculas** (distinção dos valores Sprint 01/02 em MAIÚSCULAS).
- **Campos do envelope** (`type`, `request_id`, `payload`): permanecem em **minúsculas** — necessário para o mecanismo de detecção `is_m2m_message()`.
- **Campos dentro de `payload`:** seguem a convenção **MAIÚSCULAS** (ex.: `MASTER_ID`, `CURRENT_LOAD`, `NEW_MASTER_ADDRESS`), alinhado com os restantes payloads do protocolo (HEARTBEAT, ALIVE, QUERY, etc.).
- **Campos desconhecidos:** ignorados (compatibilidade futura).
- **Campos obrigatórios ausentes:** logar erro com detalhe, nunca lançar exceção não tratada, nunca derrubar o processo.
- **`type` desconhecido:** logar e ignorar.

### 3.2 Tabela de tipos M2M

| `type` | Direcção | Quando |
|--------|----------|--------|
| `request_help` | Master A → Master B | Fila de A > `SATURATION_THRESHOLD`; payload: `MASTER_ID`, `CURRENT_LOAD`, `CAPACITY`, `WORKERS_NEEDED` |
| `response_accepted` | Master B → Master A | Master B tem Workers ociosos; payload: `WORKERS_OFFERED`, `WORKER_DETAILS` (lista de `{ID, ADDRESS}`) |
| `response_rejected` | Master B → Master A | Master B sem capacidade; payload: `REASON = "high_load"` |
| `command_redirect` | Master B → Worker | Após `response_accepted`; payload: `NEW_MASTER_ADDRESS` |
| `register_temporary_worker` | Worker → Master A | Após reconectar no Master A; payload: `WORKER_ID`, `ORIGINAL_MASTER_ID`, `ORIGINAL_MASTER_ADDRESS` |
| `command_release` | Master A → Worker | Fila de A < `RELEASE_THRESHOLD`; payload: `ORIGINAL_MASTER_ADDRESS` |
| `notify_worker_returned` | Master A → Master B | Após `command_release`; payload: `WORKER_ID` |

### 3.3 Fluxo de empréstimo

1. `_saturation_monitor` detecta `fila > SATURATION_THRESHOLD` → chama `request_help_from_neighbors(workers_needed)`.
2. Master A abre conexão M2M (pool) com Master B → envia `request_help`.
3. Master B recebe em `handle_m2m_message` → avalia `_get_idle_workers()` → responde `response_accepted` (com `worker_details`) ou `response_rejected` (com `reason`).
4. Se aceito: Master B chama `_send_redirect_to_worker(wid, peer_addr)` para cada Worker seleccionado.
5. Worker recebe `command_redirect` em `_handle_m2m_from_master()` → actualiza `_current_host/_current_port`; fecha conexão com Master B; reconecta ao Master A.
6. Worker envia `register_temporary_worker` ao Master A (antes do handshake ALIVE).
7. Worker envia handshake ALIVE com `SERVER_UUID = _origin_master_uuid` (ID do Master B).
8. Master A regista em `borrowed_workers`; despacha tarefas normalmente; tag `[EMPRESTADO]` nos logs de status.

### 3.4 Fluxo de devolução

1. `_saturation_monitor` detecta `fila < RELEASE_THRESHOLD` → lista Workers em `borrowed_workers` → chama `release_borrowed_worker(wid)` para cada um.
2. Master A envia `command_release` ao Worker via `worker_connections[wid]`.
3. Master A envia `notify_worker_returned` ao Master B via pool M2M.
4. Worker processa `command_release` → restaura `_current_host/_current_port` para Master B original → reconecta normalmente.
5. Worker remove `borrowed_workers[wid]`; log de ciclo de vida completo.

### 3.5 Timeout e resiliência

- Master A aguarda resposta de Master B por `M2M_TIMEOUT_SEC` (padrão 5 s, via `P2P_M2M_TIMEOUT_SEC`).
- `socket.timeout` → log de timeout, descarta `request_id`, fecha conexão do pool, tenta próximo vizinho.
- `OSError` (Master B caiu) → log, fecha pool, continua com Workers locais.
- Worker emprestado perde conexão com Master A → bloco `except` de `run_worker_loop` detecta `_origin_master_addr` não vazio → restaura estado para Master B e reconecta.

---

## 4. Estrutura de estado (Master)

| Variável | Tipo | Protecção | Propósito |
|---------|------|-----------|-----------|
| `task_queue` | `deque` | `state_lock` | Fila de tarefas (Sprint 01/02) |
| `pending_by_worker` | `dict[str, dict]` | `state_lock` | Tarefas em voo (Sprint 01/02) |
| `local_workers` | `set[str]` | `local_workers_lock` | IDs de Workers conectados directamente |
| `borrowed_workers` | `dict[str, dict]` | `borrowed_lock` | Workers emprestados com metadados |
| `worker_connections` | `dict[str, socket]` | `worker_conn_lock` | Conexões activas de Workers (para redirect/release) |
| `m2m_pool` | `dict[str, socket]` | `m2m_pool_lock` | Pool de conexões M2M persistentes |

---

## 5. Configuração via variáveis de ambiente (Sprint 03)

| Variável | Padrão | Descrição |
|---------|--------|-----------|
| `P2P_NEIGHBOR_MASTERS` | `""` | Formato: `"B=127.0.0.1:6001,C=127.0.0.1:6002"` |
| `P2P_SATURATION_THRESHOLD` | `100` | Tarefas na fila para disparar `request_help` |
| `P2P_RELEASE_THRESHOLD` | `60` | Tarefas na fila para disparar devolução |
| `P2P_M2M_TIMEOUT_SEC` | `5` | Timeout de resposta M2M em segundos |
| `P2P_ORIGIN_MASTER_ADDR` | `""` | Endereço `ip:porta` do Master original (worker emprestado ao arranque) |

---

## 6. Casos de teste

| ID | Cenário | Resultado Esperado |
|----|---------|-------------------|
| CT01 | `request_help` com 2 Workers ociosos no Master B | `response_accepted` com `worker_details` de 2 workers; `command_redirect` enviado a cada um |
| CT02 | `request_help` para Master B com carga alta | `response_rejected` com `reason="high_load"`; zero `command_redirect` |
| CT03 | 2 `request_help` concorrentes a Masters distintos | Cada resposta correlacionada com `request_id` original correcto |
| CT04 | Worker B1 conecta no Master A após `command_redirect` | Registado em `borrowed_workers`; handshake ALIVE com `SERVER_UUID = Master B` |
| CT05 | Master A entrega tarefa a Worker emprestado | QUERY → STATUS OK → ACK; log com tag `[EMPRESTADO]` |
| CT06 | Carga do Master A normaliza | `command_release` ao Worker + `notify_worker_returned` ao Master B; Worker volta ao Master B |
| CT07 | Master B não responde em 5 s | Timeout logado; `request_id` descartado; tenta próximo vizinho |
| CT08 | Conexão com Master A cai (Worker emprestado) | Worker restaura estado para Master B e reconecta |
| CT09 | Mensagem com `type` desconhecido | Logada e ignorada; processo continua normalmente |

---

## 7. Fora de âmbito (YAGNI)

- Autenticação M2M, TLS, persistência de estado entre reinicios, sharding de fila entre Masters, descoberta automática de vizinhos.

---

## Referências no repositório

- `protocol.py` — constantes M2M, `validate_m2m_message`, `make_m2m_message`, `is_m2m_message`; constantes Sprint 01/02 preservadas
- `servidor.py` — `handle_m2m_message`, `request_help_from_neighbors`, `release_borrowed_worker`, `_saturation_monitor`, `_get_idle_workers`, pool M2M, registos de Workers
- `client.py` — `_handle_m2m_from_master`, `_send_register_temporary`, `run_worker_loop` (fallback CT08)
- `tests/test_sprint3.py` — 21 testes cobrindo CT01–CT09 com socketpairs reais

---

*Documento produzido como especificação da Sprint 03; implementação: `docs/superpowers/plans/2026-05-20-sprint3-federacao-masters.md`.*
