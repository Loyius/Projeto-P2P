# Sprint 2 — Comunicação de tarefas e apresentação de workers — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar o ciclo completo Master ↔ Worker (duas conexões TCP curtas por tarefa), com fila no Master, estado pendente por `WORKER_UUID`, JSON + `\n`, parsing estrito, valores de controlo em maiúsculas e timeout de 5 s no worker.

**Architecture:** Master com `deque` + `dict` pendente e `threading.Lock`; dispatch na 1ª mensagem (`WORKER`/`ALIVE`); conclusão na 2ª (`STATUS`/`TASK`/`WORKER_UUID`). Worker: apresentar → receber `QUERY`/`NO_TASK` → se `QUERY`, processar → nova conexão → `ACK`. Validações partilhadas extraídas para `protocol.py` para testes e DRY.

**Tech stack:** Python 3, `socket`, `threading`, `json`, `collections.deque`; testes com `pytest` (adicionar ao projeto).

---

## Mapa de ficheiros

| Ficheiro | Responsabilidade |
|----------|------------------|
| `protocol.py` | Constantes dos valores de controlo; funções `validate_worker_handshake`, `validate_status_report`; helper opcional `read_json_line(sock, timeout_sec)` no worker. |
| `servidor.py` | Aceitar `HOST`/`PORT` configuráveis (incl. testes); fila inicial; `handle_client` com branches handshake vs status; logs; **fechar conexão sem `ACK`** se validação de status falhar (após log). |
| `client.py` | UUID do worker; ciclo 1ª/2ª conexão; timeout 5 s em `recv` acumulando até `\n`; espera 30 s após `NO_TASK`; substituir ou conviver com heartbeat — **para esta sprint, priorizar ciclo de tarefas** (heartbeat pode ficar desativado ou em comando separado). |
| `tests/test_protocol.py` | Testes unitários das validações e de ignorar chaves extra. |
| `tests/test_sprint2_integration.py` | Servidor em thread + port `0` bind + ciclo feliz e caso `NO_TASK`. |
| `requirements.txt` | Manter `schedule` se ainda usado; acrescentar `pytest`. |

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

- [ ] **Step 2: Criar `protocol.py` com validações**

```python
"""Mensagens de controlo P2P (valores em MAIÚSCULAS)."""
from __future__ import annotations

WORKER_ALIVE = "ALIVE"
TASK_QUERY = "QUERY"
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
    if payload.get("TASK") != TASK_QUERY:
        raise ValueError("TASK must be QUERY for this report")
    uid = payload.get("WORKER_UUID")
    if not isinstance(uid, str) or not uid:
        raise ValueError("WORKER_UUID is required and must be a non-empty string")
```

- [ ] **Step 3: Testes unitários — handshake válido e extra fields**

```python
import pytest

from protocol import validate_worker_handshake, validate_status_report, TASK_QUERY
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
        {"STATUS": "OK", "TASK": TASK_QUERY, "WORKER_UUID": "w1"}
    )


def test_status_nok():
    validate_status_report(
        {"STATUS": "NOK", "TASK": TASK_QUERY, "WORKER_UUID": "w1"}
    )
```

- [ ] **Step 4: Correr testes**

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

- [ ] **Step 1: Imports e estado global partilhado**

No topo de `servidor.py`, após imports existentes:

```python
from collections import deque
from protocol import (
    TASK_QUERY,
    TASK_NO_TASK,
    STATUS_ACK,
    validate_worker_handshake,
    validate_status_report,
)
```

Criar (substituir constantes soltas se necessário):

```python
task_queue: deque = deque()
pending_by_worker: dict[str, dict] = {}
state_lock = threading.Lock()
```

Inicializar a fila no arranque com pelo menos um item de teste, por exemplo:

```python
def seed_queue():
    with state_lock:
        task_queue.append({"USER": "demo-user"})
```

Chamar `seed_queue()` em `start_server`/`heartbeat` antes do `listen`, ou expor lista inicial editável.

- [ ] **Step 2: Helper para enviar uma linha JSON**

```python
def send_json_line(conn, obj: dict) -> None:
    conn.sendall((json.dumps(obj) + "\n").encode())
```

- [ ] **Step 3: Substituir lógica dentro do loop `while "\\n" in buffer`**

Após `payload = json.loads(message)`:

1. Tentar interpretar como **relatório de status**: se `"STATUS" in payload` e `"TASK" in payload`:
   - `try: validate_status_report(payload) except ValueError: log; return` e **fechar** tratamento desta mensagem sem ACK (não enviar ACK).
   - `wid = payload["WORKER_UUID"]`; com `state_lock`, se `wid` não está em `pending` ou `pending[wid]["USER"]` não coincide com o esperado — na sprint, basta verificar que `pending[wid]` existe e `pending[wid].get("TASK") == TASK_QUERY`; opcionalmente guardar `"USER"` no pendente e exigir igualdade se o relatório incluir `USER` (não obrigatório na spec — não exigir).
   - Se válido: `print` log com worker, USER do pendente, STATUS; `del pending_by_worker[wid]`; `send_json_line(conn, {"STATUS": STATUS_ACK})`.
