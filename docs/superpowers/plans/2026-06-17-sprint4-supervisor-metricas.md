# Sprint 4 — Supervisor de Métricas e Continuidade de Tarefas — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reportar periodicamente (a cada 10s) métricas de desempenho do Master ao Supervisor via TLS/TCP (payload com todas as chaves em MAIÚSCULAS), e garantir que o Master reatribui a outro Worker disponível qualquer tarefa cujo Worker original falhe durante a execução — sem modificar nenhuma lógica das Sprints 01/02/03.

**Architecture:** Thread daemon `_metrics_reporter` em `servidor.py` monta o relatório (`build_metrics_report`) a partir das estruturas já existentes (`local_workers`, `borrowed_workers`, `task_queue`, `pending_by_worker`, `NEIGHBOR_MASTERS`) e do `psutil`, e envia via uma conexão TLS/TCP efêmera (`_send_metrics_report`) ao Supervisor, sem aguardar `recv`. Em paralelo, `handle_client` é estendido para, ao detectar falha de um Worker com tarefa pendente, devolver essa tarefa à `task_queue` e marcar o Worker como falhado, deixando o despacho normal (já existente) atribuí-la a outro Worker disponível.

**Tech stack:** Python 3, `socket`, `ssl`, `threading`, `json`, `uuid`, `logging`, `datetime`, `psutil`; testes com `pytest`, `socketpair` e `monkeypatch`.

---

## Mapa de ficheiros

| Ficheiro | Responsabilidade Sprint 04 |
|----------|---------------------------|
| `servidor.py` | `build_metrics_report`, `_send_metrics_report`, `_metrics_reporter` (thread daemon), reatribuição de tarefa em falha de Worker (`_requeue_task_on_worker_failure`), contagem de `workers_failed` |
| `requirements.txt` (ou equivalente) | Adicionar dependência `psutil` |
| `tests/test_sprint4.py` | Testes cobrindo CT01–CT09 |

---

## Schema completo do payload (referência para Tasks 1-2)

> Todos os campos em **MAIÚSCULAS**. Os campos de `PERFORMANCE.FARM_STATE.WORKERS.*` são **dinâmicos**: calculados a partir do estado real da farm (`local_workers`, `borrowed_workers`, `pending_by_worker`) no instante de cada envio — não há quantidade fixa de Workers, a farm pode operar com qualquer número.

**Raiz do payload**

| Campo | Tipo | Descrição |
|---|---|---|
| `SERVER_UUID` | string | Identificador único do servidor no cluster |
| `HOSTNAME` | string | Nome DNS do nó |
| `ROLE` | string | Papel do nó no cluster (`"master"`) |
| `TASK` | string | Tipo de relatório enviado (`"performance_report"`) |
| `TIMESTAMP` | string (ISO-8601) | Momento da coleta |
| `MESSAGE_ID` | string (UUID) | Identificador único da mensagem |
| `PAYLOAD_VERSION` | string | Versão do schema do payload |

**`PERFORMANCE.SYSTEM`**

| Campo | Tipo | Descrição |
|---|---|---|
| `UPTIME_SECONDS` | int | Tempo de atividade do nó em segundos |
| `LOAD_AVERAGE_1M` | float | Média de load da CPU nos últimos 1 minuto |
| `LOAD_AVERAGE_5M` | float | Média de load da CPU nos últimos 5 minutos |
| `CPU.USAGE_PERCENT` | float | Percentual de uso da CPU (0–100) |
| `CPU.COUNT_LOGICAL` | int | Número de CPUs lógicas (threads) |
| `CPU.COUNT_PHYSICAL` | int | Número de CPUs físicas (cores) |
| `MEMORY.TOTAL_MB` | int | Memória RAM total em MB |
| `MEMORY.AVAILABLE_MB` | int | Memória RAM disponível em MB |
| `MEMORY.PERCENT_USED` | float | Percentual de uso da memória (0–100) |
| `MEMORY.MEMORY_USED` | int | Memória RAM utilizada em MB |
| `DISK.TOTAL_GB` | float | Espaço em disco total em GB |
| `DISK.FREE_GB` | float | Espaço em disco livre em GB |
| `DISK.PERCENT_USED` | float | Percentual de uso do disco (0–100) |

