"""Servidor Master P2P — distribui tarefas aos Workers e coordena empréstimos M2M.

Responsabilidades:
  - Aceitar conexões TCP de Workers e Masters vizinhos
  - Distribuir tarefas da fila para Workers disponíveis
  - Coordenar empréstimo de Workers entre Masters (Sprint 03)
  - Monitorar saturação e solicitar ajuda quando a fila estiver cheia
"""
import json
import logging
import os
import socket
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from protocol import *

# ---------------------------------------------------------------------------
# Configuração (Sprint 01/02 preservada)
# ---------------------------------------------------------------------------

# Identificador único deste Master — usado em logs e no protocolo M2M
SERVER_UUID = os.environ.get("P2P_SERVER_UUID", "MASTER_1")

# Endereço e porta em que o servidor vai escutar conexões
HOST = os.environ.get("P2P_HOST", "10.62.217.42")
PORT = int(os.environ.get("P2P_PORT", "8000"))

# Fila de tarefas pendentes — Workers consomem desta fila via popleft()
task_queue: deque = deque()

# Mapa de tarefas atribuídas a Workers ainda não confirmadas (aguardando STATUS)
# Chave: WORKER_UUID | Valor: dict com TASK, USER, A, B
pending_by_worker: dict[str, dict] = {}

# Lock que protege task_queue e pending_by_worker contra acesso concorrente de threads
state_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Sprint 03: Configuração M2M via variáveis de ambiente
# ---------------------------------------------------------------------------

# Lista de Masters vizinhos para empréstimo de Workers
# Formato da env: "B=127.0.0.1:6001,C=127.0.0.1:6002"
_RAW_NEIGHBORS = os.environ.get("P2P_NEIGHBOR_MASTERS", "10.62.217.208:8000").strip()
NEIGHBOR_MASTERS: list[dict] = []
for _entry in _RAW_NEIGHBORS.split(","):
    _entry = _entry.strip()
    if "=" in _entry:
        _mid, _addr = _entry.split("=", 1)
        # Cada vizinho é um dict com master_id e address (ip:porta)
        NEIGHBOR_MASTERS.append({"master_id": _mid.strip(), "address": _addr.strip()})

# Tamanho da fila a partir do qual este Master pede ajuda a vizinhos
SATURATION_THRESHOLD = int(os.environ.get("P2P_SATURATION_THRESHOLD", "5"))

# Tamanho da fila abaixo do qual os Workers emprestados são devolvidos (histerese)
RELEASE_THRESHOLD    = int(os.environ.get("P2P_RELEASE_THRESHOLD", "2"))

# Timeout das chamadas M2M (em segundos) para não bloquear indefinidamente
M2M_TIMEOUT_SEC      = float(os.environ.get("P2P_M2M_TIMEOUT_SEC", "5"))

# Conjunto de UUIDs de Workers que estão conectados diretamente a este Master
local_workers: set[str] = set()
local_workers_lock = threading.Lock()

# Registro de Workers emprestados de outros Masters
# worker_id -> {WORKER_ID, ORIGINAL_MASTER_ID, ORIGINAL_MASTER_ADDRESS, BORROWED_AT}
borrowed_workers: dict[str, dict] = {}
borrowed_lock = threading.Lock()

# Mapa de conexões TCP ativas dos Workers (para enviar command_redirect/release assíncrono)
# Chave: WORKER_UUID | Valor: socket TCP do Worker
worker_connections: dict[str, socket.socket] = {}
worker_conn_lock = threading.Lock()

# Pool de conexões TCP reutilizáveis para comunicação M2M entre Masters
# Evita abrir/fechar sockets repetidamente para o mesmo vizinho
m2m_pool: dict[str, socket.socket] = {}
m2m_pool_lock = threading.Lock()

# Logger dedicado ao protocolo M2M com formato: timestamp | nível | mensagem
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
m2m_log = logging.getLogger("m2m")

