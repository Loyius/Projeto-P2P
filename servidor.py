import json
import os
import socket
import threading
from collections import deque
from protocol import *

# UUID do servidor
SERVER_UUID = "MASTER_1"

# Endereço e porta do servidor
HOST = os.environ.get("P2P_HOST", "127.0.0.1")

PORT = int(os.environ.get("P2P_PORT", "5000"))

# Fila de tarefas
task_queue: deque = deque()
# Pendentes por worker
pending_by_worker: dict[str, dict] = {}
# Lock para acesso à fila e pendentes
state_lock = threading.Lock()


def seed_queue() -> None:
    with state_lock:
        # Inicializa a fila com uma tarefa de teste com definição dos valores de A e B
        task_queue.append({"USER": "demo-user", "A": 2, "B": 2})

# Função para enviar uma linha JSON para o cliente
def send_json_line(conn: socket.socket, obj: dict) -> None:
    conn.sendall((json.dumps(obj) + "\n").encode())

# Função para lidar com uma conexão cliente
def handle_client(conn: socket.socket, addr) -> None:

    # Loga o endereço do cliente
    print(f"[MASTER] Conectado com {addr}")
    # Buffer para armazenar os dados recebidos
    buffer = ""

    # Loop para lidar com a conexão cliente
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
                        
                    # Status report
                    if "STATUS" in payload and "TASK" in payload:
                        try:
                            # Validação do status report
                            validate_status_report(payload)
                        except ValueError as e:
                            print(f"[MASTER] Relatório de status inválido: {e}")
                            return
                        # UUID do worker
                        wid = payload["WORKER_UUID"]
                        # Lock para acesso à fila e pendentes
                        with state_lock:
                            # Verifica se o worker tem uma tarefa pendente ou se está emprestado
                            pend = pending_by_worker.get(wid)
                            ok_pending = (
                                pend is not None
                                and pend.get("TASK") == QUERY
                            )
                            if not ok_pending:
                                print(
                                    f"[MASTER] STATUS sem pendente válido para {wid}"
                                )
                                return
                            user = pend.get("USER")
                            status = payload["STATUS"]
                            del pending_by_worker[wid]

                        result = payload.get("RESULT")
                        print(
                            f"[MASTER] Status worker={wid} USER={user} STATUS={status} RESULT={result}"
                        )
                        send_json_line(
                            conn,
                            {"STATUS": STATUS_ACK, "WORKER_UUID": wid},
                        )
                        return  # fecha a conexão após enviar o ACK

                    try:
                        # Validação do handshake
                        validate_worker_handshake(payload)
                    except ValueError as e:
                        print(f"[MASTER] Handshake inválido: {e}")
                        continue

                    wid = payload["WORKER_UUID"]
                    server_uuid = payload.get("SERVER_UUID")

                    # Master verifica se worker foi emprestado por outro Master
                    if server_uuid:
                        print(
                            f"[MASTER] Worker {wid} é emprestado do Master {server_uuid}"
                        )
                    # Master verifica a fila de tarefas
                    with state_lock:
                        # Se a fila estiver vazia, envia um payload de "NO_TASK"
                        if not task_queue:
                            send_json_line(conn, {"TASK": TASK_NO_TASK})
                        
                        # Se a fila não estiver vazia, envia um payload de "QUERY"
                        else:
                            # Remove a primeira tarefa da fila
                            item = task_queue.popleft()
                            # Registra a tarefa pendente para o worker
                            pending_by_worker[wid] = {
                                "TASK": QUERY,
                                "USER": item["USER"],
                                "A": item["A"],
                                "B": item["B"],
                            }
                            send_json_line(
                                conn,
                                {
                                    "TASK": QUERY,
                                    "USER": item["USER"],
                                    "A": item["A"],
                                    "B": item["B"],
                                },
                            )

                except json.JSONDecodeError:
                    print("[MASTER] Erro ao decodificar JSON")

    except Exception as e:
        print(f"[MASTER] Erro: {e}")

    finally:
        conn.close()
        print(f"[MASTER] Conexão encerrada {addr}")

# Servidor em loop
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

# Função para iniciar o servidor
def start_server() -> None:
    # Inicializa a fila com uma tarefa
    seed_queue()
    # Inicia o servidor
    server_loop(HOST, PORT)


if __name__ == "__main__":
    start_server()
