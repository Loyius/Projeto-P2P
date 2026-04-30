# Sprint 2 — Comunicação de tarefas e apresentação de workers — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar o ciclo completo Master ↔ Worker (duas conexões TCP curtas por tarefa), com fila no Master, estado pendente por `WORKER_UUID`, JSON + `\n`, parsing estrito, valores de controlo em maiúsculas e timeout de 5 s no worker.

**Architecture:** Master com `deque` + `dict` pendente e `threading.Lock`; `handle_client` com ramos **HEARTBEAT** (primeiro), relatório **STATUS**/**ACK** e handshake; arranque `start_server()` → `seed_queue()` + `server_loop`. Worker: apresentação (opcional `SERVER_UUID` se emprestado) → `QUERY`/`NO_TASK` → cálculo `A+B` → `RESULT` → `ACK`. Heartbeat periódico **opcional** (`P2P_ENABLE_HEARTBEAT`) em thread com `schedule`. Validações em `protocol.py`; constante de tarefa nomeada **`QUERY`** (não `TASK_QUERY`).

**Tech stack:** Python 3, `socket`, `threading`, `json`, `collections.deque`, `schedule` (heartbeat no worker); testes com `pytest` se existir pasta `tests/`.

---

## Mapa de ficheiros

| Ficheiro | Responsabilidade |
|----------|------------------|
| `protocol.py` | Constantes `WORKER_ALIVE`, `QUERY`, `TASK_NO_TASK`, `STATUS_OK`, `STATUS_NOK`, `STATUS_ACK`; `validate_worker_handshake`, `validate_status_report`. |
| `servidor.py` | `from protocol import *`; `P2P_HOST`/`P2P_PORT`; `P2P_SERVER_UUID` (predef. `MASTER_1`); `task_queue`, `pending_by_worker`, `state_lock`; `seed_queue`, `send_json_line`, `handle_client`, `server_loop`, `start_server`. |
| `client.py` | `from protocol import *`; `schedule` + heartbeat opcional (`P2P_ENABLE_HEARTBEAT`, `P2P_HEARTBEAT_INTERVAL_SEC`, `HEARTBEAT_SERVER_UUID`); `recv_json_line`, `request_task`, `report_status` (incl. `RESULT`), `run_worker_loop`, `main`. |
| `tests/test_*.py` | Opcional: integração com servidor em thread (ver código no repositório). |
| `requirements.txt` | `schedule`; acrescentar `pytest` se se mantiverem testes automatizados. |

---

### Task 1: Constantes e validação (`protocol.py`)

**Files:**
- Create: `protocol.py`
- Create: `tests/test_protocol.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Adicionar pytest**

```text
pytest
```

Acrescentar `pytest` a `requirements.txt` (linha em ficheiro).

- [x] **Step 2: Criar `protocol.py` com validações**

```python
"""Mensagens de controlo P2P (valores em MAIÚSCULAS)."""
from __future__ import annotations

WORKER_ALIVE = "ALIVE"
QUERY = "QUERY"
TASK_NO_TASK = "NO_TASK"
STATUS_OK = "OK"
STATUS_NOK = "NOK"
STATUS_ACK = "ACK"


def validate_worker_handshake(payload: dict) -> None:
    if payload.get("WORKER") != WORKER_ALIVE:
        raise ValueError("missing or invalid WORKER (expected ALIVE)")
    uid = payload.get("WORKER_UUID")
    if not isinstance(uid, str) or not uid:
        raise ValueError("WORKER_UUID is required and must be a non-empty string")


def validate_status_report(payload: dict) -> None:
    status = payload.get("STATUS")
    if status not in (STATUS_OK, STATUS_NOK):
        raise ValueError("STATUS must be OK or NOK (case-sensitive)")
    if payload.get("TASK") != QUERY:
        raise ValueError("TASK must be QUERY for this report")
    uid = payload.get("WORKER_UUID")
    if not isinstance(uid, str) or not uid:
        raise ValueError("WORKER_UUID is required and must be a non-empty string")
```

- [x] **Step 3: Testes unitários — handshake válido e extra fields**

```python
import pytest

from protocol import validate_worker_handshake, validate_status_report, QUERY
from protocol import STATUS_OK, STATUS_NOK


def test_handshake_accepts_unknown_keys():
    validate_worker_handshake(
        {"WORKER": "ALIVE", "WORKER_UUID": "w1", "EXTRA": 123}
    )


def test_handshake_rejects_missing_uuid():
    with pytest.raises(ValueError):
        validate_worker_handshake({"WORKER": "ALIVE"})


def test_handshake_rejects_wrong_alive_case():
    with pytest.raises(ValueError):
        validate_worker_handshake({"WORKER": "alive", "WORKER_UUID": "w1"})


def test_status_ok():
    validate_status_report(
        {"STATUS": "OK", "TASK": QUERY, "WORKER_UUID": "w1"}
    )


def test_status_nok():
    validate_status_report(
        {"STATUS": "NOK", "TASK": QUERY, "WORKER_UUID": "w1"}
    )
```

- [x] **Step 4: Correr testes**

Run: `python -m pytest tests/test_protocol.py -v`

Expected: all **PASSED**

- [ ] **Step 5: Commit**

```bash
git add protocol.py tests/test_protocol.py requirements.txt
git commit -m "feat(sprint2): add protocol validators and unit tests"
```

---

### Task 2: Master — fila, pendente e `handle_client`

**Files:**
- Modify: `servidor.py`

- [x] **Step 1: Imports e estado global partilhado**

No topo de `servidor.py`:

```python
from collections import deque
from protocol import *
```

(`QUERY`, `TASK_NO_TASK`, `STATUS_ACK`, `validate_*` vêm do `protocol`.)

Criar:

```python
task_queue: deque = deque()
pending_by_worker: dict[str, dict] = {}
state_lock = threading.Lock()
```

Inicializar a fila no arranque com pelo menos um item de teste, por exemplo:

```python
def seed_queue():
    with state_lock:
        task_queue.append({"USER": "demo-user", "A": 2, "B": 2})
```

Chamar `seed_queue()` em `start_server()` antes de `server_loop(HOST, PORT)`. O Master usa `SERVER_UUID = os.environ.get("P2P_SERVER_UUID", "MASTER_1")`, `HOST`/`PORT` por ambiente.

- [x] **Step 2: Helper para enviar uma linha JSON**

```python
def send_json_line(conn, obj: dict) -> None:
    conn.sendall((json.dumps(obj) + "\n").encode())
```

- [x] **Step 3: Substituir lógica dentro do loop `while "\\n" in buffer`**

Após `payload = json.loads(message)`:

1. Tentar interpretar como **relatório de status**: se `"STATUS" in payload` e `"TASK" in payload`:
   - `try: validate_status_report(payload) except ValueError: log; return` e **fechar** tratamento desta mensagem sem ACK (não enviar ACK). **Nota:** distinguir dois casos: (a) `validate_status_report` **lança exceção** (payload malformado, campo ausente, valor inválido) → **não enviar ACK**, fechar conexão após log; (b) `validate_status_report` **passa** e `STATUS == "NOK"` (worker reportou falha legítima na tarefa) → **enviar ACK normalmente**, logar a falha, remover pendente — como no CT05 do projeto.
   - `wid = payload["WORKER_UUID"]`; com `state_lock`, verificar que `pending[wid]` existe e `pending[wid].get("TASK") == QUERY` (constante em `protocol.py`).
   - Se válido: log incluir `RESULT` se existir; `del pending_by_worker[wid]`; `send_json_line(conn, {"STATUS": STATUS_ACK, "WORKER_UUID": wid})`.
   - Após enviar o ACK, executar `return` imediatamente para encerrar o handler. O bloco `finally` existente chama `conn.close()`, fechando a conexão de forma determinística. Não aguardar mais dados do worker nesta conexão.
2. **Senão**, tratar como **handshake**:
   - `validate_worker_handshake`; se falhar, log e **não** enviar tarefa.
   - `wid = payload["WORKER_UUID"]`. Verificar `payload.get("SERVER_UUID")`: se presente, logar `[MASTER] Worker {wid} é emprestado do Master {server_uuid}`. Comportamento de despacho de tarefa não se altera — CT02 exige reconhecimento e log, não lógica diferente.
   - Com lock: se fila vazia → `send_json_line(conn, {"TASK": TASK_NO_TASK})`.
   - Senão: `item = task_queue.popleft()`; registar `pending_by_worker[wid]` com `TASK: QUERY`, `USER`, `A`, `B` (igual ao payload enviado); `send_json_line` com o mesmo dict `QUERY` + `USER` + `A` + `B`.

Manter compatibilidade: ramo **`payload.get("TASK") == "HEARTBEAT"`** **antes** dos ramos de status e handshake — resposta `HEARTBEAT` / `RESPONSE: ALIVE`.

- [ ] **Step 4: Smoke manual**

Run (dois terminais): `python servidor.py` e `python client.py` após Task 3 — aqui apenas verificar que o servidor aceita ligações sem exceção após alterações; pode falhar até o cliente estar atualizado.

- [ ] **Step 5: Commit**

```bash
git add servidor.py
git commit -m "feat(sprint2): master queue, pending map, two-phase messages"
```

---

### Task 3: Worker — ciclo duas conexões, timeout 5 s, espera 30 s

**Files:**
- Modify: `client.py`

- [x] **Step 1: Configuração**

```python
import os
import socket
import json
import threading
import time
import uuid

import schedule
from protocol import *

HOST = os.environ.get("P2P_HOST", "127.0.0.1")
PORT = int(os.environ.get("P2P_PORT", "5000"))
WORKER_UUID = os.environ.get("P2P_WORKER_UUID", str(uuid.uuid4()))
ORIGIN_MASTER_UUID = os.environ.get("P2P_ORIGIN_MASTER_UUID", "").strip()
HEARTBEAT_SERVER_UUID = os.environ.get(
    "P2P_HEARTBEAT_SERVER_UUID",
    os.environ.get("P2P_SERVER_UUID", "MASTER_1"),
)
READ_TIMEOUT_SEC = 5.0
NO_TASK_SLEEP_SEC = 30
HEARTBEAT_INTERVAL_SEC = int(os.environ.get("P2P_HEARTBEAT_INTERVAL_SEC", "30"))
```

- **Emprestado (CT02):** `P2P_ORIGIN_MASTER_UUID` não vazio → handshake com `SERVER_UUID`.
- **Heartbeat opcional:** `P2P_ENABLE_HEARTBEAT` ∈ `1`, `true`, `yes`, `on` → thread em fundo com `schedule.every(...).seconds.do(send_heartbeat)` e primeiro envio imediato.

- [x] **Step 2: Função `recv_json_line(sock) -> dict`**

Usar `sock.settimeout(READ_TIMEOUT_SEC)`, acumular buffer até `\n`, `json.loads` uma linha, devolver dict. Em `socket.timeout` ou JSON inválido: propagar ou devolver erro para o chamador tratar com mensagem clara.

- [x] **Step 3: `request_task()` — primeira conexão**

Abrir `socket`, `connect`, enviar:

```python
handshake = {"WORKER": "ALIVE", "WORKER_UUID": WORKER_UUID}
if ORIGIN_MASTER_UUID:
    handshake["SERVER_UUID"] = ORIGIN_MASTER_UUID
sock.sendall((json.dumps(handshake) + "\n").encode())
reply = recv_json_line(sock)
```

Se `reply.get("TASK") == TASK_NO_TASK`: fechar; `time.sleep(NO_TASK_SLEEP_SEC)`; retornar `None`.

Se `reply.get("TASK") == QUERY` e `"USER" in reply`: retornar tuplo `(reply["USER"], reply.get("A"), reply.get("B"))`.

Qualquer outro: tratar como erro de protocolo.

- [x] **Step 4: `report_status(user: str, ok: bool)` — segunda conexão**

Nova conexão; enviar:

```python
body = {
    "STATUS": STATUS_OK if ok else STATUS_NOK,
    "TASK": QUERY,
    "WORKER_UUID": WORKER_UUID,
    "RESULT": result,
}
```

Ler resposta; exigir `reply.get("STATUS") == STATUS_ACK` e `reply.get("WORKER_UUID") == WORKER_UUID`; senão erro.

Após confirmar o ACK, logar mensagem com `WORKER_UUID` (ex.: ciclo concluído). O socket é fechado pelo `finally` de `report_status`.

- [x] **Step 5: `run_worker_loop()`**

O worker recebe `A` e `B` junto com a tarefa, calcula `result = A + B`, loga o resultado e passa-o para `report_status`. O `time.sleep` de simulação é removido.

```python
while True:
    try:
        task = request_task()
        if task is None:
            continue
        user, a, b = task
        result = a + b
        print(f"[WORKER] Calculando {a} + {b} = {result}")
        report_status(user, ok=True, result=result)
    except (socket.timeout, OSError, ValueError, json.JSONDecodeError, ConnectionError) as e:
        print(f"[WORKER] erro: {e}; a tentar de novo...")
        time.sleep(1)
```

`if __name__ == "__main__": main()` — em `main()`, após logs iniciais, arrancar thread de heartbeat se ativada; depois `run_worker_loop()`.

- [ ] **Step 6: Commit**

```bash
git add client.py
git commit -m "feat(sprint2): worker two-phase task cycle with timeouts"
```

---

### Task 4: Integração e revisão contra a spec

**Files:**
- Create: `tests/test_sprint2_integration.py`
- Modify: `servidor.py` (aceitar `PORT=0` e expor `server_socket.getsockname()` se necessário para testes — pode ser feito com fixture que abre servidor em thread)

- [ ] **Step 1: Arranque de testes com `server_loop`**

O código de produção usa `server_loop(host, port)` em `servidor.py`. Para integração, pode usar-se port `0`, `getsockname()[1]` e threads com `handle_client` (helpers no ficheiro de teste, se existir).

- [ ] **Step 2: Teste ciclo feliz**

Fila com item que inclua `USER`, `A`, `B`; handshake → `QUERY` com os três campos; segunda conexão com `STATUS`, `RESULT` e `ACK` com `WORKER_UUID`.

- [ ] **Step 3: Teste `NO_TASK`**

Fila vazia; handshake → `NO_TASK`.

- [ ] **Step 4: Correr toda a suite**

Run: `python -m pytest tests/ -v`

Expected: **PASSED**

- [ ] **Step 5: Self-review do plano vs `docs/superpowers/specs/2026-04-29-sprint2-comunicacao-tarefas-workers-design.md`**

Confirmar cobertura: delimitador `\n`, constante `QUERY` em `protocol.py`, maiúsculas, ignorar chaves extra, falha sem obrigatórios, 5 s timeout, 30 s após `NO_TASK`, `RESULT` + soma `A+B`, emprestado via `P2P_ORIGIN_MASTER_UUID`, heartbeat opcional (`schedule`), `server_loop` / `P2P_SERVER_UUID`, fecho após `ACK`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_sprint2_integration.py servidor.py
git commit -m "test(sprint2): integration tests for master-worker task cycle"
```

---

## Revisão do plano (self-review)

1. **Cobertura da spec:** Handshake, `QUERY`/`NO_TASK` com `A`/`B`, status+`ACK`, `RESULT`, fila, pendente espelhado, timeouts, espera 30 s, parsing estrito. `SERVER_UUID` opcional (emprestado via `P2P_ORIGIN_MASTER_UUID`). Heartbeat opcional no worker (`P2P_ENABLE_HEARTBEAT`, `schedule`). Master: `SERVER_UUID` configurável (`P2P_SERVER_UUID`), ramo HEARTBEAT. Fechamento após ACK (`return` no Master; `finally` no worker). Validações em `protocol.py` com nome **`QUERY`** (não `TASK_QUERY`).
2. **Placeholders:** Nenhum TBD remanescente nas entregas obrigatórias; fila seed é intencionalmente “demo” configurável pelo aluno.
3. **Consistência:** `servidor.py` e `client.py` importam `protocol`; alinhamento dos literais com a spec (maiúsculas).

---

**Plano guardado em:** `docs/superpowers/plans/2026-04-29-sprint2-comunicacao-tarefas-workers.md`

**Opções de execução:**

1. **Subagent-Driven (recomendado)** — um subagente por tarefa, rever entre tarefas.  
2. **Inline** — executar tarefas nesta sessão em blocos com checkpoints.

Qual preferes para a implementação?
