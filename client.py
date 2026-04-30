import json
import os
import socket
import threading
import time
import uuid
from protocol import *
import schedule



HOST = os.environ.get("P2P_HOST", "10.62.217.42")
PORT = int(os.environ.get("P2P_PORT", "5000"))
WORKER_UUID = os.environ.get("P2P_WORKER_UUID", str(uuid.uuid4()))
# UUID do Master de origem quando o worker está emprestado a outro Master
ORIGIN_MASTER_UUID = os.environ.get("P2P_ORIGIN_MASTER_UUID", "").strip()
# Identificador do Master no payload HEARTBEAT
HEARTBEAT_SERVER_UUID = os.environ.get(
    "P2P_HEARTBEAT_SERVER_UUID",
    os.environ.get("P2P_SERVER_UUID", "MASTER_1"),
)   

#Intervalos
# Timeout para receber uma linha JSON do socket
READ_TIMEOUT_SEC = 5.0
# Tempo de espera para uma tarefa não encontrada
NO_TASK_SLEEP_SEC = 30
# Intervalo para enviar heartbeat
HEARTBEAT_INTERVAL_SEC = int(os.environ.get("P2P_HEARTBEAT_INTERVAL_SEC", "30"))

# Função para receber uma linha JSON do socket
def recv_json_line(sock: socket.socket) -> dict:
    sock.settimeout(READ_TIMEOUT_SEC)
    buffer = b""
    while b"\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("conexão fechada antes de linha completa")
        buffer += chunk
    line, _, _ = buffer.partition(b"\n")
    return json.loads(line.decode())

# Função para enviar heartbeat
def send_heartbeat() -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.connect((HOST, PORT))
            #payload
            payload = {
                "SERVER_UUID": HEARTBEAT_SERVER_UUID,
                "TASK": "HEARTBEAT",
            }
            client.sendall((json.dumps(payload) + "\n").encode())
            reply = recv_json_line(client)
            print(f"[WORKER] Resposta recebida: {reply}")
    except Exception as e:
        print(f"[WORKER] Erro de conexão: {e}")

# Função para enviar heartbeat periodicamente
def _heartbeat_schedule_loop() -> None:
    print("[WORKER] Iniciando envio de heartbeat...")
    send_heartbeat()
    schedule.every(HEARTBEAT_INTERVAL_SEC).seconds.do(send_heartbeat)
    while True:
        schedule.run_pending()
        time.sleep(1)


def run_worker_loop() -> None:
    while True:
        # Abre UMA conexão por ciclo completo (handshake + tarefa + relatório de status)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((HOST, PORT))

            # Solicita uma tarefa ao Master
            handshake = {"WORKER": WORKER_ALIVE, "WORKER_UUID": WORKER_UUID}
            # Se o worker está emprestado a outro Master, inclui o SERVER_UUID no handshake
            if ORIGIN_MASTER_UUID:
                handshake["SERVER_UUID"] = ORIGIN_MASTER_UUID
            sock.sendall((json.dumps(handshake) + "\n").encode())
            reply = recv_json_line(sock)

            if reply.get("TASK") == TASK_NO_TASK:
                # Sem tarefa disponível, aguarda antes de tentar novamente
                time.sleep(NO_TASK_SLEEP_SEC)
                continue

            if not (reply.get("TASK") == QUERY and "USER" in reply):
                raise ValueError(f"resposta inesperada do master: {reply}")

            # Extrai os valores de A e B da tarefa
            user, a, b = reply["USER"], reply.get("A"), reply.get("B")

            # Calcula o resultado da tarefa
            result = a + b
            # Loga o resultado da tarefa
            print(f"[WORKER] Calculando {a} + {b} = {result}")

            # — Relatório de status: reutiliza o mesmo socket, sem fechar a conexão —
            body = {
                "STATUS": STATUS_OK,
                "TASK": QUERY,
                "WORKER_UUID": WORKER_UUID,
                "RESULT": result,
            }
            sock.sendall((json.dumps(body) + "\n").encode())
            ack = recv_json_line(sock)
            if (
                ack.get("STATUS") != STATUS_ACK
                or ack.get("WORKER_UUID") != WORKER_UUID
            ):
                raise ValueError(f"ACK inválido: {ack}")
            print(
                f"[WORKER] ACK recebido — ciclo concluído para WORKER_UUID={WORKER_UUID}"
            )

        except (
            socket.timeout,
            OSError,
            ValueError,
            json.JSONDecodeError,
            ConnectionError,
        ) as e:
            print(f"[WORKER] erro: {e}; a tentar de novo...")
            time.sleep(1)
        finally:
            sock.close()


def main() -> None:
    # Inicia o loop do worker
    print(f"[WORKER] UUID={WORKER_UUID} a ligar a {HOST}:{PORT}")
    if ORIGIN_MASTER_UUID:
        print(
            f"[WORKER] Modo emprestado: handshake incluirá SERVER_UUID={ORIGIN_MASTER_UUID} (Master de origem)"
        )
    hb = os.environ.get("P2P_ENABLE_HEARTBEAT", "").strip().lower()
    if hb in ("1", "true", "yes", "on"):
        threading.Thread(target=_heartbeat_schedule_loop, daemon=True).start()
    # Ciclo de tarefas
    run_worker_loop()


if __name__ == "__main__":
    main()