# Sprint 3 — Federação de Masters: Empréstimo e Devolução de Workers — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Estender o sistema Master-Worker com protocolo M2M (Master-to-Master) para empréstimo e devolução de Workers entre Masters vizinhos, com histerese, pool de conexões, strict parsing e resiliência a falhas — sem modificar nenhuma lógica das Sprints 01/02.

**Architecture:** Protocolo M2M detectado por `is_m2m_message()` antes dos ramos Sprint 01/02 em `handle_client`. Estado thread-safe separado para Workers locais (`local_workers`) e emprestados (`borrowed_workers`). Pool de conexões M2M persistentes (`m2m_pool`). Monitor de saturação em thread daemon com histerese. Worker com estado dinâmico mutável (`_current_host/_current_port`) para suportar redirecionamento.

**Tech stack:** Python 3, `socket`, `threading`, `json`, `uuid`, `logging`, `datetime`; testes com `pytest` e `socketpair`.

---

## Mapa de ficheiros

| Ficheiro | Responsabilidade Sprint 03 |
|----------|---------------------------|
| `protocol.py` | Constantes M2M (`M2M_*`), `M2M_KNOWN_TYPES`, `validate_m2m_message`, `make_m2m_message`, `is_m2m_message` |
| `servidor.py` | Pool M2M, `handle_m2m_message`, `request_help_from_neighbors`, `release_borrowed_worker`, `_saturation_monitor`, registos de Workers locais e emprestados, tags de log |
| `client.py` | Estado dinâmico (`_current_host/_current_port`, `_origin_master_uuid`, `_state_lock`), `_handle_m2m_from_master`, `_send_register_temporary`, fallback CT08 |
| `tests/test_sprint3.py` | 21 testes cobrindo CT01–CT09 com socketpairs, monkeypatch e threads |

---

### Task 1: Protocolo M2M em `protocol.py`

**Files:**
- Modify: `protocol.py`

- [x] **Step 1: Adicionar constantes M2M**

```python
# Sprint 03: Tipos de mensagem Master-to-Master (case-sensitive, minúsculas)
M2M_REQUEST_HELP         = "request_help"
M2M_RESPONSE_ACCEPTED    = "response_accepted"
M2M_RESPONSE_REJECTED    = "response_rejected"
M2M_COMMAND_REDIRECT     = "command_redirect"
M2M_REGISTER_TEMP_WORKER = "register_temporary_worker"
M2M_COMMAND_RELEASE      = "command_release"
M2M_NOTIFY_RETURNED      = "notify_worker_returned"

M2M_KNOWN_TYPES: frozenset[str] = frozenset({
    M2M_REQUEST_HELP, M2M_RESPONSE_ACCEPTED, M2M_RESPONSE_REJECTED,
    M2M_COMMAND_REDIRECT, M2M_REGISTER_TEMP_WORKER,
    M2M_COMMAND_RELEASE, M2M_NOTIFY_RETURNED,
})
```

- [x] **Step 2: Adicionar `validate_m2m_message`**

```python
def validate_m2m_message(msg: dict) -> None:
    for field in ("type", "request_id", "payload"):
        if field not in msg:
            raise ValueError(f"Campo obrigatório '{field}' ausente na mensagem M2M")
    if not isinstance(msg["payload"], dict):
        raise ValueError("Campo 'payload' deve ser um objeto JSON")
```

- [x] **Step 3: Adicionar `make_m2m_message` e `is_m2m_message`**

```python
def make_m2m_message(msg_type: str, payload: dict, request_id: str | None = None) -> dict:
    import uuid
    return {"type": msg_type, "request_id": request_id or str(uuid.uuid4()), "payload": payload}

def is_m2m_message(payload: dict) -> bool:
    return "type" in payload and payload.get("type") in M2M_KNOWN_TYPES
```

- [x] **Step 4: Correr testes existentes para confirmar não regressão**

Run: `python -m pytest tests/test_protocol.py -v`

Expected: 5 PASSED (Sprint 01/02 intactos)

- [x] **Step 5: Commit**

```bash
git add protocol.py
git commit -m "feat(sprint3): M2M protocol constants and validators in protocol.py"
```

---

### Task 2: Estado e utilitários M2M em `servidor.py`

**Files:**
- Modify: `servidor.py`

- [x] **Step 1: Imports e configuração M2M**