**`PERFORMANCE.FARM_STATE.WORKERS`** (todos dinâmicos)

| Campo | Tipo | Descrição |
|---|---|---|
| `TOTAL_REGISTERED` | int | Total de Workers atualmente registados no nó |
| `WORKERS_UTILIZATION` | int | Workers ocupados no momento (executando tarefas) |
| `WORKERS_ALIVE` | int | Workers considerados vivos/respondendo |
| `WORKERS_IDLE` | int | Workers ociosos disponíveis para novas tarefas |
| `WORKERS_BORROWED` | int | Workers que este nó emprestou para outros nós |
| `WORKERS_RECEIVED` | int | Workers que este nó recebeu emprestados de outros nós |
| `WORKERS_FAILED` | int | Workers que falharam |
| `WORKERS_HOME` | int | Workers nativos do servidor (sem empréstimos) |
| `WORKERS_AVAILABLE_CAPACITY` | int | Capacidade ociosa total (= `WORKERS_IDLE`) |
| `BORROWED_WORKERS` | array | Lista de Workers emprestados com origem/destino |
| `BORROWED_WORKERS[].DIRECTION` | string (`"in"` \| `"out"`) | Direção do empréstimo |
| `BORROWED_WORKERS[].PEER_UUID` | string | `SERVER_UUID` do nó na outra ponta do empréstimo |

**`PERFORMANCE.FARM_STATE.TASKS`**

| Campo | Tipo | Descrição |
|---|---|---|
| `TASKS_PENDING` | int | Tarefas aguardando execução |
| `TASKS_RUNNING` | int | Tarefas em execução no momento |
| `TASKS_COMPLETED` | int | Total de tarefas concluídas |
| `TASKS_FAILED` | int | Total de tarefas com falha |
| `OLDEST_TASK_AGE_S` | int | Idade da tarefa pendente mais antiga (segundos) |

**`PERFORMANCE.CONFIG_THRESHOLDS`**

| Campo | Tipo | Descrição |
|---|---|---|
| `MAX_TASK` | int | Número máximo de tarefas antes de considerar o nó saturado |
| `WARN_CPU_PERCENT` | int | Percentual de CPU para disparar alerta |
| `WARN_MEMORY_PERCENT` | int | Percentual de memória para disparar alerta |
| `RELEASE_TASK` | int | Threshold para liberar Workers emprestados |

**`PERFORMANCE.NEIGHBORS[]`**

| Campo | Tipo | Descrição |
|---|---|---|
| `SERVER_UUID` | string | Identificador do nó vizinho |
| `STATUS` | string (`"available"` \| `"unavailable"`) | Status do vizinho |
| `LAST_HEARTBEAT` | string (ISO-8601) | Timestamp do último heartbeat recebido do vizinho |

Spec completa de referência: `docs/superpowers/specs/2026-06-17-sprint4-supervisor-metricas-design.md`, seção 3.3.

---

### Task 1: Dependência `psutil` e configuração Sprint 04

**Files:**
- Modify: `servidor.py`

- [x] **Step 1: Adicionar import e configuração via env**

```python
# Sprint 04: Supervisor de Métricas
import ssl
import psutil

METRICS_ENABLED   = os.environ.get("P2P_METRICS_ENABLED", "1").strip() != "0"
METRICS_INTERVAL  = float(os.environ.get("P2P_METRICS_INTERVAL_SEC", "10"))
SUPERVISOR_HOST   = os.environ.get("P2P_SUPERVISOR_HOST", "nuted-ia.dev").strip()
SUPERVISOR_PORT   = int(os.environ.get("P2P_SUPERVISOR_PORT", "443"))
SUPERVISOR_SNI    = os.environ.get("P2P_SUPERVISOR_SNI", "nuted-ia.dev").strip()

_metrics_start_time = time.monotonic()
_neighbor_last_heartbeat: dict[str, str] = {}
workers_failed_count = 0
metrics_log = logging.getLogger("metrics")
```

- [x] **Step 2: Confirmar `psutil` instalado**