# ---------------------------------------------------------------------------
# Tarefas (Sprint 01/02 preservadas)
# ---------------------------------------------------------------------------
tasks = [
    #User 1: Small values
    {"USER": "user1", "A": 1, "B": 5}, {"USER": "user1", "A": 3, "B": 7},
    {"USER": "user1", "A": 10, "B": 2}, {"USER": "user1", "A": 4, "B": 4},
    {"USER": "user1", "A": 9, "B": 1}, {"USER": "user1", "A": 6, "B": 8},
    #User 2: Medium values
     {"USER": "user2", "A": 15, "B": 20}, {"USER": "user2", "A": 12, "B": 18},
     {"USER": "user2", "A": 25, "B": 5}, {"USER": "user2", "A": 30, "B": 10},
     {"USER": "user2", "A": 11, "B": 11}, {"USER": "user2", "A": 14, "B": 22},
     #User 3: Large values
     {"USER": "user3", "A": 100, "B": 50}, {"USER": "user3", "A": 250, "B": 150},
     {"USER": "user3", "A": 500, "B": 500}, {"USER": "user3", "A": 120, "B": 80},
     {"USER": "user3", "A": 99, "B": 1}, {"USER": "user3", "A": 333, "B": 666},
     #User 4: Zeroes and Primes
     {"USER": "user4", "A": 0, "B": 10}, {"USER": "user4", "A": 7, "B": 13},
     {"USER": "user4", "A": 17, "B": 19}, {"USER": "user4", "A": 23, "B": 29},
     {"USER": "user4", "A": 31, "B": 0}, {"USER": "user4", "A": 2, "B": 3},
     #User 5: Mixed scale
     {"USER": "user5", "A": 1000, "B": 1}, {"USER": "user5", "A": 5, "B": 5000},
     {"USER": "user5", "A": 42, "B": 42}, {"USER": "user5", "A": 8, "B": 16},
     {"USER": "user5", "A": 64, "B": 32}, {"USER": "user5", "A": 123, "B": 456},
]


def seed_queue() -> None:
    with state_lock:
        task_queue.extend(tasks)


# ---------------------------------------------------------------------------
# Utilitários de I/O
# ---------------------------------------------------------------------------
def send_json_line(conn: socket.socket, obj: dict) -> None:
    """Serializa obj como JSON e envia ao socket com '\\n' como delimitador de mensagem."""
    conn.sendall((json.dumps(obj) + "\n").encode())


def recv_json_line(conn: socket.socket, timeout: float = M2M_TIMEOUT_SEC) -> dict:
    """Lê uma linha JSON completa de um socket, aplicando timeout.

    Acumula dados no buffer até encontrar '\\n' (delimitador de mensagem).
    Necessário porque TCP não garante que uma mensagem chegue em um único recv().
    """
    conn.settimeout(timeout)
    buf = b""
    # Continua lendo até encontrar o delimitador de fim de mensagem
    while b"\n" not in buf:
        chunk = conn.recv(4096)
        if not chunk:
            raise ConnectionError("conexão fechada antes de linha completa")
        buf += chunk
    # Extrai apenas a primeira mensagem (ignora dados além do '\n')
    line, _, _ = buf.partition(b"\n")
    return json.loads(line.decode())


# ---------------------------------------------------------------------------
# Sprint 03: Helpers de contagem
# ---------------------------------------------------------------------------
def _get_queue_size() -> int:
    """Retorna o tamanho atual da fila de tarefas de forma thread-safe."""
    with state_lock:
        return len(task_queue)


def _get_local_count() -> int:
    """Retorna o número de Workers locais conectados a este Master."""
    with local_workers_lock:
        return len(local_workers)


def _get_idle_workers() -> list[str]:
    """Sprint 03: Retorna lista de Workers locais sem tarefas pendentes.

    Um Worker é considerado ocioso se não está em pending_by_worker.
    Esses são os cand idatos a serem emprestados a Masters vizinhos.
    """
    with state_lock:
        busy = set(pending_by_worker.keys())
    with local_workers_lock:
        return [w for w in local_workers if w not in busy]


def _log_worker_counts() -> None:
    """Sprint 03: Exibe contadores de Workers locais e emprestados no log."""
    with borrowed_lock:
        b = len(borrowed_workers)
    m2m_log.info("[MASTER] Workers locais=%d emprestados=%d", _get_local_count(), b)


