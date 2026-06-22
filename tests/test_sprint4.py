"""Testes Sprint 04 — cobre CT01 a CT09 (Supervisor de Métricas + continuidade de tarefas)."""
import json
import threading
import time

import servidor


def test_build_metrics_report_keys_are_lowercase():
    report = servidor.build_metrics_report()
    assert report["server_uuid"]
    assert report["role"] == "master"
    assert report["task"] == "performance_report"
    assert "performance" in report
    perf = report["performance"]
    assert "system" in perf and "farm_state" in perf and "config_thresholds" in perf and "neighbors" in perf
    assert "uptime_seconds" in perf["system"]
    assert "usage_percent" in perf["system"]["cpu"]
    assert "total_mb" in perf["system"]["memory"]
    assert "total_gb" in perf["system"]["disk"]
    workers = perf["farm_state"]["workers"]
    assert "total_registered" in workers and "borrowed_workers" in workers
    tasks = perf["farm_state"]["tasks"]
    assert "tasks_pending" in tasks and "oldest_task_age_s" in tasks
    thresholds = perf["config_thresholds"]
    assert thresholds["max_task"] >= 0
    json.dumps(report)  # deve ser serializável


def test_build_metrics_report_worker_counts_are_dynamic():
    """Os valores de WORKERS.* nao sao fixos: devem refletir o estado
    real da farm no momento da chamada, nao um numero fixo de exemplo."""
    with servidor.local_workers_lock:
        servidor.local_workers.clear()
        servidor.local_workers.add("worker_a")

    report_one_worker = servidor.build_metrics_report()
    assert report_one_worker["performance"]["farm_state"]["workers"]["total_registered"] == 1

    with servidor.local_workers_lock:
        servidor.local_workers.add("worker_b")
        servidor.local_workers.add("worker_c")

    report_three_workers = servidor.build_metrics_report()
    assert report_three_workers["performance"]["farm_state"]["workers"]["total_registered"] == 3


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


def test_send_metrics_report_swallows_connection_error(monkeypatch):
    def boom():
        raise OSError("conexão recusada")

    monkeypatch.setattr(servidor, "_open_supervisor_connection", boom)

    servidor._send_metrics_report({"SERVER_UUID": "master_1"})  # não deve lançar


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


def test_metrics_disabled_does_not_start_thread(monkeypatch):
    monkeypatch.setattr(servidor, "METRICS_ENABLED", False)
    started = {"flag": False}
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.update(flag=True))

    servidor._maybe_start_metrics_reporter()

    assert started["flag"] is False


def test_requeue_task_on_worker_failure_returns_task_to_queue():
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


def test_requeued_task_is_dispatched_to_other_idle_worker():
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


def test_neighbors_last_heartbeat_reflects_m2m_observed(monkeypatch):
    from protocol import make_m2m_message, M2M_REQUEST_HELP
    import socket as socket_mod

    monkeypatch.setattr(servidor, "NEIGHBOR_MASTERS", [{"master_id": "MASTER_B", "address": "x:1"}])
    monkeypatch.setattr(servidor, "_get_idle_workers", lambda: [])

    srv_sock, cli_sock = socket_mod.socketpair()
    msg = make_m2m_message(M2M_REQUEST_HELP, {"MASTER_ID": "MASTER_B", "WORKERS_NEEDED": 1})
    t = threading.Thread(target=servidor.handle_m2m_message, args=(msg, srv_sock, "peer"), daemon=True)
    t.start()
    t.join(timeout=2)
    srv_sock.close()
    cli_sock.close()

    assert "MASTER_B" in servidor._neighbor_last_heartbeat
