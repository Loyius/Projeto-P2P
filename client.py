import json
import os
import socket
import time
import uuid

from protocol import (
    WORKER_ALIVE,
    QUERY,
    TASK_NO_TASK,
    STATUS_OK,
    STATUS_NOK,
    STATUS_ACK,
)

HOST = os.environ.get("P2P_HOST", "127.0.0.1")
PORT = int(os.environ.get("P2P_PORT", "5000"))
WORKER_UUID = os.environ.get("P2P_WORKER_UUID", str(uuid.uuid4()))
# UUID do Master de origem quando o worker está emprestado a outro Master (payload opcional SERVER_UUID).
ORIGIN_MASTER_UUID = os.environ.get("P2P_ORIGIN_MASTER_UUID", "").strip()
READ_TIMEOUT_SEC = 5.0
NO_TASK_SLEEP_SEC = 30

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

# Função para solicitar uma tarefa
def request_task() -> tuple[str, int | float, int | float] | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((HOST, PORT))
        handshake = {"WORKER": WORKER_ALIVE, "WORKER_UUID": WORKER_UUID}
        # Se o worker está emprestado a outro Master, inclui o SERVER_UUID no handshake
        if ORIGIN_MASTER_UUID:
            handshake["SERVER_UUID"] = ORIGIN_MASTER_UUID
        sock.sendall((json.dumps(handshake) + "\n").encode())
        reply = recv_json_line(sock)
        if reply.get("TASK") == TASK_NO_TASK:
            time.sleep(NO_TASK_SLEEP_SEC)
            return None
        if reply.get("TASK") == QUERY and "USER" in reply:
            return reply["USER"], reply.get("A"), reply.get("B")
        raise ValueError(f"resposta inesperada do master: {reply}")
    finally:
        sock.close()

#Relatório de status 
def report_status(user: str, ok: bool, result=None) -> None:
    _ = user 
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((HOST, PORT))
        # Envia o payload de "STATUS" para o master
        #payload de "STATUS"
        body = {
            "STATUS": STATUS_OK if ok else STATUS_NOK,
            "TASK": QUERY,
            "WORKER_UUID": WORKER_UUID,
            "RESULT": result,
        }
        sock.sendall((json.dumps(body) + "\n").encode())
        reply = recv_json_line(sock)
        if (
            reply.get("STATUS") != STATUS_ACK
            or reply.get("WORKER_UUID") != WORKER_UUID
        ):
            raise ValueError(f"ACK inválido: {reply}")
        print(
            f"[WORKER] ACK recebido — ciclo concluído para WORKER_UUID={WORKER_UUID}"
        )
        # socket fechado pelo bloco finally logo abaixo
    finally:
        sock.close()


def run_worker_loop() -> None:
    while True:
        try:
            # Solicita uma tarefa
            task = request_task()
            if task is None:
                continue
            # Extrai os valores de A e B da tarefa
            user, a, b = task
            # Calcula o resultado da tarefa
            result = a + b
            # Loga o resultado da tarefa
            print(f"[WORKER] Calculando {a} + {b} = {result}")
            # Relatório de status
            report_status(user, ok=True, result=result)
            # Fechar conexão
        except (
            socket.timeout,
            OSError,
            ValueError,
            json.JSONDecodeError,
            ConnectionError,
        ) as e:
            print(f"[WORKER] erro: {e}; a tentar de novo...")
            time.sleep(1)


def main() -> None:
    # Inicia o loop do worker
    # Loga o UUID do worker e o endereço do servidor
    print(f"[WORKER] UUID={WORKER_UUID} a ligar a {HOST}:{PORT}")
    if ORIGIN_MASTER_UUID:
        print(
            f"[WORKER] Modo emprestado: handshake incluirá SERVER_UUID={ORIGIN_MASTER_UUID} (Master de origem)"
        )
    # Executa o loop do worker
    run_worker_loop()


if __name__ == "__main__":
    main()