# ---------------------------------------------------------------------------
# Sprint 03: Log M2M estruturado
# ---------------------------------------------------------------------------
def _log_m2m(direction: str, msg: dict, peer: str) -> None:
    """Loga mensagem M2M com formato: timestamp | type | request_id | origem→destino.

    Facilita rastreamento de mensagens M2M em logs de produção.
    """
    ts = datetime.now(timezone.utc).isoformat()
    t   = msg.get("type", "?")
    rid = msg.get("request_id", "?")
    m2m_log.info("%s | %s | %s | %s", ts, t, rid, f"{direction} {peer}")


# ---------------------------------------------------------------------------
# Sprint 03: Pool de conexões M2M
# ---------------------------------------------------------------------------
def _get_m2m_conn(master_id: str, address: str) -> socket.socket:
    """Retorna conexão M2M existente ou cria nova (pool reutilizável).

    Tenta reaproveitar uma conexão TCP já aberta para o mesmo Master.
    Se a conexão estiver morta (OSError em getpeername), abre uma nova.
    """
    with m2m_pool_lock:
        conn = m2m_pool.get(master_id)
        if conn is not None:
            try:
                # Verifica se a conexão ainda está ativa
                conn.getpeername()
                return conn
            except OSError:
                # Conexão morta — vai criar uma nova abaixo
                pass
        host, port_str = address.rsplit(":", 1)
        new_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        new_conn.connect((host, int(port_str)))
        m2m_pool[master_id] = new_conn
        return new_conn


def _close_m2m_conn(master_id: str) -> None:
    """Fecha e remove conexão M2M do pool (chamado após erro ou timeout)."""
    with m2m_pool_lock:
        conn = m2m_pool.pop(master_id, None)
    if conn:
        try:
            conn.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Sprint 03: Envio de command_redirect a Worker
# ---------------------------------------------------------------------------
def _send_redirect_to_worker(worker_id: str, new_master_address: str, target_master_id: str = "") -> None:
    """Envia command_redirect via conexão TCP ativa do Worker.

    O Worker deve reconectar ao Master cujo endereço está em NEW_MASTER_ADDRESS.
    Usa a conexão já aberta em worker_connections para evitar nova abertura de socket.
    """
    # Monta mensagem M2M de redirecionamento com o endereço do novo Master
    msg = make_m2m_message(
        M2M_COMMAND_REDIRECT,
        {
            "NEW_MASTER_ADDRESS": new_master_address,  # spec: campo NEW_MASTER_ADDRESS
        },
    )
    # Busca a conexão ativa deste Worker
    with worker_conn_lock:
        wconn = worker_connections.get(worker_id)
    if wconn:
        try:
            _log_m2m("→", msg, f"Worker:{worker_id}")
            send_json_line(wconn, msg)
        except OSError as e:
            m2m_log.warning("[MASTER] Falha ao enviar command_redirect a Worker:%s — %s", worker_id, e)
    else:
        m2m_log.warning("[MASTER] command_redirect: sem conexão ativa para Worker:%s", worker_id)