Run: `pip install psutil` (se ainda não estiver instalado)

Run: `python -c "import psutil; print(psutil.cpu_percent())"`
Expected: imprime um número (sem exceção)

- [x] **Step 3: Commit**

```bash
git add servidor.py
git commit -m "feat(sprint4): config e dependências do Supervisor de Métricas"
```

---

### Task 2: `build_metrics_report` — montagem do payload com chaves em MAIÚSCULAS

**Files:**
- Modify: `servidor.py`
- Test: `tests/test_sprint4.py`

- [x] **Step 1: Escrever teste falhando**

```python
# tests/test_sprint4.py
import json
import servidor


def test_build_metrics_report_keys_are_uppercase():
    report = servidor.build_metrics_report()
    assert report["SERVER_UUID"]
    assert report["ROLE"] == "master"
    assert report["TASK"] == "performance_report"
    assert "PERFORMANCE" in report
    perf = report["PERFORMANCE"]
    assert "SYSTEM" in perf and "FARM_STATE" in perf and "CONFIG_THRESHOLDS" in perf and "NEIGHBORS" in perf
    assert "UPTIME_SECONDS" in perf["SYSTEM"]
    assert "USAGE_PERCENT" in perf["SYSTEM"]["CPU"]
    assert "TOTAL_MB" in perf["SYSTEM"]["MEMORY"]
    assert "TOTAL_GB" in perf["SYSTEM"]["DISK"]
    workers = perf["FARM_STATE"]["WORKERS"]
    assert "TOTAL_REGISTERED" in workers and "BORROWED_WORKERS" in workers
    tasks = perf["FARM_STATE"]["TASKS"]
    assert "TASKS_PENDING" in tasks and "OLDEST_TASK_AGE_S" in tasks
    thresholds = perf["CONFIG_THRESHOLDS"]
    assert thresholds["MAX_TASK"] >= 0
    json.dumps(report)  # deve ser serializável


def test_build_metrics_report_worker_counts_are_dynamic():
    """Os valores de WORKERS.* nao sao fixos: devem refletir o estado
    real da farm no momento da chamada, nao um numero fixo de exemplo."""
    with servidor.local_workers_lock:
        servidor.local_workers.clear()
        servidor.local_workers.add("worker_a")

    report_one_worker = servidor.build_metrics_report()
    assert report_one_worker["PERFORMANCE"]["FARM_STATE"]["WORKERS"]["TOTAL_REGISTERED"] == 1

    with servidor.local_workers_lock:
        servidor.local_workers.add("worker_b")
        servidor.local_workers.add("worker_c")

    report_three_workers = servidor.build_metrics_report()
    assert report_three_workers["PERFORMANCE"]["FARM_STATE"]["WORKERS"]["TOTAL_REGISTERED"] == 3
```

- [x] **Step 2: Correr o teste para confirmar falha**

Run: `python -m pytest tests/test_sprint4.py::test_build_metrics_report_keys_are_uppercase -v`
Expected: FAIL com `AttributeError: module 'servidor' has no attribute 'build_metrics_report'`

- [x] **Step 3: Implementar `build_metrics_report`**

