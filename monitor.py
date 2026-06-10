"""Sprint 04 — Monitor de Métricas do Cluster.

Coleta métricas do sistema (CPU, memória, disco) e do estado da Farm (Workers,
tarefas, thresholds, vizinhos) e envia periodicamente ao Supervisor via TLS/TCP.

Regras da Sprint 04:
  - Conexão TLS sobre TCP pura (sem HTTP)
  - Envia JSON e fecha a conexão sem aguardar resposta (fire-and-forget)
  - Intervalo de envio: 10 segundos
  - Host: nuted-ia.dev  Porta: 443  SNI: nuted-ia.dev

O módulo é desacoplado do estado do servidor via um objeto MonitorContext que
recebe funções de leitura de estado em tempo de construção — facilita testes
unitários sem precisar subir o servidor completo.
"""
from __future__ import annotations

import json
import socket
import ssl
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

try:
    import psutil  # métricas reais de CPU / memória / disco
    _PSUTIL_OK = True
except ImportError:
    _PSUTIL_OK = False

# ---------------------------------------------------------------------------
# Configuração da conexão com o Supervisor
# ---------------------------------------------------------------------------

SUPERVISOR_HOST = "nuted-ia.dev"
SUPERVISOR_PORT = 443
SUPERVISOR_SNI  = "nuted-ia.dev"

# Intervalo entre envios de métricas (segundos) — conforme especificação Sprint 04
MONITOR_INTERVAL_SEC = 10

# Versão do schema do payload — permite o dashboard identificar o formato
PAYLOAD_VERSION = "sprint4-monitor"


# ---------------------------------------------------------------------------
# Coleta de métricas do sistema operacional
# ---------------------------------------------------------------------------

def _collect_system_metrics() -> dict:
    """Retorna métricas do SO via psutil.

    Em caso de psutil indisponível, retorna valores zerados para não
    interromper o servidor por falta de uma dependência de monitoramento.
    """
    if not _PSUTIL_OK:
        return {
            "uptime_seconds": 0,
            "load_average_1m": 0.0,
            "load_average_5m": 0.0,
            "cpu": {
                "usage_percent": 0.0,
                "count_logical": 0,
                "count_physical": 0,
            },
            "memory": {
                "total_mb": 0,
                "available_mb": 0,
                "percent_used": 0.0,
                "memory_used": 0,
            },
            "disk": {
                "total_gb": 0.0,
                "free_gb": 0.0,
                "percent_used": 0.0,
            },
        }

    # Uptime: diferença entre agora e o momento de boot do sistema
    uptime_s = int(time.time() - psutil.boot_time())

    # Load average: disponível em Linux/Mac; no Windows retorna (0, 0, 0)
    try:
        load1, load5, _ = psutil.getloadavg()
    except AttributeError:
        load1, load5 = 0.0, 0.0

    # CPU
    cpu_pct    = psutil.cpu_percent(interval=None)
    cpu_log    = psutil.cpu_count(logical=True) or 0
    cpu_phys   = psutil.cpu_count(logical=False) or 0

    # Memória RAM
    mem        = psutil.virtual_memory()
    total_mb   = int(mem.total   / 1024 / 1024)
    avail_mb   = int(mem.available / 1024 / 1024)
    used_mb    = int(mem.used    / 1024 / 1024)

    # Disco (partição raiz)
    disk       = psutil.disk_usage("/")
    total_gb   = round(disk.total / 1024 / 1024 / 1024, 2)
    free_gb    = round(disk.free  / 1024 / 1024 / 1024, 2)
    disk_pct   = round(disk.percent, 2)

    return {
        "uptime_seconds":   uptime_s,
        "load_average_1m":  round(load1, 2),
        "load_average_5m":  round(load5, 2),
        "cpu": {
            "usage_percent":   round(cpu_pct, 2),
            "count_logical":   cpu_log,
            "count_physical":  cpu_phys,
        },
        "memory": {
            "total_mb":      total_mb,
            "available_mb":  avail_mb,
            "percent_used":  round(mem.percent, 2),
            "memory_used":   used_mb,
        },
        "disk": {
            "total_gb":     total_gb,
            "free_gb":      free_gb,
            "percent_used": disk_pct,
        },
    }