# ---------------------------------------------------------------------------
# Sprint 03: Empréstimo — solicita ajuda a Masters vizinhos
# ---------------------------------------------------------------------------
def request_help_from_neighbors(workers_needed: int) -> None:
    """Percorre NEIGHBOR_MASTERS e envia request_help até obter resposta positiva.

    Estratégia: tenta cada vizinho em ordem; para no primeiro que aceitar.
    Em caso de timeout ou falha de rede, loga e tenta o próximo vizinho.
    """
    for neighbor in NEIGHBOR_MASTERS:
        mid  = neighbor["master_id"]
        addr = neighbor["address"]
        rid  = str(uuid.uuid4())
        # Monta mensagem request_help com informações de carga atual
        msg  = make_m2m_message(
            M2M_REQUEST_HELP,
            {
                "MASTER_ID": SERVER_UUID,          # quem está pedindo ajuda
                "CURRENT_LOAD": _get_queue_size(), # tamanho atual da fila
                "CAPACITY": SATURATION_THRESHOLD,  # limite que foi atingido
                "WORKERS_NEEDED": workers_needed,  # quantos Workers são necessários
            },
            request_id=rid,
        )
        try:
            conn = _get_m2m_conn(mid, addr)
            _log_m2m(f"Master:{SERVER_UUID} →", msg, f"Master:{mid}")
            send_json_line(conn, msg)
            reply = recv_json_line(conn, timeout=M2M_TIMEOUT_SEC)
            _log_m2m(f"Master:{mid} →", reply, f"Master:{SERVER_UUID}")

            if reply.get("type") == M2M_RESPONSE_ACCEPTED:
                # Vizinho aceitou — lista de Workers que serão redirecionados para cá
                granted = reply.get("payload", {}).get("WORKER_DETAILS", [])
                m2m_log.info(
                    "[MASTER] request_help aceito por %s — %d workers concedidos rid=%s",
                    mid, len(granted), rid,
                )
                return  # sucesso, para de tentar vizinhos
            elif reply.get("type") == M2M_RESPONSE_REJECTED:
                reason = reply.get("payload", {}).get("REASON", "?")
                m2m_log.info("[MASTER] request_help rejeitado por %s reason=%s", mid, reason)
                # Tenta próximo vizinho

        except socket.timeout:
            # CT07 — timeout logado, tenta próximo vizinho
            m2m_log.warning(
                "[MASTER] Timeout (5s) aguardando Master:%s request_id=%s — tentando próximo vizinho",
                mid, rid,
            )
            _close_m2m_conn(mid)
        except OSError as e:
            # CT08 — Master B caiu durante empréstimo; continua com workers locais
            m2m_log.warning("[MASTER] Falha de conexão com Master:%s — %s. Continuando com workers locais.", mid, e)
            _close_m2m_conn(mid)


# ---------------------------------------------------------------------------
# Sprint 03: Devolução de Worker emprestado
# ---------------------------------------------------------------------------
def release_borrowed_worker(worker_id: str) -> None:
    """Envia command_release ao Worker e notify_worker_returned ao Master original.

    Sequenìia de devolução:
      1. Envia command_release ao Worker via conexão ativa
      2. Notifica o Master de origem que o Worker está voltando
      3. Remove o Worker do registro de emprestados e loga o ciclo de vida
    """
    with borrowed_lock:
        info = borrowed_workers.get(worker_id)
    if info is None:
        return  # Worker já foi devolvido ou não está registrado

    orig_addr = info.get("ORIGINAL_MASTER_ADDRESS", "")
    orig_mid  = info.get("ORIGINAL_MASTER_ID", "")

    # 1. Envia command_release ao Worker com endereço do Master original
    release_msg = make_m2m_message(M2M_COMMAND_RELEASE, {"ORIGINAL_MASTER_ADDRESS": orig_addr})
    with worker_conn_lock:
        wconn = worker_connections.get(worker_id)
    if wconn:
        try:
            _log_m2m("→", release_msg, f"Worker:{worker_id}")
            send_json_line(wconn, release_msg)
        except OSError as e:
            m2m_log.warning("[MASTER] Falha ao enviar command_release a Worker:%s — %s", worker_id, e)

    # 2. Notifica o Master original que o Worker está a caminho de volta
    if orig_addr:
        notify_msg = make_m2m_message(M2M_NOTIFY_RETURNED, {"WORKER_ID": worker_id})
        try:
            conn = _get_m2m_conn(orig_mid, orig_addr)
            _log_m2m("→", notify_msg, f"Master:{orig_mid}")
            send_json_line(conn, notify_msg)
        except OSError as e:
            m2m_log.warning("[MASTER] Falha ao notificar Master:%s — %s", orig_mid, e)
            _close_m2m_conn(orig_mid)

    # 3. Remove do registro e loga ciclo de vida completo do Worker emprestado
    with borrowed_lock:
        removed = borrowed_workers.pop(worker_id, None)
    if removed:
        m2m_log.info(
            "[MASTER] Ciclo de vida Worker emprestado concluído — worker_id=%s borrowed_at=%s returned_at=%s orig_master=%s",
            worker_id,
            removed.get("BORROWED_AT", "?"),
            datetime.now(timezone.utc).isoformat(),
            orig_mid,
        )
    _log_worker_counts()


