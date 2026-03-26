import socket
import json
import schedule
import time

HOST = '10.62.217.42'
PORT = 5000

SERVER_UUID = "MASTER_1"


def send_heartbeat():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.connect((HOST, PORT))

            payload = {
                "SERVER_UUID": SERVER_UUID,
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


def heartbeat():
    print("[WORKER] Iniciando envio de heartbeat...")
    # Executa imediatamente a primeira vez
    send_heartbeat()

    # Agenda o heartbeat a cada 30 segundos
    schedule.every(30).seconds.do(send_heartbeat)

    while True:
        schedule.run_pending()
        time.sleep(1)
def main():
    heartbeat()


if __name__ == "__main__":
    main()