# ---------------------------------------------------------------------------
# MonitorContext — desacopla o monitor do estado global do servidor
# ---------------------------------------------------------------------------

class MonitorContext:
    """Encapsula as dependências de estado que o monitor precisa ler do servidor.

    Cada campo é uma função sem argumentos (thunk) que retorna o valor atual.
    Isso permite substituir por lambdas de teste sem precisar de mocks complexos.
    """

    def __init__(
        self,
        server_uuid:            str,
        hostname:               str,
        saturation_threshold:   int,
        release_threshold:      int,
        get_local_workers:      Callable[[], set],
        get_borrowed_workers:   Callable[[], dict],   # workers recebidos (direction "in")
        get_lent_workers:       Callable[[], dict],   # workers enviados (direction "out")
        get_pending_by_worker:  Callable[[], dict],
        get_task_queue_len:     Callable[[], int],
        get_tasks_completed:    Callable[[], int],
        get_tasks_failed:       Callable[[], int],
        get_neighbor_masters:   Callable[[], list],
    ) -> None:
        self.server_uuid           = server_uuid
        self.hostname              = hostname
        self.saturation_threshold  = saturation_threshold
        self.release_threshold     = release_threshold
        self._get_local_workers    = get_local_workers
        self._get_borrowed_workers = get_borrowed_workers
        self._get_lent_workers     = get_lent_workers
        self._get_pending          = get_pending_by_worker
        self._get_queue_len        = get_task_queue_len
        self._get_completed        = get_tasks_completed
        self._get_failed           = get_tasks_failed
        self._get_neighbors        = get_neighbor_masters


# ---------------------------------------------------------------------------
# Construção do payload de performance conforme especificação Sprint 04
# ---------------------------------------------------------------------------

def build_performance_report(ctx: MonitorContext) -> dict:
    """Monta o payload completo de performance_report exigido pela Sprint 04.

    Combina métricas do SO (via psutil) com estado interno da Farm
    (workers, tarefas, thresholds, vizinhos) coletados do MonitorContext.
    """
    local_workers   = ctx._get_local_workers()    # set de IDs
    borrowed_w      = ctx._get_borrowed_workers()  # dict worker_id -> info (recebidos)
    lent_w          = ctx._get_lent_workers()      # dict worker_id -> peer_id (enviados)
    pending         = ctx._get_pending()           # dict worker_id -> task_info

    # Contagens derivadas do estado atual
    total_registered  = len(local_workers) + len(borrowed_w)
    workers_busy      = len(pending)                    # executando tarefas
    workers_idle      = max(0, len(local_workers) - workers_busy)
    workers_received  = len(borrowed_w)                 # recebidos de outros masters
    workers_borrowed  = len(lent_w)                     # emprestados a outros masters
    workers_home      = len(local_workers)              # nativos deste servidor

    # Lista de workers emprestados com direção e peer
    borrowed_list: list[dict] = []
    for wid, peer_id in lent_w.items():
        borrowed_list.append({"direction": "out", "peer_uuid": peer_id})
    for wid, info in borrowed_w.items():
        borrowed_list.append({"direction": "in", "peer_uuid": info.get("ORIGINAL_MASTER_ID", "")})

    # Estado das tarefas
    tasks_pending   = ctx._get_queue_len()
    tasks_running   = workers_busy
    tasks_completed = ctx._get_completed()
    tasks_failed    = ctx._get_failed()

    # Vizinhos com status e último heartbeat conhecido
    neighbors_list: list[dict] = []
    for n in ctx._get_neighbors():
        neighbors_list.append({
            "server_uuid":    n.get("master_id", ""),
            "status":         "available",
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        })

    return {
        "server_uuid":    ctx.server_uuid,
        "hostname":       ctx.hostname,
        "role":           "master",
        "task":           "performance_report",
        "timestamp":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "message_id":     str(uuid.uuid4()),
        "payload_version": PAYLOAD_VERSION,
        "performance": {
            "system": _collect_system_metrics(),
            "farm_state": {
                "workers": {
                    "total_registered":          total_registered,
                    "workers_utilization":        workers_busy,
                    "workers_alive":              total_registered,
                    "workers_idle":               workers_idle,
                    "workers_borrowed":           workers_borrowed,
                    "workers_received":           workers_received,
                    "workers_failed":             0,
                    "workers_home":               workers_home,
                    "workers_available_capacity": workers_idle,
                    "borrowed_workers":           borrowed_list,
                },
                "tasks": {
                    "tasks_pending":      tasks_pending,
                    "tasks_running":      tasks_running,
                    "tasks_completed":    tasks_completed,
                    "tasks_failed":       tasks_failed,
                    "oldest_task_age_s":  0,
                },
            },
            "config_thresholds": {
                "max_task":             ctx.saturation_threshold,
                "warn_cpu_percent":     85,
                "warn_memory_percent":  85,
                "release_task":         ctx.release_threshold,
            },
            "neighbors": neighbors_list,
        },
    }