# ---------------------------------------------------------------------------
# Sprint 03: Handler de mensagens M2M recebidas de outros Masters
# ---------------------------------------------------------------------------
def handle_m2m_message(msg: dict, conn: socket.socket, peer_addr: str) -> None:
    """Processa mensagem M2M recebida de outro Master. Nunca lança exceção não tratada.

    Roteamento por tipo de mensagem:
    - request_help:            avalia carga e aceita/rejeita pedido de Workers
    - register_temporary_worker: registra Worker emprestado que chegou
    - notify_worker_returned:  confirma devolução de Worker ao Master original
    - demais tipos:            logados sem ação local
    """
    # Valida estrutura básica do envelope M2M antes de processar
    try:
        validate_m2m_message(msg)
    except ValueError as e:
        m2m_log.error("[MASTER] Mensagem M2M inválida de %s: %s — ignorando", peer_addr, e)
        return

    msg_type = msg.get("type", "")
    rid      = msg.get("request_id", "?")
    payload  = msg.get("payload", {})

    _log_m2m(f"Master:{peer_addr} →", msg, f"Master:{SERVER_UUID}")

    # CT09 — type desconhecido: loga e ignora sem fechar a conexão
    if msg_type not in M2M_KNOWN_TYPES:
        m2m_log.warning(
            "[MASTER] type='%s' desconhecido de %s request_id=%s — ignorando",
            msg_type, peer_addr, rid,
        )
        return

    # ---- request_help: outro Master está sobrecarregado e pede Workers ----
    if msg_type == M2M_REQUEST_HELP:
        workers_needed = payload.get("WORKERS_NEEDED", 1)
        idle = _get_idle_workers()  # Workers locais sem tarefas pendentes

        if not idle:
            # CT02: sem Workers ociosos → rejeita o pedido de ajuda
            reply = make_m2m_message(
                M2M_RESPONSE_REJECTED,
                {"REASON": "high_load"},
                request_id=rid,
            )
            _log_m2m(f"Master:{SERVER_UUID} →", reply, f"Master:{peer_addr}")
            send_json_line(conn, reply)
            return

        # CT01: tem Workers ociosos → aceita e seleciona os necessários
        selected = idle[:workers_needed]
        reply = make_m2m_message(
            M2M_RESPONSE_ACCEPTED,
            {
                "WORKERS_OFFERED": len(selected),
                "WORKER_DETAILS": [
                    {"ID": wid, "ADDRESS": f"{HOST}:{PORT}"}
                    for wid in selected
                ],
            },
            request_id=rid,
        )
        _log_m2m(f"Master:{SERVER_UUID} →", reply, f"Master:{peer_addr}")
        send_json_line(conn, reply)

        # Determina o endereço correto do Master solicitante para o redirecionamento
        req_master_id = payload.get("MASTER_ID", "")
        target_address = ""
        for neighbor in NEIGHBOR_MASTERS:
            if neighbor["master_id"] == req_master_id:
                target_address = neighbor["address"]
                break
        if not target_address:
            # Fallback: usa o IP do peer com porta padrão 5000
            peer_ip = peer_addr.split(":")[0] if ":" in peer_addr else peer_addr
            target_address = f"{peer_ip}:8000"

        # Envia command_redirect a cada Worker selecionado para que se reconecte ao Master A
        for wid in selected:
            _send_redirect_to_worker(wid, target_address)

    # ---- register_temporary_worker: Worker emprestado chegou e se identifica ----
    elif msg_type == M2M_REGISTER_TEMP_WORKER:
        worker_id    = payload.get("WORKER_ID", "")
        orig_mid     = payload.get("ORIGINAL_MASTER_ID", "")
        orig_addr    = payload.get("ORIGINAL_MASTER_ADDRESS", "")
        if not worker_id:
            m2m_log.error(
                "[MASTER] register_temporary_worker sem WORKER_ID de %s — ignorando", peer_addr
            )
            return
        # Registra o Worker emprestado com metadados para futura devolução
        with borrowed_lock:
            borrowed_workers[worker_id] = {
                "WORKER_ID": worker_id,
                "ORIGINAL_MASTER_ID": orig_mid,
                "ORIGINAL_MASTER_ADDRESS": orig_addr,
                "BORROWED_AT": datetime.now(timezone.utc).isoformat(),
            }
        m2m_log.info(
            "[MASTER] Worker emprestado registrado: worker_id=%s orig_master=%s", worker_id, orig_mid
        )
        _log_worker_counts()

    # ---- notify_worker_returned: Master A nos avisa que devolveu o Worker ----
    elif msg_type == M2M_NOTIFY_RETURNED:
        worker_id = payload.get("WORKER_ID", "")
        m2m_log.info(
            "[MASTER] notify_worker_returned recebido: worker_id=%s de %s", worker_id, peer_addr
        )

    # Os demais tipos (response_accepted/rejected, command_redirect, command_release)
    # chegam no sentido oposto — apenas loga, sem ação local
    else:
        m2m_log.info(
            "[MASTER] type='%s' recebido de %s request_id=%s (sem ação local)", msg_type, peer_addr, rid
        )