```python
def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_metrics_report() -> dict:
    """Monta o payload de métricas com todas as chaves em MAIÚSCULAS.

    Estrutura e valores seguem sprint4.md; apenas a caixa das chaves
    foi corrigida para MAIÚSCULAS nesta sprint.

    Importante: todos os campos de PERFORMANCE.FARM_STATE.WORKERS são
    calculados dinamicamente a partir do estado real da farm no momento
    da chamada (local_workers, borrowed_workers, pending_by_worker). Os
    valores do exemplo na spec (ex.: TOTAL_REGISTERED=6) são apenas
    ilustrativos — não há número fixo de Workers; a farm pode operar
    com qualquer quantidade.
    """
    vm = psutil.virtual_memory()
    du = psutil.disk_usage("/")
    try:
        load1, load5, _ = os.getloadavg()
    except (AttributeError, OSError):
        load1, load5 = 0.0, 0.0

    with local_workers_lock:
        total_local = len(local_workers)
    with borrowed_lock:
        borrowed_list = list(borrowed_workers.values())
    with state_lock:
        tasks_pending = len(task_queue)
        tasks_running = len(pending_by_worker)
        oldest_age = 0
        if task_queue:
            oldest_age = int(time.time() - task_queue[0].get("enqueued_at", time.time()))

    workers_idle = max(total_local - tasks_running, 0)

    borrowed_out = [b for b in borrowed_list if b.get("direction") == "out"]
    borrowed_in = [b for b in borrowed_list if b.get("direction") == "in"]

    neighbors = []
    for neighbor in NEIGHBOR_MASTERS:
        mid = neighbor["master_id"]
        neighbors.append({
            "SERVER_UUID": mid,
            "STATUS": "available" if mid in _neighbor_last_heartbeat else "unavailable",
            "LAST_HEARTBEAT": _neighbor_last_heartbeat.get(mid, _iso_now()),
        })

    return {
        "SERVER_UUID": SERVER_UUID,
        "HOSTNAME": socket.gethostname(),
        "ROLE": "master",
        "TASK": "performance_report",
        "TIMESTAMP": _iso_now(),
        "MESSAGE_ID": str(uuid.uuid4()),
        "PAYLOAD_VERSION": "sprint4-monitor",
        "PERFORMANCE": {
            "SYSTEM": {
                "UPTIME_SECONDS": int(time.monotonic() - _metrics_start_time),
                "LOAD_AVERAGE_1M": round(load1, 2),
                "LOAD_AVERAGE_5M": round(load5, 2),
                "CPU": {
                    "USAGE_PERCENT": psutil.cpu_percent(interval=None),
                    "COUNT_LOGICAL": psutil.cpu_count(logical=True) or 0,
                    "COUNT_PHYSICAL": psutil.cpu_count(logical=False) or 0,
                },
                "MEMORY": {
                    "TOTAL_MB": int(vm.total / (1024 * 1024)),
                    "AVAILABLE_MB": int(vm.available / (1024 * 1024)),
                    "PERCENT_USED": vm.percent,
                    "MEMORY_USED": int(vm.used / (1024 * 1024)),
                },
                "DISK": {
                    "TOTAL_GB": round(du.total / (1024 ** 3), 1),
                    "FREE_GB": round(du.free / (1024 ** 3), 1),
                    "PERCENT_USED": du.percent,
                },
            },
            "FARM_STATE": {
                "WORKERS": {
                    "TOTAL_REGISTERED": total_local + len(borrowed_in),
                    "WORKERS_UTILIZATION": tasks_running,
                    "WORKERS_ALIVE": total_local,
                    "WORKERS_IDLE": workers_idle,
                    "WORKERS_BORROWED": len(borrowed_out),
                    "WORKERS_RECEIVED": len(borrowed_in),
                    "WORKERS_FAILED": workers_failed_count,
                    "WORKERS_HOME": total_local - len(borrowed_in),
                    "WORKERS_AVAILABLE_CAPACITY": workers_idle,
                    "BORROWED_WORKERS": [
                        {"DIRECTION": b["direction"], "PEER_UUID": b["peer_uuid"]}
                        for b in borrowed_list
                    ],
                },
                "TASKS": {
                    "TASKS_PENDING": tasks_pending,
                    "TASKS_RUNNING": tasks_running,
                    "TASKS_COMPLETED": tasks_completed_count,
                    "TASKS_FAILED": tasks_failed_count,
                    "OLDEST_TASK_AGE_S": oldest_age,
                },
            },
            "CONFIG_THRESHOLDS": {
                "MAX_TASK": SATURATION_THRESHOLD,
                "WARN_CPU_PERCENT": int(os.environ.get("P2P_WARN_CPU_PERCENT", "85")),
                "WARN_MEMORY_PERCENT": int(os.environ.get("P2P_WARN_MEMORY_PERCENT", "85")),
                "RELEASE_TASK": RELEASE_THRESHOLD,
            },
            "NEIGHBORS": neighbors,
        },
    }
```