```python
import logging, uuid
from datetime import datetime, timezone

# Sprint 03: Configuração M2M via env
_RAW_NEIGHBORS = os.environ.get("P2P_NEIGHBOR_MASTERS", "").strip()
NEIGHBOR_MASTERS: list[dict] = []
for _entry in _RAW_NEIGHBORS.split(","):
    if "=" in _entry:
        _mid, _addr = _entry.split("=", 1)
        NEIGHBOR_MASTERS.append({"master_id": _mid.strip(), "address": _addr.strip()})

SATURATION_THRESHOLD = int(os.environ.get("P2P_SATURATION_THRESHOLD", "100"))
RELEASE_THRESHOLD    = int(os.environ.get("P2P_RELEASE_THRESHOLD", "60"))
M2M_TIMEOUT_SEC      = float(os.environ.get("P2P_M2M_TIMEOUT_SEC", "5"))
```

- [x] **Step 2: Estruturas thread-safe Sprint 03**

```python
local_workers: set[str] = set()
local_workers_lock = threading.Lock()

borrowed_workers: dict[str, dict] = {}   # worker_id -> {worker_id, original_master_id, original_master_address, borrowed_at}
borrowed_lock = threading.Lock()

worker_connections: dict[str, socket.socket] = {}
worker_conn_lock = threading.Lock()

m2m_pool: dict[str, socket.socket] = {}
m2m_pool_lock = threading.Lock()

m2m_log = logging.getLogger("m2m")
```

- [x] **Step 3: Helpers de pool, log e I/O M2M**

Implementar: `recv_json_line`, `_log_m2m`, `_get_m2m_conn`, `_close_m2m_conn`, `_get_idle_workers`, `_log_worker_counts`.

- [x] **Step 4: `handle_m2m_message` — handler dos tipos M2M recebidos**

Casos tratados: `request_help` → `response_accepted`/`response_rejected` + `command_redirect`; `register_temporary_worker` → registo em `borrowed_workers`; `notify_worker_returned` → log. Tipos desconhecidos → log + return (CT09).

- [x] **Step 5: `request_help_from_neighbors` — empréstimo**

Loop pelos `NEIGHBOR_MASTERS`; envia `request_help`; aguarda resposta em `M2M_TIMEOUT_SEC`; `socket.timeout` → log + tenta próximo (CT07); `OSError` → log + fecha pool (CT08).

- [x] **Step 6: `release_borrowed_worker` — devolução**

Envia `command_release` ao Worker via `worker_connections`; envia `notify_worker_returned` ao Master original via pool; remove de `borrowed_workers`; loga ciclo de vida (CT06).

- [x] **Step 7: `_saturation_monitor` — thread daemon com histerese**

```python
if not _help_requested and q > SATURATION_THRESHOLD:  # dispara request_help
elif _help_requested and q < RELEASE_THRESHOLD:        # dispara release
```

- [x] **Step 8: Estender `handle_client` sem quebrar Sprint 01/02**

Antes de HEARTBEAT: `if is_m2m_message(payload): handle_m2m_message(...)`. Registo de `local_workers` e `worker_connections` no handshake ALIVE. Tag `[EMPRESTADO]` no log de STATUS (CT05). Limpeza em `finally`.

- [x] **Step 9: Iniciar `_saturation_monitor` em `start_server`**

```python
threading.Thread(target=_saturation_monitor, daemon=True).start()
```

- [x] **Step 10: Commit**

```bash
git add servidor.py
git commit -m "feat(sprint3): M2M handling, borrowed worker registry, saturation monitor"
```

---

### Task 3: Worker com estado dinâmico em `client.py`

**Files:**
- Modify: `client.py`

- [x] **Step 1: Estado dinâmico mutável**

```python
_current_host = HOST
_current_port = PORT
_origin_master_uuid = ORIGIN_MASTER_UUID
_origin_master_addr = os.environ.get("P2P_ORIGIN_MASTER_ADDR", "").strip()
_state_lock = threading.Lock()
```

- [x] **Step 2: `_handle_m2m_from_master(msg) -> str`**

Retorna `"redirect"` (actualiza `_current_host/_current_port`, guarda origem) ou `"release"` (restaura Master original) ou `"ignore"`. Tipos desconhecidos → log + `"ignore"`.

- [x] **Step 3: `_send_register_temporary(sock)`**

Envia `register_temporary_worker` com `worker_id`, `original_master_id`, `original_master_address` antes do handshake ALIVE.

- [x] **Step 4: Estender `run_worker_loop` sem quebrar Sprint 01/02**

```python
with _state_lock:
    is_borrowed = bool(_origin_master_uuid)
# Se emprestado: _send_register_temporary antes de ALIVE
# Handshake inclui SERVER_UUID se is_borrowed
# Detecção de M2M após recv: if is_m2m_message(reply): action = _handle_m2m_from_master
# Fallback CT08 no except: restaurar _current_host/_current_port se _origin_master_addr não vazio
```

