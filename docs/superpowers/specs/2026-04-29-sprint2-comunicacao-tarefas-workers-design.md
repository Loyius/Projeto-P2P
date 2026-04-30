# Sprint 2: Comunicação de Tarefas e Apresentação de Workers — Design (Brainstorming)

**Data:** 2026-04-29  
**Estado:** Especificação aprovada para implementação (ver plano em `docs/superpowers/plans/`).

---

## 1. Contexto

Sistema de balanceamento P2P sobre **TCP** com mensagens **JSON** terminadas obrigatoriamente em **`\n`**. O **ciclo principal** é o de tarefas (handshake → `QUERY`/`NO_TASK` → status → `ACK`). O Master (`servidor.py`) continua a aceitar mensagens **`HEARTBEAT`** (resposta com `RESPONSE: ALIVE`). O Worker (`client.py`) pode ativar heartbeat periódico em **thread em fundo** com `schedule` quando `P2P_ENABLE_HEARTBEAT` está ligado (ligações TCP separadas das duas fases de tarefa).

---

## 2. Decisões de desenho (brainstorming)

| Decisão | Escolha |
|--------|---------|
| Modelo de conexão | **B** — **conexões curtas**: 1ª conexão pedido/apresentação + resposta `QUERY` ou `NO_TASK`; 2ª conexão relatório de status + `ACK`. |
| Comportamento `NO_TASK` | **Intervalo fixo de 30 s** antes de nova tentativa (alinhado ao ritmo do worker atual). |
| Arquitetura Master | **Fila FIFO + mapa pendente por `WORKER_UUID`** protegido por lock; ao enviar `QUERY`, regista atribuição até `ACK` / validação de `STATUS`. |
| Concorrência | Manter **thread por conexão** + **`threading.Lock`** na estrutura partilhada (encaixa no `servidor.py` atual). |

---

## 3. Protocolo de mensagens

### 3.1 Regras globais

- **Framing:** uma mensagem = um objeto JSON + `\n`.
- **Parsing estrito (Master):** **ignorar** chaves JSON desconhecidas; **falhar** (fechar conexão ou responder erro de protocolo — ver §5) se **faltar qualquer campo obrigatório** para o tipo de mensagem esperado nesta fase.
- **Case sensitivity:** valores de controlo **somente em maiúsculas:** `ALIVE`, `QUERY`, `NO_TASK`, `OK`, `NOK`, `ACK`, `HEARTBEAT` (este último só no fluxo opcional de heartbeat).
- **Constantes partilhadas:** em `protocol.py` os literais expõem-se como `WORKER_ALIVE`, `QUERY`, `TASK_NO_TASK`, `STATUS_OK`, `STATUS_NOK`, `STATUS_ACK`; `servidor.py` e `client.py` importam o módulo conforme o código (ex.: `from protocol import *`).

### 3.2 Worker → Master (1ª conexão — apresentação)

**Obrigatórios:**

- `"WORKER": "ALIVE"`
- `"WORKER_UUID": "<string>"` — identificador estável do worker nesta sessão de vida útil.

**Opcional:**

- `"SERVER_UUID": "<string>"` — presente quando o worker é "emprestado" de outro Master (identificador do **Master de origem**). O Master deve **registar em log** a origem do worker (`[MASTER] Worker {WORKER_UUID} é emprestado do Master {SERVER_UUID}`) e prosseguir com o despacho de tarefa normalmente. Lógica de negócio do empréstimo (redirecionamento, O5) fora do âmbito desta sprint.
- **Implementação no Worker (`client.py`):** definir a variável de ambiente `P2P_ORIGIN_MASTER_UUID` com o identificador do Master de origem (string não vazia). Enquanto estiver definida, cada handshake de apresentação inclui `SERVER_UUID` com esse valor. Se não estiver definida ou estiver vazia, o worker não envia o campo (comportamento normal).

**Resposta Master:**