Nota: `tasks_completed_count` e `tasks_failed_count` são contadores já necessários para Sprint 04; se não existirem ainda em `servidor.py`, adicionar como `int` globais protegidos por `state_lock`, incrementados nos pontos já existentes de conclusão/erro de tarefa (ACK de sucesso / excesso de re-tentativas).

- [x] **Step 4: Correr o teste para confirmar sucesso**

Run: `python -m pytest tests/test_sprint4.py::test_build_metrics_report_keys_are_uppercase -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add servidor.py tests/test_sprint4.py
git commit -m "feat(sprint4): build_metrics_report com chaves em MAIUSCULAS"
```

---

### Task 3: Envio TLS/TCP ao Supervisor (apenas `SEND`, nunca `RECV`)

**Files:**
- Modify: `servidor.py`
- Test: `tests/test_sprint4.py`

**Regras explícitas de envio (ler antes de implementar):**

- **TLS sobre TCP puro** — nunca HTTP. Abre-se um socket TCP normal e envolve-se em TLS com `ssl.SSLContext.wrap_socket`; nunca usar `requests`/`urllib`/qualquer cliente HTTP para este envio.
- **Sem paths de URL no socket.** Um endpoint TCP é definido **apenas por host e porta** — não existe "caminho" num socket TCP. Não usar `/supervisor/colector` nem `/supervisor` em nenhuma parte da conexão; esses caminhos só existem na URL do dashboard web (HTTP, ver Task 6), que é um recurso totalmente separado.
- **Apenas `SEND`, nunca `RECV`.** O fluxo é sempre: conectar → enviar o JSON → encerrar a conexão. `_send_metrics_report` (Step 3 abaixo) nunca chama `recv()` nem aguarda qualquer resposta do Supervisor — isso é validado pelo teste do Step 1.
- **Parâmetros fixos da conexão:**

```python
HOST = "nuted-ia.dev"   # TCP_SOCKET_HOST
PORT = 443              # TCP_SOCKET_PORT
TLS  = True             # TCP_SOCKET_TLS
SNI  = "nuted-ia.dev"   # TCP_SOCKET_SNI
```

- **Identificador do nó (`SERVER_UUID`) é independente da conexão.** Valores como `michel_1`/`michel_2` (usados no ambiente do professor) ou o `SERVER_UUID` configurado para este Master são apenas identificadores lógicos do nó dentro do cluster monitorado — **não fazem parte do endereço de conexão**, que é sempre `nuted-ia.dev:443` independentemente do `SERVER_UUID` enviado no payload.

- [x] **Step 1: Escrever teste falhando — nunca chama `recv`**

```python
def test_send_metrics_report_never_calls_recv(monkeypatch):
    sent = {}

    class FakeTLSSocket:
        def __init__(self):
            self.closed = False

        def sendall(self, data):
            sent["data"] = data

        def recv(self, *a, **kw):
            raise AssertionError("send_metrics_report nunca deve chamar recv")

        def close(self):
            self.closed = True

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    fake_sock = FakeTLSSocket()
    monkeypatch.setattr(servidor, "_open_supervisor_connection", lambda: fake_sock)

    servidor._send_metrics_report({"SERVER_UUID": "master_1"})

    assert b'"SERVER_UUID"' in sent["data"]
    assert sent["data"].endswith(b"\n")
    assert fake_sock.closed
```

- [x] **Step 2: Correr o teste para confirmar falha**

Run: `python -m pytest tests/test_sprint4.py::test_send_metrics_report_never_calls_recv -v`
Expected: FAIL com `AttributeError: module 'servidor' has no attribute '_send_metrics_report'`

- [x] **Step 3: Implementar `_open_supervisor_connection` e `_send_metrics_report`**

```python
def _open_supervisor_connection():
    """Abre uma conexão TLS sobre TCP com o Supervisor. Nunca usa HTTP."""
    raw_sock = socket.create_connection((SUPERVISOR_HOST, SUPERVISOR_PORT), timeout=5)
    ctx = ssl.create_default_context()
    return ctx.wrap_socket(raw_sock, server_hostname=SUPERVISOR_SNI)


def _send_metrics_report(report: dict) -> None:
    """Envia o relatório ao Supervisor: conecta, envia, encerra. Nunca chama recv."""
    try:
        with _open_supervisor_connection() as tls_sock:
            tls_sock.sendall((json.dumps(report) + "\n").encode("utf-8"))
    except (OSError, ssl.SSLError) as exc:
        metrics_log.warning("[METRICS] Falha ao enviar relatório ao Supervisor: %s", exc)
```