# ---------------------------------------------------------------------------
# Envio ao Supervisor via TLS/TCP (fire-and-forget, sem RECV)
# ---------------------------------------------------------------------------

def send_to_supervisor(payload: dict) -> None:
    """Abre conexão TLS/TCP ao Supervisor, envia o JSON e fecha.

    Não aguarda resposta (especificação Sprint 04: apenas SEND).
    Em caso de falha de rede, loga e retorna sem interromper o servidor.
    """
    raw_json = json.dumps(payload) + "\n"
    encoded  = raw_json.encode("utf-8")

    # Cria contexto TLS com verificação de certificado padrão do SO
    tls_ctx = ssl.create_default_context()

    try:
        # Abre socket TCP puro e envolve com TLS (SNI configurado no wrap_socket)
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.settimeout(10)
        raw_sock.connect((SUPERVISOR_HOST, SUPERVISOR_PORT))

        tls_sock = tls_ctx.wrap_socket(raw_sock, server_hostname=SUPERVISOR_SNI)
        try:
            tls_sock.sendall(encoded)
            # Não executa recv — comportamento exigido pela Sprint 04
        finally:
            tls_sock.close()

    except Exception as e:
        # Falha de rede não deve derrubar o servidor — apenas loga
        print(f"[MONITOR] Falha ao enviar ao Supervisor: {e}")


# ---------------------------------------------------------------------------
# Loop daemon de monitoramento
# ---------------------------------------------------------------------------

def monitor_loop(ctx: MonitorContext, interval_sec: float = MONITOR_INTERVAL_SEC) -> None:
    """Loop daemon que coleta e envia métricas ao Supervisor periodicamente.

    Deve ser executado em thread daemon (não bloqueia encerramento do processo).
    Em cada ciclo:
      1. Constrói o payload de performance
      2. Envia via TLS/TCP ao Supervisor
      3. Aguarda o intervalo configurado

    Args:
        ctx:          contexto com referências ao estado do servidor
        interval_sec: intervalo entre envios (padrão: 10s conforme Sprint 04)
    """
    print(f"[MONITOR] Monitor de métricas iniciado (intervalo={interval_sec}s → {SUPERVISOR_HOST}:{SUPERVISOR_PORT})")
    while True:
        try:
            report = build_performance_report(ctx)
            send_to_supervisor(report)
        except Exception as e:
            # Garante que uma exceção inesperada não encerre o loop daemon
            print(f"[MONITOR] Erro inesperado no ciclo de métricas: {e}")
        time.sleep(interval_sec)


def start_monitor(ctx: MonitorContext) -> threading.Thread:
    """Inicia a thread daemon do monitor de métricas e a retorna.

    Separado do loop para facilitar testes (pode-se chamar apenas build_performance_report
    sem precisar subir a thread).
    """
    t = threading.Thread(target=monitor_loop, args=(ctx,), daemon=True)
    t.start()
    return t