- Se existir tarefa na fila: `{"TASK": "QUERY", "USER": "<string>", "A": <number>, "B": <number>}` e **registar pendente** para esse `WORKER_UUID`.
- Se fila vazia: `{"TASK": "NO_TASK"}` (sem registo pendente).

### 3.3 Worker → Master (2ª conexão — resultado)

**Obrigatórios:**

- `"STATUS": "OK"` ou `"STATUS": "NOK"`
- `"TASK": "QUERY"` — deve coincidir com a tarefa atribuída em memória para este `WORKER_UUID`.
- `"WORKER_UUID": "<string>"` — igual ao da apresentação.

**Opcional:**

- `"RESULT": <number>` — resultado do cálculo quando o worker reporta sucesso ou inclui o valor enviado pelo worker (ex.: soma `A + B`).

Exemplo com resultado:

```json
{"STATUS": "OK", "TASK": "QUERY", "WORKER_UUID": "<string>", "RESULT": <number>}
```

**Resposta Master:**

- Se validação OK: **log** (worker, resultado, contexto útil da tarefa) e `{"STATUS": "ACK", "WORKER_UUID": "<string>"}` — o campo `WORKER_UUID` **espelha** o UUID recebido no reporte; **remover** pendente.
  - Após enviar o ACK, o Master **fecha a conexão imediatamente** (`return` no handler). O Worker, ao receber o ACK, loga o encerramento e fecha o socket pelo bloco `finally`. O ciclo está concluído — ambos os lados encerram a conexão de forma determinística sem aguardar timeout passivo.
- Se validação falhar: ver §5 (não enviar `ACK` de confirmação válida sem critério claro — recomenda-se fechar ou mensagem de erro explícita; implementação deve ser **determinística** e documentada no plano).

### 3.4 Processamento no Worker

- Após receber `QUERY` na 1ª conexão, **fechar conexão**. O Worker recebe `A` e `B` na resposta `QUERY`, calcula `result = A + B`, e inclui `RESULT` no payload de status.
- Abrir **nova conexão** e enviar o JSON de `STATUS`.
- Após `ACK`, considerar ciclo concluído; pode iniciar novo ciclo (1ª conexão) para próxima tarefa.
- Após receber o ACK, o Worker fecha o socket e considera o ciclo encerrado. Pode iniciar imediatamente um novo ciclo (1ª conexão) para a próxima tarefa.

### 3.5 Timeout (Worker)

- Em **cada** conexão, ao aguardar a **primeira** linha/resposta completa do Master: **máximo 5 s** (`READ_TIMEOUT_SEC` no `client.py`, via `settimeout` em `recv_json_line`). Se expirar: tratar como falha, fechar socket e **tentar reconectar** conforme política simples (ex.: `time.sleep(1)` no ciclo de erros do worker).

### 3.6 Heartbeat opcional (Worker ↔ Master, ligação curta)

- **Não faz parte** do ciclo obrigatório de tarefa; usa **outra** ligação TCP quando ativado.
- **Worker → Master:** `{"SERVER_UUID": "<string>", "TASK": "HEARTBEAT"}` — o valor de `SERVER_UUID` no payload pode ser configurado com `P2P_HEARTBEAT_SERVER_UUID` ou, por defeito, alinhado a `P2P_SERVER_UUID` / `"MASTER_1"` (`HEARTBEAT_SERVER_UUID` no `client.py`).
- **Master → Worker:** `{"SERVER_UUID": "<string>", "TASK": "HEARTBEAT", "RESPONSE": "ALIVE"}` (eco do `SERVER_UUID` recebido ou fallback do Master).
- **Ativação:** variável de ambiente `P2P_ENABLE_HEARTBEAT` ∈ `1`, `true`, `yes`, `on`; primeiro envio imediato, depois intervalo `P2P_HEARTBEAT_INTERVAL_SEC` (predefinição **30**); biblioteca **`schedule`** + **`threading`** no worker.
- O **identificador do Master** usado nas respostas internas do servidor é `SERVER_UUID = os.environ.get("P2P_SERVER_UUID", "MASTER_1")` em `servidor.py`.