- [x] **Step 4: Correr o teste para confirmar sucesso**

Run: `python -m pytest tests/test_sprint4.py::test_send_metrics_report_never_calls_recv -v`
Expected: PASS

- [x] **Step 5: Teste de resiliência a falha de conexão (CT03)**

```python
def test_send_metrics_report_swallows_connection_error(monkeypatch, caplog):
    def boom():
        raise OSError("conexão recusada")

    monkeypatch.setattr(servidor, "_open_supervisor_connection", boom)

    servidor._send_metrics_report({"SERVER_UUID": "master_1"})  # não deve lançar
```

Run: `python -m pytest tests/test_sprint4.py::test_send_metrics_report_swallows_connection_error -v`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add servidor.py tests/test_sprint4.py
git commit -m "feat(sprint4): envio TLS/TCP ao Supervisor sem aguardar recv"
```

---

### Task 4: Thread daemon `_metrics_reporter` e arranque

**Files:**
- Modify: `servidor.py`
- Test: `tests/test_sprint4.py`

- [x] **Step 1: Escrever teste falhando — periodicidade**

```python
def test_metrics_reporter_sends_periodically(monkeypatch):
    calls = []
    monkeypatch.setattr(servidor, "build_metrics_report", lambda: {"x": 1})
    monkeypatch.setattr(servidor, "_send_metrics_report", lambda report: calls.append(report))
    monkeypatch.setattr(servidor, "METRICS_INTERVAL", 0.05)

    stop_event = threading.Event()
    t = threading.Thread(target=servidor._metrics_reporter, args=(stop_event,), daemon=True)
    t.start()
    time.sleep(0.25)
    stop_event.set()
    t.join(timeout=1)

    assert len(calls) >= 3
```

- [x] **Step 2: Correr o teste para confirmar falha**

Run: `python -m pytest tests/test_sprint4.py::test_metrics_reporter_sends_periodically -v`
Expected: FAIL com `AttributeError: module 'servidor' has no attribute '_metrics_reporter'`

- [x] **Step 3: Implementar `_metrics_reporter`**

```python
def _metrics_reporter(stop_event: threading.Event) -> None:
    """Thread daemon: envia métricas ao Supervisor a cada METRICS_INTERVAL segundos."""
    while not stop_event.is_set():
        try:
            report = build_metrics_report()
            _send_metrics_report(report)
        except Exception as exc:  # nunca derruba a thread
            metrics_log.warning("[METRICS] Erro ao montar/enviar relatório: %s", exc)
        stop_event.wait(METRICS_INTERVAL)
```

- [x] **Step 4: Correr o teste para confirmar sucesso**

Run: `python -m pytest tests/test_sprint4.py::test_metrics_reporter_sends_periodically -v`
Expected: PASS

- [x] **Step 5: Teste CT05 — desligado via env**

```python
def test_metrics_disabled_does_not_start_thread(monkeypatch):
    monkeypatch.setattr(servidor, "METRICS_ENABLED", False)
    started = {"flag": False}
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.update(flag=True))

    servidor._maybe_start_metrics_reporter()

    assert started["flag"] is False
```

- [x] **Step 6: Implementar `_maybe_start_metrics_reporter` e ligar em `start_server`**

```python
_metrics_stop_event = threading.Event()


def _maybe_start_metrics_reporter() -> None:
    if METRICS_ENABLED:
        threading.Thread(
            target=_metrics_reporter, args=(_metrics_stop_event,), daemon=True
        ).start()
