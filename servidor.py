import json
import os
import socket
import threading
from collections import deque
from protocol import *

# UUID do servidor
SERVER_UUID = os.environ.get("P2P_SERVER_UUID", "MASTER_1")

# Endereço e porta do servidor
HOST = os.environ.get("P2P_HOST", "10.62.217.42")
PORT = int(os.environ.get("P2P_PORT", "5000"))

# Fila de tarefas
task_queue: deque = deque()
# Pendentes por worker
pending_by_worker: dict[str, dict] = {}
# Lock para acesso à fila e pendentes
state_lock = threading.Lock()


# FIX 1: seed_queue agora é chamada ANTES de server_loop
tasks = [
    # User 1: Small values
    {"USER": "user1", "A": 1, "B": 5}, {"USER": "user1", "A": 3, "B": 7},
    {"USER": "user1", "A": 10, "B": 2}, {"USER": "user1", "A": 4, "B": 4},
    {"USER": "user1", "A": 9, "B": 1}, {"USER": "user1", "A": 6, "B": 8},
    
    # User 2: Medium values
    {"USER": "user2", "A": 15, "B": 20}, {"USER": "user2", "A": 12, "B": 18},
    {"USER": "user2", "A": 25, "B": 5}, {"USER": "user2", "A": 30, "B": 10},
    {"USER": "user2", "A": 11, "B": 11}, {"USER": "user2", "A": 14, "B": 22},
    
    # User 3: Large values
    {"USER": "user3", "A": 100, "B": 50}, {"USER": "user3", "A": 250, "B": 150},
    {"USER": "user3", "A": 500, "B": 500}, {"USER": "user3", "A": 120, "B": 80},
    {"USER": "user3", "A": 99, "B": 1}, {"USER": "user3", "A": 333, "B": 666},
    
    # User 4: Zeroes and Primes
    {"USER": "user4", "A": 0, "B": 10}, {"USER": "user4", "A": 7, "B": 13},
    {"USER": "user4", "A": 17, "B": 19}, {"USER": "user4", "A": 23, "B": 29},
    {"USER": "user4", "A": 31, "B": 0}, {"USER": "user4", "A": 2, "B": 3},
    
    # User 5: Mixed scale
    {"USER": "user5", "A": 1000, "B": 1}, {"USER": "user5", "A": 5, "B": 5000},
    {"USER": "user5", "A": 42, "B": 42}, {"USER": "user5", "A": 8, "B": 16},
    {"USER": "user5", "A": 64, "B": 32}, {"USER": "user5", "A": 123, "B": 456}
]

def seed_queue() -> None:
    with state_lock:
        task_queue.extend(tasks)


def send_json_line(conn: socket.socket, obj: dict) -> None:
    conn.sendall((json.dumps(obj) + "\n").encode())


def handle_client(conn: socket.socket, addr) -> None:
    print(f"[MASTER] Conectado com {addr}")
    buffer = ""

    try:
        while True:
            data = conn.recv(1024).decode()
            if not data:
                break
            buffer += data

            while "\n" in buffer:
                message, buffer = buffer.split("\n", 1)

                try:
                    payload = json.loads(message)
                    print(f"[MASTER] Mensagem recebida: {payload}")

                    # Heartbeat
                    if payload.get("TASK") == "HEARTBEAT":
                        response = {
                            "SERVER_UUID": payload.get("SERVER_UUID", SERVER_UUID),
                            "TASK": "HEARTBEAT",
                            "RESPONSE": "ALIVE",
                        }
                        send_json_line(conn, response)
                        continue

                    # Relatório de status
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
                            user = pend.get("USER")
                            status = payload["STATUS"]
                            del pending_by_worker[wid]

                        result = payload.get("RESULT")
                        print(f"[MASTER] Status worker={wid} USER={user} STATUS={status} RESULT={result}")

                        send_json_line(conn, {"STATUS": STATUS_ACK, "WORKER_UUID": wid})
                        continue

                    # Handshake
                    try:
                        validate_worker_handshake(payload)
                    except ValueError as e:
                        print(f"[MASTER] Handshake inválido: {e}")
                        continue

                    wid = payload["WORKER_UUID"]
                    server_uuid = payload.get("SERVER_UUID")

                    if server_uuid:
                        print(f"[MASTER] Worker {wid} é emprestado do Master {server_uuid}")

                    # FIX 2: decide dentro do lock, envia FORA do lock
                    with state_lock:
                        if not task_queue:
                            response = {"TASK": TASK_NO_TASK}
                        else:
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

                    # I/O de rede fora do lock
                    send_json_line(conn, response)

                except json.JSONDecodeError:
                    print("[MASTER] Erro ao decodificar JSON")

    except Exception as e:
        print(f"[MASTER] Erro: {e}")
    finally:
        conn.close()
        print(f"[MASTER] Conexão encerrada {addr}")


def server_loop(host: str, port: int) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen()
    bound_host, bound_port = server.getsockname()[:2]
    print(f"[MASTER] Servidor escutando em {bound_host}:{bound_port}")

    try:
        while True:
            conn, addr = server.accept()
            client_thread = threading.Thread(
                target=handle_client, args=(conn, addr), daemon=True
            )
            client_thread.start()
    finally:
        server.close()


def start_server() -> None:
    # FIX 1: seed_queue ANTES de server_loop
    seed_queue()
    server_loop(HOST, PORT)


if __name__ == "__main__":
    start_server()