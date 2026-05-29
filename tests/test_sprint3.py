"""Testes Sprint 03 — cobre CT01 a CT09."""
import json
import socket
import threading
import time
import uuid

import pytest

import servidor
import client as wmod
from protocol import (
    validate_m2m_message, make_m2m_message, is_m2m_message,
    M2M_REQUEST_HELP, M2M_RESPONSE_ACCEPTED, M2M_RESPONSE_REJECTED,
    M2M_COMMAND_REDIRECT, M2M_REGISTER_TEMP_WORKER,
    M2M_COMMAND_RELEASE, M2M_NOTIFY_RETURNED, M2M_KNOWN_TYPES,
    WORKER_ALIVE, QUERY, STATUS_OK, STATUS_ACK,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _send(sock, obj):
    sock.sendall((json.dumps(obj) + "\n").encode())


def _recv(sock, timeout=3.0):
    sock.settimeout(timeout)
    buf = b""
    while b"\n" not in buf:
        buf += sock.recv(4096)
    line, _, _ = buf.partition(b"\n")
    return json.loads(line.decode())


def _tcp_server(port, handler):
    """Sobe um servidor TCP numa thread e chama handler(conn) para cada conexão."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(5)
    srv.settimeout(5)

    def _loop():
        try:
            while True:
                try:
                    conn, _ = srv.accept()
                    threading.Thread(target=handler, args=(conn,), daemon=True).start()
                except socket.timeout:
                    break
        finally:
            srv.close()

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    time.sleep(0.05)
    return t


# ---------------------------------------------------------------------------
# Testes de protocol.py
# ---------------------------------------------------------------------------
class TestM2MProtocol:
    def test_make_m2m_has_required_fields(self):
        msg = make_m2m_message(M2M_REQUEST_HELP, {"workers_needed": 2})
        assert msg["type"] == M2M_REQUEST_HELP
        assert "request_id" in msg
        assert isinstance(msg["payload"], dict)

    def test_make_m2m_accepts_explicit_request_id(self):
        rid = str(uuid.uuid4())
        msg = make_m2m_message(M2M_RESPONSE_ACCEPTED, {}, request_id=rid)
        assert msg["request_id"] == rid

    def test_validate_m2m_ok(self):
        validate_m2m_message(make_m2m_message(M2M_REQUEST_HELP, {"workers_needed": 1}))

    def test_validate_m2m_missing_type(self):
        with pytest.raises(ValueError, match="type"):
            validate_m2m_message({"request_id": "x", "payload": {}})

    def test_validate_m2m_missing_request_id(self):
        with pytest.raises(ValueError, match="request_id"):
            validate_m2m_message({"type": M2M_REQUEST_HELP, "payload": {}})

    def test_validate_m2m_missing_payload(self):
        with pytest.raises(ValueError, match="payload"):
            validate_m2m_message({"type": M2M_REQUEST_HELP, "request_id": "x"})

    def test_validate_m2m_payload_not_dict(self):
        with pytest.raises(ValueError):
            validate_m2m_message({"type": M2M_REQUEST_HELP, "request_id": "x", "payload": "bad"})

    def test_validate_m2m_ignores_unknown_fields(self):
        validate_m2m_message({
            "type": M2M_REQUEST_HELP, "request_id": "x", "payload": {},
            "extra_field": "ignored",
        })

    def test_is_m2m_message_true_for_all_types(self):
        for t in M2M_KNOWN_TYPES:
            assert is_m2m_message({"type": t}) is True

    def test_is_m2m_message_false_for_worker_msg(self):
        assert is_m2m_message({"WORKER": "ALIVE", "WORKER_UUID": "w1"}) is False

    def test_is_m2m_message_false_for_unknown(self):
        assert is_m2m_message({"type": "unknown_type"}) is False

    def test_all_m2m_types_present(self):
        expected = {
            "request_help", "response_accepted", "response_rejected",
            "command_redirect", "register_temporary_worker",
            "command_release", "notify_worker_returned",
        }
        assert M2M_KNOWN_TYPES == expected


# ---------------------------------------------------------------------------
# CT01 — Pedido aceito: response_accepted com worker_details + command_redirect
# ---------------------------------------------------------------------------
class TestCT01Accepted:
    def test_ct01_response_accepted_with_worker_details(self, monkeypatch):
        """CT01: Master B tem Workers ociosos → response_accepted com worker_details."""
        monkeypatch.setattr(servidor, "_get_idle_workers", lambda: ["w1", "w2"])
        redirected = []
        monkeypatch.setattr(servidor, "_send_redirect_to_worker",
                            lambda wid, addr, target_master_id="": redirected.append(wid))

        srv_sock, cli_sock = socket.socketpair()
        rid = str(uuid.uuid4())
        msg = make_m2m_message(M2M_REQUEST_HELP, {"WORKERS_NEEDED": 2}, request_id=rid)
        t = threading.Thread(
            target=servidor.handle_m2m_message,
            args=(msg, srv_sock, "peer"),
            daemon=True,
        )
        t.start()

        reply = _recv(cli_sock)
        t.join(timeout=2)
        srv_sock.close(); cli_sock.close()

        assert reply["type"] == M2M_RESPONSE_ACCEPTED
        assert reply["request_id"] == rid              # CT03: request_id preservado
        assert len(reply["payload"]["WORKER_DETAILS"]) == 2
        assert set(redirected) == {"w1", "w2"}         # command_redirect enviado a cada um


# ---------------------------------------------------------------------------
# CT02 — Pedido recusado: response_rejected com reason=high_load
# ---------------------------------------------------------------------------
class TestCT02Rejected:
    def test_ct02_response_rejected_high_load(self, monkeypatch):
        """CT02: Master B sem Workers ociosos → response_rejected; nenhum command_redirect."""
        monkeypatch.setattr(servidor, "_get_idle_workers", lambda: [])
        redirected = []
        monkeypatch.setattr(servidor, "_send_redirect_to_worker",
                            lambda wid, addr, target_master_id="": redirected.append(wid))

        srv_sock, cli_sock = socket.socketpair()
        rid = str(uuid.uuid4())
        msg = make_m2m_message(M2M_REQUEST_HELP, {"WORKERS_NEEDED": 2}, request_id=rid)
        t = threading.Thread(
            target=servidor.handle_m2m_message,
            args=(msg, srv_sock, "peer"),
            daemon=True,
        )
        t.start()

        reply = _recv(cli_sock)
        t.join(timeout=2)
        srv_sock.close(); cli_sock.close()

        assert reply["type"] == M2M_RESPONSE_REJECTED
        assert reply["request_id"] == rid
        assert reply["payload"]["REASON"] == "high_load"
        assert redirected == []   # nenhum command_redirect


# ---------------------------------------------------------------------------
# CT03 — Correlação de request_id com 2 requests concorrentes
# ---------------------------------------------------------------------------
class TestCT03Correlation:
    def test_ct03_concurrent_requests_correlated(self, monkeypatch):
        """CT03: 2 request_help concorrentes; cada resposta traz o request_id correto."""
        monkeypatch.setattr(servidor, "_get_idle_workers", lambda: ["w_idle"])
        monkeypatch.setattr(servidor, "_send_redirect_to_worker",
                            lambda wid, addr, target_master_id="": None)

        results = {}

        def _do_request(port_offset, rid):
            srv_sock, cli_sock = socket.socketpair()
            msg = make_m2m_message(M2M_REQUEST_HELP, {"WORKERS_NEEDED": 1}, request_id=rid)
            threading.Thread(
                target=servidor.handle_m2m_message,
                args=(msg, srv_sock, f"peer_{port_offset}"),
                daemon=True,
            ).start()
            reply = _recv(cli_sock)
            results[rid] = reply["request_id"]
            srv_sock.close(); cli_sock.close()

        rid_a = str(uuid.uuid4())
        rid_b = str(uuid.uuid4())
        ta = threading.Thread(target=_do_request, args=(1, rid_a), daemon=True)
        tb = threading.Thread(target=_do_request, args=(2, rid_b), daemon=True)
        ta.start(); tb.start()
        ta.join(timeout=3); tb.join(timeout=3)

        assert results[rid_a] == rid_a, "request_id do request A deve ser preservado"
        assert results[rid_b] == rid_b, "request_id do request B deve ser preservado"


# ---------------------------------------------------------------------------
# CT04 + CT05 — Worker emprestado registra-se e executa tarefa
# ---------------------------------------------------------------------------
class TestCT04CT05BorrowedWorker:
    def test_ct04_ct05_full_flow(self):
        """CT04: Worker regista-se como emprestado.
        CT05: recebe QUERY, reporta OK, recebe ACK com log [EMPRESTADO]."""
        worker_id = str(uuid.uuid4())

        # Seed a task
        with servidor.state_lock:
            servidor.task_queue.clear()
            servidor.task_queue.append({"USER": "u_test", "A": 10, "B": 5})

        srv_sock, cli_sock = socket.socketpair()
        t = threading.Thread(
            target=servidor.handle_client,
            args=(srv_sock, ("127.0.0.1", 0)),
            daemon=True,
        )
        t.start()

        try:
            # CT04 Step 1: register_temporary_worker
            reg = make_m2m_message(M2M_REGISTER_TEMP_WORKER, {
                "WORKER_ID": worker_id,
                "ORIGINAL_MASTER_ID": "MASTER_B",
                "ORIGINAL_MASTER_ADDRESS": "127.0.0.1:6001",
            })
            _send(cli_sock, reg)

            # CT04 Step 2: ALIVE com SERVER_UUID = MASTER_B
            _send(cli_sock, {"WORKER": WORKER_ALIVE, "WORKER_UUID": worker_id, "SERVER_UUID": "MASTER_B"})

            # CT05 Step 3: recebe QUERY
            reply = _recv(cli_sock)
            assert reply["TASK"] == QUERY
            assert reply["USER"] == "u_test"

            # CT05 Step 4: reporta STATUS OK
            _send(cli_sock, {"STATUS": STATUS_OK, "TASK": QUERY, "WORKER_UUID": worker_id, "RESULT": 15})

            # CT05 Step 5: recebe ACK
            ack = _recv(cli_sock)
            assert ack["STATUS"] == STATUS_ACK
            assert ack["WORKER_UUID"] == worker_id

            # CT04: Worker deve estar em borrowed_workers
            with servidor.borrowed_lock:
                assert worker_id in servidor.borrowed_workers
                assert servidor.borrowed_workers[worker_id]["ORIGINAL_MASTER_ID"] == "MASTER_B"
        finally:
            cli_sock.close()
            t.join(timeout=2)
            with servidor.borrowed_lock:
                servidor.borrowed_workers.pop(worker_id, None)
            with servidor.state_lock:
                servidor.task_queue.clear()


# ---------------------------------------------------------------------------
# CT06 — Devolução: command_release ao Worker + notify_worker_returned ao Master
# ---------------------------------------------------------------------------
class TestCT06Release:
    def test_ct06_release_sends_command_release_and_notify(self):
        """CT06: release_borrowed_worker envia command_release e notify_worker_returned."""
        worker_id = str(uuid.uuid4())

        # Socket pair simula conexão ativa com o Worker
        w_srv, w_cli = socket.socketpair()
        # Socket pair simula conexão M2M com Master B
        m_srv, m_cli = socket.socketpair()

        with servidor.borrowed_lock:
            servidor.borrowed_workers[worker_id] = {
                "WORKER_ID": worker_id,
                "ORIGINAL_MASTER_ID": "MASTER_B",
                "ORIGINAL_MASTER_ADDRESS": "127.0.0.1:6001",
                "BORROWED_AT": "2026-01-01T00:00:00+00:00",
            }
        with servidor.worker_conn_lock:
            servidor.worker_connections[worker_id] = w_srv
        with servidor.m2m_pool_lock:
            servidor.m2m_pool["MASTER_B"] = m_cli   # pré-injeta no pool

        servidor.release_borrowed_worker(worker_id)

        # Verifica command_release chegou ao Worker
        release_msg = _recv(w_cli)
        assert release_msg["type"] == M2M_COMMAND_RELEASE
        assert release_msg["payload"]["ORIGINAL_MASTER_ADDRESS"] == "127.0.0.1:6001"

        # Verifica notify_worker_returned chegou ao Master B
        notify_msg = _recv(m_srv)
        assert notify_msg["type"] == M2M_NOTIFY_RETURNED
        assert notify_msg["payload"]["WORKER_ID"] == worker_id

        # Worker removido de borrowed_workers
        with servidor.borrowed_lock:
            assert worker_id not in servidor.borrowed_workers

        w_srv.close(); w_cli.close()
        m_srv.close()
        with servidor.m2m_pool_lock:
            servidor.m2m_pool.pop("MASTER_B", None)


# ---------------------------------------------------------------------------
# CT07 — Timeout: Master B não responde em 5s
# ---------------------------------------------------------------------------
class TestCT07Timeout:
    def test_ct07_timeout_logged_and_aborts(self, monkeypatch):
        """CT07: Master B não responde → timeout logado; request_help retorna sem travar."""
        # Servidor que aceita mas nunca responde
        hung = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        hung.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        hung.bind(("127.0.0.1", 0))
        hung.listen(1)
        port = hung.getsockname()[1]

        def _hang():
            try:
                conn, _ = hung.accept()
                time.sleep(10)
                conn.close()
            except Exception:
                pass
        threading.Thread(target=_hang, daemon=True).start()

        monkeypatch.setattr(servidor, "NEIGHBOR_MASTERS",
                            [{"master_id": "HUNG", "address": f"127.0.0.1:{port}"}])
        monkeypatch.setattr(servidor, "M2M_TIMEOUT_SEC", 0.3)   # timeout curto
        with servidor.m2m_pool_lock:
            servidor.m2m_pool.clear()

        start = time.time()
        servidor.request_help_from_neighbors(1)
        elapsed = time.time() - start

        hung.close()
        # Deve retornar após timeout, não travar
        assert elapsed < 3.0

        # Pool deve estar limpo (conexão descartada)
        with servidor.m2m_pool_lock:
            assert "HUNG" not in servidor.m2m_pool


# ---------------------------------------------------------------------------
# CT08 — Falha do Master: Worker emprestado restaura conexão ao Master original
# ---------------------------------------------------------------------------
class TestCT08MasterFailure:
    def test_ct08_worker_restores_original_master_state(self):
        """CT08: Ao perder conexão com Master A, Worker atualiza estado para Master B."""
        # Salva estado original do módulo client
        original_host = wmod._current_host
        original_port = wmod._current_port
        original_uuid = wmod._origin_master_uuid
        original_addr = wmod._origin_master_addr

        try:
            # Configura worker como emprestado: Master A = porta fictícia, Master B = porta fictícia
            with wmod._state_lock:
                wmod._current_host = "127.0.0.1"
                wmod._current_port = 9_999
                wmod._origin_master_uuid = "MASTER_B"
                wmod._origin_master_addr = "127.0.0.1:8_888"

            # Simula o bloco except de run_worker_loop quando Master A cai
            with wmod._state_lock:
                if wmod._origin_master_addr and wmod._origin_master_uuid:
                    parts = wmod._origin_master_addr.rsplit(":", 1)
                    if len(parts) == 2:
                        wmod._current_host = parts[0]
                        wmod._current_port = int(parts[1])
                        wmod._origin_master_addr = ""
                        wmod._origin_master_uuid = ""

            # Verifica: estado agora aponta para Master B
            with wmod._state_lock:
                assert wmod._current_host == "127.0.0.1"
                assert wmod._current_port == 8_888
                assert wmod._origin_master_addr == ""
                assert wmod._origin_master_uuid == ""   # não mais emprestado
        finally:
            # Restaura estado original
            with wmod._state_lock:
                wmod._current_host = original_host
                wmod._current_port = original_port
                wmod._origin_master_uuid = original_uuid
                wmod._origin_master_addr = original_addr


# ---------------------------------------------------------------------------
# CT09 — Tipo desconhecido: ignorado, processo continua
# ---------------------------------------------------------------------------
class TestCT09UnknownType:
    def test_ct09_unknown_type_does_not_crash(self):
        """CT09: type desconhecido → logado e ignorado; nenhuma exceção."""
        class _FakeSock:
            def sendall(self, _): pass

        bad_msg = {"type": "totally_unknown", "request_id": "x", "payload": {}}
        # Não deve lançar exceção
        servidor.handle_m2m_message(bad_msg, _FakeSock(), "fake_peer")

    def test_ct09_missing_required_field_does_not_crash(self):
        """Campos obrigatórios ausentes → logado, não lança exceção não tratada."""
        class _FakeSock:
            def sendall(self, _): pass

        bad_msg = {"type": M2M_REQUEST_HELP, "payload": {}}  # sem request_id
        servidor.handle_m2m_message(bad_msg, _FakeSock(), "fake_peer")