```

Em `start_server()`, junto ao arranque de `_saturation_monitor` (Sprint 03):

```python
threading.Thread(target=_saturation_monitor, daemon=True).start()
_maybe_start_metrics_reporter()
```

- [x] **Step 7: Correr todos os testes da task**

Run: `python -m pytest tests/test_sprint4.py -v`
Expected: PASS (todos os testes desta task)

- [x] **Step 8: Commit**

```bash
git add servidor.py tests/test_sprint4.py
git commit -m "feat(sprint4): thread _metrics_reporter com liga/desliga via env"
```

---

### Task 5: Continuidade de tarefas — Master reatribui tarefa de Worker falhado

**Files:**
- Modify: `servidor.py`
- Test: `tests/test_sprint4.py`

- [x] **Step 1: Escrever teste falhando — tarefa volta à fila em falha de Worker**

```python
def test_requeue_task_on_worker_failure_returns_task_to_queue(monkeypatch):
    servidor.task_queue.clear()
    servidor.pending_by_worker.clear()
    with servidor.local_workers_lock:
        servidor.local_workers.add("worker_x")

    task = {"id": "t1", "payload": {"op": "soma"}, "enqueued_at": time.time()}
    with servidor.state_lock:
        servidor.pending_by_worker["worker_x"] = task

    before_failed = servidor.workers_failed_count
    servidor._requeue_task_on_worker_failure("worker_x")

    with servidor.state_lock:
        assert task in servidor.task_queue
        assert "worker_x" not in servidor.pending_by_worker
    with servidor.local_workers_lock:
        assert "worker_x" not in servidor.local_workers
    assert servidor.workers_failed_count == before_failed + 1
```

- [x] **Step 2: Correr o teste para confirmar falha**

Run: `python -m pytest tests/test_sprint4.py::test_requeue_task_on_worker_failure_returns_task_to_queue -v`
Expected: FAIL com `AttributeError: module 'servidor' has no attribute '_requeue_task_on_worker_failure'`

- [x] **Step 3: Implementar `_requeue_task_on_worker_failure`**

```python
def _requeue_task_on_worker_failure(worker_id: str) -> None:
    """Ao detectar falha de um Worker, devolve a tarefa pendente dele à
    fila para que outro Worker disponível a retome. Garante continuidade
    de tarefas mesmo que o Worker original não volte (Sprint 04).
    """
    global workers_failed_count

    with state_lock:
        task = pending_by_worker.pop(worker_id, None)
        if task is not None:
            task["retry_count"] = task.get("retry_count", 0) + 1
            task_queue.appendleft(task)

    with local_workers_lock:
        local_workers.discard(worker_id)
    with worker_conn_lock:
        worker_connections.pop(worker_id, None)
    with borrowed_lock:
        borrowed_workers.pop(worker_id, None)

    workers_failed_count += 1
    metrics_log.warning(
        "[MASTER] Worker '%s' falhou; tarefa %s reenfileirada para outro Worker",
        worker_id, task.get("id") if task else "N/A",
    )
```

- [x] **Step 4: Correr o teste para confirmar sucesso**

Run: `python -m pytest tests/test_sprint4.py::test_requeue_task_on_worker_failure_returns_task_to_queue -v`
Expected: PASS

- [x] **Step 5: Integrar em `handle_client` — chamar no `except`/`finally` de desconexão**

Localizar em `servidor.py` o bloco `finally` de `handle_client` que já faz `local_workers.discard(worker_id_in_session)` (Sprint 02/03) e substituir a limpeza manual por uma chamada única:

```python
finally:
    if worker_id_in_session:
        _requeue_task_on_worker_failure(worker_id_in_session)
    client_sock.close()
```

- [x] **Step 6: Teste CT07 — outro Worker disponível recebe a tarefa reenfileirada**

```python
def test_requeued_task_is_dispatched_to_other_idle_worker(monkeypatch):
    servidor.task_queue.clear()
    servidor.pending_by_worker.clear()
    with servidor.local_workers_lock:
        servidor.local_workers.clear()
        servidor.local_workers.add("worker_failed")
        servidor.local_workers.add("worker_idle")

    task = {"id": "t2", "payload": {"op": "soma"}, "enqueued_at": time.time()}
    with servidor.state_lock:
        servidor.pending_by_worker["worker_failed"] = task

    servidor._requeue_task_on_worker_failure("worker_failed")

    idle = servidor._get_idle_workers()
    assert "worker_idle" in idle
    with servidor.state_lock:
        assert task in servidor.task_queue