2. **Senão**, tratar como **handshake**:
   - `validate_worker_handshake`; se falhar, log e **não** enviar tarefa.
   - Com lock: se fila vazia → `send_json_line({"TASK": TASK_NO_TASK})`.
   - Senão: `item = task_queue.popleft()`; `pending_by_worker[wid] = {"TASK": TASK_QUERY, "USER": item["USER"]}`; `send_json_line({"TASK": TASK_QUERY, "USER": item["USER"]})`.

Manter compatibilidade: se ainda precisares de HEARTBEAT durante a migração, tratar `payload.get("TASK") == "HEARTBEAT"` num ramo **antes** dos acima, como hoje.

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

- [ ] **Step 1: Configuração**

```python
import os
import socket
import json
import time
import random
import uuid

from protocol import (
    TASK_QUERY,
    TASK_NO_TASK,
    STATUS_OK,
    STATUS_ACK,
)

HOST = os.environ.get("P2P_HOST", "127.0.0.1")
PORT = int(os.environ.get("P2P_PORT", "5000"))
WORKER_UUID = os.environ.get("P2P_WORKER_UUID", str(uuid.uuid4()))
READ_TIMEOUT_SEC = 5.0
NO_TASK_SLEEP_SEC = 30
```

- [ ] **Step 2: Função `recv_json_line(sock) -> dict`**

Usar `sock.settimeout(READ_TIMEOUT_SEC)`, acumular buffer até `\n`, `json.loads` uma linha, devolver dict. Em `socket.timeout` ou JSON inválido: propagar ou devolver erro para o chamador tratar com mensagem clara.

- [ ] **Step 3: `request_task()` — primeira conexão**

Abrir `socket`, `connect`, enviar:

```python
handshake = {"WORKER": "ALIVE", "WORKER_UUID": WORKER_UUID}
# opcional: if borrowed: handshake["SERVER_UUID"] = ...
sock.sendall((json.dumps(handshake) + "\n").encode())
reply = recv_json_line(sock)
```

Se `reply.get("TASK") == TASK_NO_TASK`: fechar; `time.sleep(NO_TASK_SLEEP_SEC)`; retornar `None`.

Se `reply.get("TASK") == TASK_QUERY` e `"USER" in reply`: retornar `reply["USER"]` (e fechar socket).

Qualquer outro: tratar como erro de protocolo.

- [ ] **Step 4: `report_status(user: str, ok: bool)` — segunda conexão**

Nova conexão; enviar:

```python
body = {
    "STATUS": STATUS_OK if ok else "NOK",
    "TASK": TASK_QUERY,
    "WORKER_UUID": WORKER_UUID,
}
```

Ler resposta; exigir `{"STATUS": STATUS_ACK}`; senão erro.

- [ ] **Step 5: `run_worker_loop()`**

```python
while True:
    try:
        user = request_task()
        if user is None:
            continue
        time.sleep(random.uniform(0.5, 2.0))  # simulação
        report_status(user, ok=True)
    except (socket.timeout, OSError, ValueError, json.JSONDecodeError) as e:
        print(f"[WORKER] erro: {e}; a tentar de novo...")
        time.sleep(1)
```

`if __name__ == "__main__": run_worker_loop()`

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

- [ ] **Step 1: Refator mínimo para teste — função `serve_forever(host, port)`**

Permitir iniciar o servidor numa porta `0` e ler a porta real com `server_socket.getsockname()[1]` após `bind`. O plano recomenda extrair o corpo de `heartbeat()` para aceitar argumentos.

- [ ] **Step 2: Teste ciclo feliz**

Arranjar servidor com fila contendo `{"USER": "u1"}`; worker lógico em Python no mesmo processo: socket 1 handshake → `QUERY`; socket 2 status → `ACK`. Assertions em respostas.

- [ ] **Step 3: Teste `NO_TASK`**

Fila vazia; handshake → `NO_TASK`.

- [ ] **Step 4: Correr toda a suite**

Run: `python -m pytest tests/ -v`

Expected: **PASSED**

- [ ] **Step 5: Self-review do plano vs `docs/superpowers/specs/2026-04-29-sprint2-comunicacao-tarefas-workers-design.md`**

Confirmar cobertura: delimitador `\n`, maiúsculas, ignorar chaves extra, falha sem obrigatórios, 5 s timeout, 30 s após `NO_TASK`, duas conexões, log no Master.

- [ ] **Step 6: Commit**

```bash
git add tests/test_sprint2_integration.py servidor.py
git commit -m "test(sprint2): integration tests for master-worker task cycle"
```

---

## Revisão do plano (self-review)

1. **Cobertura da spec:** Handshake, `QUERY`/`NO_TASK`, status+`ACK`, fila, pendente, timeouts, espera 30 s, parsing estrito — mapeados às Tarefas 1–4. Política explícita: falha de `validate_status_report` ou pendente inexistente → **sem ACK**, conexão termina após possível resposta vazia ou só log (implementação mínima: fechar sem ACK).
2. **Placeholders:** Nenhum TBD remanescente nas entregas obrigatórias; fila seed é intencionalmente “demo” configurável pelo aluno.
3. **Consistência:** Nomes `TASK_QUERY`, funções de validação partilhadas entre master e testes.

---

**Plano guardado em:** `docs/superpowers/plans/2026-04-29-sprint2-comunicacao-tarefas-workers.md`

**Opções de execução:**

1. **Subagent-Driven (recomendado)** — um subagente por tarefa, rever entre tarefas.  
2. **Inline** — executar tarefas nesta sessão em blocos com checkpoints.

Qual preferes para a implementação?