---

## 4. Master — fila e estado

- **Fila:** `collections.deque` de itens; cada item inclui pelo menos `USER` (string), `A` e `B` (números) para a tarefa de soma. `seed_queue()` no arranque (`start_server()` → `server_loop`) adiciona um item demo `{"USER": "demo-user", "A": 2, "B": 2}`.
- **Endereço:** `HOST` / `PORT` via `P2P_HOST` / `P2P_PORT` (predefinições `127.0.0.1` e `5000`).
- **Pendentes:** `dict[WORKER_UUID, { "TASK": "QUERY", "USER": "...", "A": ..., "B": ... }]` — espelha o payload `QUERY` enviado na rede para aquele worker.
- **Processamento:** `handle_client` trata primeiro `HEARTBEAT`; depois relatório `STATUS` (validação com `validate_status_report` de `protocol.py`, log com `RESULT`, `ACK` + `return`); por fim handshake (`validate_worker_handshake`, log de emprestado se houver `SERVER_UUID`, `NO_TASK` ou despacho `QUERY` com `A`/`B`). Helper `send_json_line`.
- **Invariantes:**
  - Só existe entrada pendente se o Master enviou `QUERY` a esse worker e ainda não recebeu `STATUS` válido + processou `ACK`.
  - `NO_TASK` **não** cria pendente.
- **Concorrência:** todo acesso à fila e ao dicionário pendente sob **um lock**.

---

## 5. Tratamento de erros (resumo)

- **JSON inválido** ou linha incompleta além do timeout: descartar ou fechar; Master deve **logar**; Worker usa timeout de 5 s.
- **Campos obrigatórios em falta:** Master **não** tratar como sucesso silencioso.
- **`STATUS` sem pendente correspondente** ou `TASK`/`WORKER_UUID` incoerente: **não** confirmar com `ACK` como sucesso; fechar ou protocolo de erro acordado no plano.
- **`NOK` válido** (reporte `STATUS: "NOK"` que **passa** a validação estrutural): **mesmo fluxo** de confirmação que `OK` — o Master loga a falha da tarefa e envia `ACK` com `WORKER_UUID` como de costume; a tarefa fica “fechada” do ponto de vista do worker. A **ausência** de `ACK` aplica-se **exclusivamente** a payloads que **falham** na validação estrutural (JSON inválido, campos obrigatórios em falta, valores fora do protocolo), **não** ao `NOK` legítimo. Política de re-enfileiramento **fora do âmbito** salvo definição explícita no plano — default: **não** re-enfileirar automaticamente.

---

## 6. Testes e critérios de sucesso

- Teste(s) de integração ou testes com sockets em porta local: ciclo feliz **QUERY → OK/NOK → ACK**.
- `NO_TASK` seguido de comportamento do worker (espera 30 s) pode ser testado com clock fake ou intervalo reduzido em modo teste se o plano introduzir isso.
- Master ignora campos extra no JSON e falha sem campos obrigatórios.
- Valores de controlo recusados se não forem exatamente maiúsculos conforme spec.

---

## 7. Fora de âmbito (YAGNI)

- Persistência da fila, multi-master, criptografia, formato rico de `USER` além de string, reatribuição automática de tarefas falhadas.

---

## Referências no repositório

- `protocol.py` — constantes de controlo, `validate_worker_handshake`, `validate_status_report`
- `servidor.py` — Master (`server_loop`, `start_server`, `handle_client`)
- `client.py` — Worker (`request_task`, `report_status`, heartbeat opcional)

---

*Documento produzido pelo fluxo de brainstorming; implementação: `docs/superpowers/plans/2026-04-29-sprint2-comunicacao-tarefas-workers.md`.*