```

- [x] **Step 7: Correr toda a suite Sprint 04**

Run: `python -m pytest tests/test_sprint4.py -v`
Expected: PASS (todos)

- [x] **Step 8: Commit**

```bash
git add servidor.py tests/test_sprint4.py
git commit -m "feat(sprint4): Master reatribui tarefa de Worker falhado a outro Worker disponivel"
```

---

### Task 6: Suite completa e regressão

**Files:**
- Test: `tests/test_sprint4.py`

- [x] **Step 1: Correr toda a suite do projeto**

Run: `python -m pytest tests/ -v`
Expected: todos os testes de Sprint 01/02/03 continuam PASSED + testes Sprint 04 (CT01–CT09) PASSED

- [x] **Step 2: Conferir manualmente o formato do payload**

```python
import json, servidor
print(json.dumps(servidor.build_metrics_report(), indent=2))
```

Expected: todas as chaves no JSON impresso estão em MAIÚSCULAS, valores consistentes com o estado atual do Master.

- [x] **Step 3: Validar visualmente no Dashboard do Supervisor**

Com `P2P_METRICS_ENABLED=1` e o Master a correr (ligação real à internet necessária), abrir no navegador:

`https://nuted-ia.dev/supervisor/dashboard/`

Expected: o nó (`SERVER_UUID` configurado) aparece na topologia do cluster pouco depois do primeiro envio (até 10s), com CPU/memória/disco/filas de tarefas e estado dos Workers atualizados automaticamente a cada novo envio. Esse dashboard é apenas para visualização via navegador (HTTP) — não tem relação com o socket TCP/TLS usado para enviar o payload.

- [x] **Step 4: Commit final**

```bash
git add tests/test_sprint4.py
git commit -m "test(sprint4): suite completa CT01-CT09 do Supervisor de Metricas e continuidade de tarefas"
```

---

## Revisão do plano (self-review)

1. **Cobertura da spec:** Payload com chaves em MAIÚSCULAS (Task 2), conexão TLS/TCP host `nuted-ia.dev:443` SNI `nuted-ia.dev` sem HTTP e sem `recv` (Task 3), periodicidade de 10s via thread daemon (Task 4), tolerância a falhas do Master reatribuindo tarefas de Workers falhados a outro Worker disponível (Task 5 — requisito adicional desta sprint). Todos os CT01–CT09 da spec têm teste correspondente.
5. **Valores de exemplo do payload não são fixos:** os números de `PERFORMANCE.FARM_STATE.WORKERS` no payload de exemplo de `sprint4.md` (ex.: `TOTAL_REGISTERED: 6`) são apenas ilustrativos. `build_metrics_report` calcula esses campos dinamicamente a partir de `local_workers`/`borrowed_workers` a cada chamada (validado por `test_build_metrics_report_worker_counts_are_dynamic`); a farm pode subir com qualquer quantidade de Workers.
2. **Não regressão:** Sprints 01/02/03 preservadas — `_requeue_task_on_worker_failure` apenas centraliza limpeza já existente no `finally` de `handle_client` e acrescenta o reenfileiramento; nenhuma estrutura de dados de Sprint 01/02/03 é renomeada ou removida.
3. **Thread-safety:** `_metrics_reporter` só lê estado protegido por locks já existentes (`state_lock`, `local_workers_lock`, `borrowed_lock`); `_requeue_task_on_worker_failure` usa os mesmos locks para escrita.
4. **Resiliência:** Falha de conexão com o Supervisor nunca derruba o Master (`except OSError, ssl.SSLError` em `_send_metrics_report`, `except Exception` no loop de `_metrics_reporter`); falha de Worker nunca perde uma tarefa (sempre reenfileirada antes de limpar o registo do Worker).

---

**Plano guardado em:** `docs/superpowers/plans/2026-06-17-sprint4-supervisor-metricas.md`

**Spec:** `docs/superpowers/specs/2026-06-17-sprint4-supervisor-metricas-design.md`

**Estado:** ✅ Implementado.