# ---------------------------------------------------------------------------
# Sprint 03: Monitor de saturação com histerese
# ---------------------------------------------------------------------------
def _saturation_monitor(check_interval_sec: float = 5.0) -> None:
    """Loop daemon que monitora a fila e dispara empréstimo/devolução automaticamente.

    Histerese de dois limiares evita oscilação rápida entre pedir/devolver:
    - Acima de SATURATION_THRESHOLD: pede ajuda a vizinhos (uma vez)
    - Abaixo de RELEASE_THRESHOLD:   devolve Workers emprestados
    """
    m2m_log.info(
        "[MASTER] Monitor de saturação iniciado (SATURATION=%d RELEASE=%d)",
        SATURATION_THRESHOLD, RELEASE_THRESHOLD,
    )
    _help_requested = False  # evita pedir ajuda múltiplas vezes sem devolver
    while True:
        time.sleep(check_interval_sec)  # verifica a cada 5s por padrão
        q = _get_queue_size()

        # Saturação detectada e ainda não pediu ajuda: solicita Workers a vizinhos
        if not _help_requested and q > SATURATION_THRESHOLD:
            m2m_log.info(
                "[MASTER] Saturação detectada (fila=%d > %d) — solicitando ajuda a vizinhos", q, SATURATION_THRESHOLD
            )
            _help_requested = True
            # Estima quantos Workers extras são necessários proporcionalmente
            workers_needed = max(1, q // max(_get_local_count(), 1))
            threading.Thread(
                target=request_help_from_neighbors,
                args=(workers_needed,),
                daemon=True,
            ).start()

        # Carga normalizada e havia Workers emprestados: inicia devoluções
        elif _help_requested and q < RELEASE_THRESHOLD:
            m2m_log.info(
                "[MASTER] Carga normalizada (fila=%d < %d) — devolvendo Workers emprestados", q, RELEASE_THRESHOLD
            )
            _help_requested = False
            with borrowed_lock:
                to_release = list(borrowed_workers.keys())
            # Devolve cada Worker em thread separada para não bloquear o monitor
            for wid in to_release:
                threading.Thread(
                    target=release_borrowed_worker,
                    args=(wid,),
                    daemon=True,
                ).start()


# ---------------------------------------------------------------------------
# Handler de conexões (Sprint 01/02 preservado + Sprint 03 estendido)
# ---------------------------------------------------------------------------
def handle_client(conn: socket.socket, addr) -> None:
    """Processa todas as mensagens de uma conexão TCP (Worker ou Master vizinho).

    Executa em thread dedicada por conexão. Lê mensagens em loop até fechar.
    Roteia pelo conteúdo do payload:
    - M2M:       delega a handle_m2m_message
    - HEARTBEAT: responde com ALIVE
    - STATUS:    valida e confirma resultado da tarefa (ACK)
    - WORKER:    handshake, atribui tarefa ou responde NO_TASK
    """
    print(f"[MASTER] Conectado com {addr}")
    buffer = ""
    worker_id_in_session: str | None = None  # UUID do Worker nesta sessão (para limpeza)

    try:
        while True:
            data = conn.recv(1024).decode()
            if not data:
                break  # conexão fechada pelo cliente
            buffer += data

            # Processa todas as mensagens completas no buffer (delimitadas por '\n')
            while "\n" in buffer:
                message, buffer = buffer.split("\n", 1)

                try:
                    payload = json.loads(message)
                    print(f"[MASTER] Mensagem recebida: {payload}")

                    # Sprint 03: mensagem M2M de outro Master — delega ao handler M2M
                    if is_m2m_message(payload):
                        peer_addr = f"{addr[0]}:{addr[1]}"
                        handle_m2m_message(payload, conn, peer_addr)
                        continue

                    # Heartbeat: Worker (ou monitor externo) verifica se o servidor está vivo
                    if payload.get("TASK") == "HEARTBEAT":
                        response = {
                            "SERVER_UUID": payload.get("SERVER_UUID", SERVER_UUID),
                            "TASK": "HEARTBEAT",
                            "RESPONSE": "ALIVE",
                        }
                        send_json_line(conn, response)
                        continue

                    # Relatório de status: Worker concluiu uma tarefa e envia o resultado
                    if "STATUS" in payload and "TASK" in payload:
                        try:
                            validate_status_report(payload)
                        except ValueError as e:
                            print(f"[MASTER] Relatório de status inválido: {e}")
                            return

                        wid = payload["WORKER_UUID"]

                        with state_lock:
                            pend = pending_by_worker.get(wid)
                            ok_pending = (
                                pend is not None
                                and pend.get("TASK") == QUERY
                            )
                            if not ok_pending:
                                print(f"[MASTER] STATUS sem pendente válido para {wid}")
                                return
                            user   = pend.get("USER")
                            status = payload["STATUS"]
                            # Remove da fila de pendentes após confirmar o resultado
                            del pending_by_worker[wid]

                        result = payload.get("RESULT")
                        # Sprint 03: marca no log se o resultado veio de Worker emprestado
                        with borrowed_lock:
                            is_borrowed = wid in borrowed_workers
                        tag = " [EMPRESTADO]" if is_borrowed else ""
                        print(
                            f"[MASTER]{tag} Status worker={wid} USER={user} STATUS={status} RESULT={result}"
                        )

                        # Confirma recebimento ao Worker (ACK)
                        send_json_line(conn, {"STATUS": STATUS_ACK, "WORKER_UUID": wid})
                        continue

                    # Handshake Worker: primeira mensagem enviada ao conectar
                    try:
                        validate_worker_handshake(payload)
                    except ValueError as e:
                        print(f"[MASTER] Handshake inválido: {e}")
                        continue

                    wid        = payload["WORKER_UUID"]
                    server_uuid = payload.get("SERVER_UUID")  # presente se Worker emprestado

                    # Sprint 03: registra Worker e guarda conexão ativa para futuros M2M
                    with local_workers_lock:
                        local_workers.add(wid)
                    worker_id_in_session = wid
                    with worker_conn_lock:
                        worker_connections[wid] = conn  # necessário para command_redirect

                    if server_uuid:
                        print(f"[MASTER] Worker {wid} é emprestado do Master {server_uuid}")
                        # CT04 — registra automaticamente como emprestado se ainda não estiver
                        with borrowed_lock:
                            if wid not in borrowed_workers:
                                borrowed_workers[wid] = {
                                    "WORKER_ID": wid,
                                    "ORIGINAL_MASTER_ID": server_uuid,
                                    "ORIGINAL_MASTER_ADDRESS": "",
                                    "BORROWED_AT": datetime.now(timezone.utc).isoformat(),
                                }
                        _log_worker_counts()

                    # Decide a resposta dentro do lock para evitar race condition na fila
                    with state_lock:
                        if not task_queue:
                            # Fila vazia: informa Worker que não há tarefas no momento
                            response = {"TASK": TASK_NO_TASK}
                        else:
                            # Retira a primeira tarefa da fila e marca como pendente
                            item = task_queue.popleft()
                            pending_by_worker[wid] = {
                                "TASK": QUERY,
                                "USER": item["USER"],
                                "A": item["A"],
                                "B": item["B"],
                            }
                            response = {
                                "TASK": QUERY,
                                "USER": item["USER"],
                                "A": item["A"],
                                "B": item["B"],
                            }

                    # Envia tarefa (ou NO_TASK) fora do lock para não bloquear outras threads
                    send_json_line(conn, response)

                except json.JSONDecodeError:
                    print("[MASTER] Erro ao decodificar JSON")

    except Exception as e:
        print(f"[MASTER] Erro: {e}")
    finally:
        # Limpeza ao desconectar: remove Worker dos registros e fecha socket
        if worker_id_in_session:
            with worker_conn_lock:
                worker_connections.pop(worker_id_in_session, None)
            with local_workers_lock:
                local_workers.discard(worker_id_in_session)
        conn.close()
        print(f"[MASTER] Conexão encerrada {addr}")


def _master_heartbeat_sender(interval_sec: float = 10.0) -> None:
    """Envia periodicamente {'TASK': 'HEARTBEAT'} a todos os Workers conectados.

    Remove do registro qualquer conexão que falhar ao enviar para evitar acumular
    sockets mortos.
    """
    while True:
        with worker_conn_lock:
            conns = list(worker_connections.items())
        for wid, conn in conns:
            try:
                send_json_line(conn, {"TASK": "HEARTBEAT", "SERVER_UUID": SERVER_UUID})
            except Exception:
                with worker_conn_lock:
                    worker_connections.pop(wid, None)
        time.sleep(interval_sec)


# ---------------------------------------------------------------------------
# Loop do servidor (Sprint 01/02 preservado)
# ---------------------------------------------------------------------------
def server_loop(host: str, port: int) -> None:
    """Cria o socket TCP do servidor e aceita conexões em loop.

    Cada conexão aceita é tratada em uma thread daemon separada via handle_client,
    permitindo atender múltiplos Workers/Masters simultaneamente.
    SO_REUSEADDR permite reiniciar o servidor rapidamente sem erro "Address in use".
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Permite reutilizar o endereço imediatamente após encerrar o servidor
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen()  # backlog padrão do SO
    bound_host, bound_port = server.getsockname()[:2]
    print(f"[MASTER] Servidor escutando em {bound_host}:{bound_port}")

    try:
        while True:
            # Bloqueia até chegar uma nova conexão
            conn, addr = server.accept()
            # Cria thread daemon para tratar esta conexão sem bloquear o loop principal
            client_thread = threading.Thread(
                target=handle_client, args=(conn, addr), daemon=True
            )
            client_thread.start()
    finally:
        server.close()  # fecha o socket servidor ao sair (ex.: Ctrl+C)


def start_server() -> None:
    """Ponto de entrada do servidor: inicializa fila, monitor e loop TCP."""
    # Guarda de histerese (Req 35): garante que o limiar de liberação seja sempre
    # menor que o de saturação. Se estiverem invertidos, o monitor ficaria pedindo
    # e devolvendo Workers indefinidamente (efeito ping-pong). Falhar cedo com
    # mensagem clara é melhor do que um comportamento incorreto silencioso em produção.
    if RELEASE_THRESHOLD >= SATURATION_THRESHOLD:
        raise ValueError(
            f"Configuração inválida: P2P_RELEASE_THRESHOLD ({RELEASE_THRESHOLD}) "
            f"deve ser MENOR que P2P_SATURATION_THRESHOLD ({SATURATION_THRESHOLD}). "
            f"Corrija as variáveis de ambiente para evitar efeito ping-pong."
        )

    # Popula a fila ANTES de iniciar o servidor para evitar race condition
    # onde um Worker conecta antes das tarefas estarem disponíveis
    seed_queue()
    # Sprint 03: inicia monitor de saturação em thread daemon
    threading.Thread(target=_saturation_monitor, daemon=True).start()
    # Sprint 03: inicia sender proativo de heartbeats a Workers conectados
    threading.Thread(target=_master_heartbeat_sender, args=(10.0,), daemon=True).start()
    # Inicia o loop do servidor (bloqueia até encerramento)
    server_loop(HOST, PORT)


if __name__ == "__main__":
    start_server()