import socket
import json
import schedule
import time

HOST = '192.168.1.7'
PORT = 5000

WORKER_UUID = "WORKER-CC"
SERVER_UUID = "MASTER"


def send_heartbeat():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.connect((HOST, PORT))

            payload = {
                "SERVER_UUID": SERVER_UUID,
                "WORKER_UUID": WORKER_UUID,
                "TASK": "HEARTBEAT"
            }

            client.sendall((json.dumps(payload) + "\n").encode())

            buffer = ""
            while True:
                data = client.recv(1024).decode()
                if not data:
                    break

                buffer += data

                if "\n" in buffer:
                    message, buffer = buffer.split("\n", 1)

                    response = json.loads(message)
                    print(f"[WORKER] Resposta recebida: {response}")
                    break

    except Exception as e:
        print(f"[WORKER] Erro de conexão: {e}")


def main():
    # Agenda o heartbeat a cada 5 segundos
    schedule.every(5).seconds.do(send_heartbeat)

    print("[WORKER] Iniciando envio de heartbeat...")

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()