- [x] **Step 5: Commit**

```bash
git add client.py
git commit -m "feat(sprint3): worker dynamic state, redirect/release handling, CT08 fallback"
```

---

### Task 4: Testes Sprint 03

**Files:**
- Create: `tests/test_sprint3.py`

- [x] **Step 1: Testes de `protocol.py`** — `make_m2m_message`, `validate_m2m_message`, `is_m2m_message`, `M2M_KNOWN_TYPES` (11 testes)

- [x] **Step 2: CT01** — `handle_m2m_message` com Workers ociosos → `response_accepted` com `WORKER_DETAILS` + `command_redirect` (monkeypatch de `_get_idle_workers` e `_send_redirect_to_worker`)

- [x] **Step 3: CT02** — Sem Workers ociosos → `response_rejected` com `reason="high_load"`; zero redirects

- [x] **Step 4: CT03** — 2 threads concorrentes com `request_id` distintos; cada resposta correlaciona `request_id` correcto

- [x] **Step 5: CT04 + CT05** — `handle_client` em thread com socketpair; Worker envia `register_temporary_worker` + ALIVE + STATUS OK; verifica `borrowed_workers` e ACK

- [x] **Step 6: CT06** — `release_borrowed_worker` com socketpairs injectados no pool; verifica `command_release` e `notify_worker_returned`

- [x] **Step 7: CT07** — Servidor que nunca responde; `M2M_TIMEOUT_SEC=0.3` via monkeypatch; verifica retorno em < 3 s e pool limpo

- [x] **Step 8: CT08** — Simula bloco `except` de `run_worker_loop`; verifica restauro de `_current_host/_current_port`

- [x] **Step 9: CT09** — `type` desconhecido e campos obrigatórios ausentes não lançam exceção

- [x] **Step 10: Correr suite completa**

Run: `python -m pytest tests/ -v`

Expected: **26 PASSED**

```
tests/test_protocol.py::test_handshake_accepts_unknown_keys PASSED
tests/test_protocol.py::test_handshake_rejects_missing_uuid PASSED
tests/test_protocol.py::test_handshake_rejects_wrong_alive_case PASSED
tests/test_protocol.py::test_status_ok PASSED
tests/test_protocol.py::test_status_nok PASSED
tests/test_sprint3.py::TestM2MProtocol::* (11 testes) PASSED
tests/test_sprint3.py::TestCT01Accepted::* PASSED
tests/test_sprint3.py::TestCT02Rejected::* PASSED
tests/test_sprint3.py::TestCT03Correlation::* PASSED
tests/test_sprint3.py::TestCT04CT05BorrowedWorker::* PASSED
tests/test_sprint3.py::TestCT06Release::* PASSED
tests/test_sprint3.py::TestCT07Timeout::* PASSED
tests/test_sprint3.py::TestCT08MasterFailure::* PASSED
tests/test_sprint3.py::TestCT09UnknownType::* (2 testes) PASSED
```

- [x] **Step 11: Commit**

```bash
git add tests/test_sprint3.py
git commit -m "test(sprint3): 21 tests covering CT01-CT09 with socketpairs and monkeypatch"
```

---

## Revisão do plano (self-review)

1. **Cobertura da spec:** Todos os 7 tipos M2M implementados. Histerese com `SATURATION_THRESHOLD`/`RELEASE_THRESHOLD`. Pool M2M. Timeout 5 s com fallback ao próximo vizinho (CT07). Resiliência a queda do Master B (CT08). Strict parsing sem exceções não tratadas (CT09). Log estruturado `timestamp|type|request_id|origem→destino`. Contadores de Workers locais e emprestados a cada mudança. Ciclo de vida completo de Worker emprestado nos logs.
2. **Não regressão:** Sprints 01/02 preservadas — `handle_client` apenas tem `if is_m2m_message` antes dos ramos existentes; `protocol.py` apenas acrescenta após a linha 32.
3. **Thread-safety:** 6 locks distintos para 6 estruturas de dados partilhadas.
4. **Bug corrigido:** Campo `granted_workers` → `WORKER_DETAILS` no log de `request_help_from_neighbors` para consistência com o envelope enviado.

---

**Plano guardado em:** `docs/superpowers/plans/2026-05-20-sprint3-federacao-masters.md`

**Spec:** `docs/superpowers/specs/2026-05-20-sprint3-federacao-masters-design.md`

**Estado:** ✅ Implementação completa — 26/26 testes passando.
