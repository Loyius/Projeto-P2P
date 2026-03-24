import socket
import threading
import json

HOST = '192.168.1.7'
PORT = 5000
SERVER_UUID = "MASTER"


def handle_client(conn, addr):
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

                    # Verifica se é HEARTBEAT
                    if payload.get("TASK") == "HEARTBEAT":
                        response = {
                            "SERVER_UUID": payload.get("SERVER_UUID", SERVER_UUID),
                            "TASK": "HEARTBEAT",
                            "RESPONSE": "ALIVE"
                        }

                        conn.sendall((json.dumps(response) + "\n").encode())

                except json.JSONDecodeError:
                    print("[MASTER] Erro ao decodificar JSON")

    except Exception as e:
        print(f"[MASTER] Erro: {e}")

    finally:
        conn.close()
        print(f"[MASTER] Conexão encerrada {addr}")


def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()

    print(f"[MASTER] Servidor escutando em {HOST}:{PORT}")

    while True:
        conn, addr = server.accept()

        # Thread para cada conexão (concorrência)
        client_thread = threading.Thread(target=handle_client, args=(conn, addr))
        client_thread.start()


if __name__ == "__main__":
    start_server()