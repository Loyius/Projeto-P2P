"""Worker P2P — cliente que se conecta ao Master, solicita tarefas e devolve resultados.

Fluxo geral:
  1. Conecta-se ao Master via TCP
  2. Envia handshake (WORKER=ALIVE + WORKER_UUID)
  3. Recebe uma tarefa (QUERY com A e B) ou NO_TASK
  4. Calcula A + B e devolve o resultado
  5. Aguarda ACK do Master e repete o ciclo

Sprint 03 adiciona suporte a:
  - Redirecionamento para outro Master (command_redirect)
  - Devolução ao Master original (command_release)
  - Heartbeat periódico opcional
"""
import json
import os
import socket
import threading
import time
import uuid
from protocol import *
import schedule

# ---------------------------------------------------------------------------
# Configuração via variáveis de ambiente (facilita deploy sem alterar código)
# ---------------------------------------------------------------------------

# Endereço IP do Master ao qual o Worker deve se conectar inicialmente
HOST        = os.environ.get("P2P_HOST", "192.168.100.87")

# Porta TCP do Master
PORT        = int(os.environ.get("P2P_PORT", "8000"))

# Identificador único deste Worker — gerado aleatoriamente se não fornecido
WORKER_UUID = os.environ.get("P2P_WORKER_UUID", str(uuid.uuid4()))

# UUID do Master de origem quando o worker está emprestado a outro Master
# Se preenchido, indica que este Worker foi redirecionado e deve voltar ao original
ORIGIN_MASTER_UUID = os.environ.get("P2P_ORIGIN_MASTER_UUID", "").strip()

# UUID do Master que este Worker inclui nos heartbeats
# Permite ao servidor identificar a qual Master cluster o Worker pertence
HEARTBEAT_SERVER_UUID = os.environ.get(
    "P2P_HEARTBEAT_SERVER_UUID",
    os.environ.get("P2P_SERVER_UUID", "MASTER_1"),
)

# ---------------------------------------------------------------------------
# Intervalos de tempo configuráveis
# ---------------------------------------------------------------------------

# Timeout de leitura em segundos ao aguardar resposta do Master
READ_TIMEOUT_SEC       = 5.0

# Tempo de espera (segundos) quando o Master responde NO_TASK (sem tarefas disponíveis)
NO_TASK_SLEEP_SEC      = int(os.environ.get("P2P_NO_TASK_SLEEP_SEC", "30"))

# Intervalo em segundos entre envios de heartbeat ao servidor
HEARTBEAT_INTERVAL_SEC = int(os.environ.get("P2P_HEARTBEAT_INTERVAL_SEC", "30"))


def recv_json_line(sock: socket.socket, timeout: float = READ_TIMEOUT_SEC) -> dict:
    """Lê uma linha JSON completa do socket e devolve como dicionário.

    Aguarda até receber o caractere de nova linha '\\n' que delimita a mensagem.
    Aplica timeout para evitar bloqueio indefinido caso o Master não responda.

    Args:
        sock:    socket TCP conectado ao Master
        timeout: tempo máximo de espera em segundos

    Returns:
        Dicionário com o conteúdo da mensagem JSON recebida

    Raises:
        ConnectionError: se o socket fechar antes de uma linha completa chegar
        socket.timeout:  se o timeout for atingido sem dados suficientes
    """
    sock.settimeout(timeout)
    buffer = b""
    # Continua recebendo dados até encontrar o delimitador de linha
    while b"\n" not in buffer:
        data = sock.recv(4096)
        if not data:
            raise ConnectionError("conexão fechada antes de linha completa")
        buffer += data
    # Extrai apenas a primeira linha (ignora dados extras após '\n')
    line, _, _ = buffer.partition(b"\n")
    return json.loads(line.decode())


def send_heartbeat() -> None:
    """Envia um heartbeat ao Master para confirmar que este Worker está ativo.

    Abre uma nova conexão TCP, envia o payload HEARTBEAT com o UUID do servidor
    e aguarda a resposta. Em caso de erro de rede, loga e encerra silenciosamente.
    Este comportamento é intencional: heartbeats são "best effort".
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.connect((HOST, PORT))

            # Monta o payload do heartbeat com identificação do servidor/cluster
            payload = {
                "SERVER_UUID": HEARTBEAT_SERVER_UUID,
                "TASK": "HEARTBEAT",
            }

            # Envia o heartbeat com delimitador de linha para o protocolo de framing
            client.sendall((json.dumps(payload) + "\n").encode())

            # Aguarda confirmação do servidor (ALIVE)
            reply = recv_json_line(client)

            print(f"[WORKER] Resposta recebida: {reply}")
    except Exception as e:
        # Falha de heartbeat não interrompe o ciclo de trabalho do Worker
        print(f"[WORKER] Erro de conexão: {e}")


def _heartbeat_schedule_loop() -> None:
    """Loop daemon que agenda e executa heartbeats em intervalos regulares.

    Executa em thread separada (daemon=True) para não bloquear o ciclo principal.
    Envia um heartbeat imediatamente ao iniciar e depois a cada HEARTBEAT_INTERVAL_SEC.
    Usa a biblioteca 'schedule' para agendamento sem precisar de sleeps manuais complexos.
    """
    print("[WORKER] Iniciando envio de heartbeat...")
    # Heartbeat imediato ao iniciar (não espera o primeiro intervalo)
    send_heartbeat()
    # Agenda heartbeats periódicos a cada N segundos
    schedule.every(HEARTBEAT_INTERVAL_SEC).seconds.do(send_heartbeat)
    while True:
        # Verifica e executa tarefas agendadas pendentes
        schedule.run_pending()
        time.sleep(1)


# ---------------------------------------------------------------------------
# Sprint 03: Estado dinâmico do Worker — pode mudar durante execução
# ---------------------------------------------------------------------------

# Endereço do Master atual — atualizado quando o Worker recebe command_redirect
_current_host = HOST
_current_port = PORT

# UUID e endereço do Master de origem — preenchidos ao receber command_redirect
# Guardados para permitir a devolução ao Master original via command_release
_origin_master_uuid = ORIGIN_MASTER_UUID
_origin_master_addr = os.environ.get("P2P_ORIGIN_MASTER_ADDR", "").strip()

# Lock para proteger as variáveis de estado mutável contra race conditions
# Necessário porque heartbeat e loop principal rodam em threads diferentes
_state_lock = threading.Lock()

# Evento sinalizado quando o Worker deve parar o ciclo atual e reconectar
# ao novo Master (command_redirect) ou ao Master original (command_release)
_redirect_event  = threading.Event()
_release_event   = threading.Event()


def _handle_m2m_from_master(msg: dict) -> str:
    """Sprint 03: Processa mensagem M2M recebida do Master atual.

    O Master pode enviar mensagens M2M ao Worker em dois momentos:
    - Logo após o handshake (antes de enviar uma tarefa)
    - Durante o período de espera NO_TASK (de forma assíncrona)

    Args:
        msg: dicionário com o envelope M2M (type, request_id, payload)

    Retorna:
      "redirect" — deve reconectar ao target_master_address (novo Master)
      "release"  — deve reconectar ao Master original
      "ignore"   — mensagem ignorada (tipo desconhecido ou sem ação necessária)
    """
    global _current_host, _current_port, _origin_master_uuid, _origin_master_addr

    msg_type = msg.get("type", "")

    # Tipo desconhecido — ignora e continua normalmente
    if msg_type not in M2M_KNOWN_TYPES:
        print(f"[WORKER] type M2M desconhecido='{msg_type}' — ignorando")
        return "ignore"

    # Sprint 03: command_redirect — o Master ordena reconexão ao novo Master A
    if msg_type == M2M_COMMAND_REDIRECT:
        # O payload deve conter NEW_MASTER_ADDRESS no formato "ip:porta"
        target_addr = msg.get("payload", {}).get("NEW_MASTER_ADDRESS", "")
        if not target_addr:
            print(f"[WORKER] command_redirect sem NEW_MASTER_ADDRESS — ignorando")
            return "ignore"
        print(f"[WORKER] command_redirect recebido — redirecionando para {target_addr}")
        try:
            if ":" in target_addr:
                h, p = target_addr.rsplit(":", 1)
            else:
                print(f"[WORKER] command_redirect: formato inválido '{target_addr}' — ignorando")
                return "ignore"
            with _state_lock:
                # Salva o endereço do Master atual como "origem" para futura devolução
                # Isso permite que o Worker volte ao Master correto ao receber command_release
                _origin_master_addr = f"{_current_host}:{_current_port}"
                _origin_master_uuid = HEARTBEAT_SERVER_UUID
                # Atualiza o endereço do Master para o novo destino
                _current_host = h
                _current_port = int(p)
        except ValueError:
            print(f"[WORKER] command_redirect: porta inválida em '{target_addr}' — ignorando")
            return "ignore"
        return "redirect"

    # Sprint 03: command_release — o Master ordena retorno ao Master original
    if msg_type == M2M_COMMAND_RELEASE:
        print(f"[WORKER] command_release recebido — voltando ao Master original")
        # O payload pode conter ORIGINAL_MASTER_ADDRESS; usa estado interno como fallback
        payload_orig = msg.get("payload", {}).get("ORIGINAL_MASTER_ADDRESS", "")
        with _state_lock:
            # Prioriza o endereço do payload; cai de volta no estado interno se ausente
            restore_addr = payload_orig or _origin_master_addr
            if restore_addr:
                parts = restore_addr.rsplit(":", 1)
                if len(parts) == 2:
                    # Restaura o Master original e limpa o estado de Worker emprestado
                    _current_host = parts[0]
                    _current_port = int(parts[1])
                    _origin_master_addr = ""
                    _origin_master_uuid = ""
        return "release"

    # Outros tipos M2M (ex.: request_help, response_accepted) não geram ação no Worker
    print(f"[WORKER] M2M type='{msg_type}' recebido do Master — ignorando (sem ação no Worker)")
    return "ignore"


# ---------------------------------------------------------------------------
# Sprint 03: Envia register_temporary_worker ao Master novo após redirect
# ---------------------------------------------------------------------------
def _send_register_temporary(sock: socket.socket) -> None:
    """Sprint 03: Após reconectar ao Master A, registra-se como Worker emprestado.

    Enviado imediatamente após conectar ao novo Master (antes do handshake normal).
    Informa ao Master A:
    - Qual Worker está chegando (WORKER_ID)
    - De qual Master este Worker veio (ORIGINAL_MASTER_ID)
    - Como contactar o Master de origem para futura devolução (ORIGINAL_MASTER_ADDRESS)
    """
    with _state_lock:
        orig_uuid = _origin_master_uuid
        orig_addr = _origin_master_addr

    # Monta mensagem M2M de registro usando o construtor padrão do protocolo
    msg = make_m2m_message(
        M2M_REGISTER_TEMP_WORKER,
        {
            "WORKER_ID": WORKER_UUID,
            "ORIGINAL_MASTER_ID": orig_uuid,
            "ORIGINAL_MASTER_ADDRESS": orig_addr,
        },
    )
    sock.sendall((json.dumps(msg) + "\n").encode())
    print(f"[WORKER] register_temporary_worker enviado ao novo Master (orig={orig_uuid})")


# ---------------------------------------------------------------------------
# Ciclo principal do Worker (Sprint 01/02 preservado + Sprint 03 estendido)
# ---------------------------------------------------------------------------
def execute_task(task_name: str, payload: dict):
    """Executor genérico de tarefas.

    Atualmente suporta tarefas do tipo QUERY que envolvem A e B e um operador
    opcional `OP` (add, sub, mul, div). Valida presença e tipos de A/B.
    """
    # Normaliza o nome da task para comparação simplificada
    name = (task_name or "").upper()

    # QUERY — operações aritméticas com A/B
    if name == QUERY or name == "QUERY" or name == "":
        a = payload.get("A")
        b = payload.get("B")
        op = (payload.get("OP") or "add").lower()

        if a is None or b is None:
            raise ValueError("campos A e B exigidos para esta task")

        try:
            if not isinstance(a, (int, float)):
                a = float(a)
            if not isinstance(b, (int, float)):
                b = float(b)
        except (TypeError, ValueError):
            raise ValueError("A e B devem ser números")

        if op in ("add", "sum", "+"):
            return a + b
        if op in ("sub", "-", "subtract"):
            return a - b
        if op in ("mul", "*", "multiply"):
            return a * b
        if op in ("div", "/"):
            if b == 0:
                raise ValueError("divisão por zero")
            return a / b

        raise ValueError(f"operação desconhecida: {op}")

    # PRINT — imprime uma mensagem provida no payload
    if name == "PRINT":
        msg = payload.get("MSG") or payload.get("MESSAGE") or payload.get("TEXT")
        print(f"[WORKER][PRINT] {msg}")
        return msg

    # SLEEP — pausa o Worker por N segundos (bloqueante)
    if name == "SLEEP":
        secs = payload.get("SEC") or payload.get("SECONDS") or payload.get("S")
        if secs is None:
            raise ValueError("campo SEC/SECONDS exigido para SLEEP")
        try:
            secs = float(secs)
        except (TypeError, ValueError):
            raise ValueError("SEC/SECONDS deve ser número")
        time.sleep(secs)
        return f"SLEPT {secs}"

    # SCHEDULE — agenda uma ação não-bloqueante usando threading.Timer
    # Espera payload com IN_SECONDS e ACTION (dicionário com TASK e campos)
    if name == "SCHEDULE":
        in_secs = payload.get("IN_SECONDS") or payload.get("IN_SEC") or payload.get("DELAY")
        action = payload.get("ACTION") or payload.get("JOB")
        if in_secs is None or not action or not isinstance(action, dict):
            raise ValueError("SCHEDULE requer IN_SECONDS e ACTION(dict)")
        try:
            in_secs = float(in_secs)
        except (TypeError, ValueError):
            raise ValueError("IN_SECONDS deve ser número")

        def _run_action():
            try:
                execute_task(action.get("TASK"), action)
            except Exception as e:
                print(f"[WORKER] falha em ação agendada: {e}")

        t = threading.Timer(in_secs, _run_action)
        t.daemon = True
        t.start()
        return f"SCHEDULED in {in_secs}s"

    # Task desconhecida — o Worker não sabe executar
    raise ValueError(f"task desconhecida: {task_name}")

def run_worker_loop() -> None:
    """Loop infinito que gerencia o ciclo de trabalho do Worker.

    Cada iteração do loop externo representa uma tentativa de conexão ao Master.
    Fluxo por iteração:
      1. Lê estado atual (host/port, flag de Worker emprestado)
      2. Abre nova conexão TCP ao Master
      3. (Sprint 03) Se emprestado, envia register_temporary_worker
      4. Envia handshake (WORKER=ALIVE + WORKER_UUID)
      5. Aguarda resposta do Master:
         - Mensagem M2M → processa redirect/release e reconecta
         - NO_TASK → escuta ativamente por 30s por possíveis redirects
         - QUERY → calcula e devolve resultado
      6. Aguarda ACK do Master
      7. Em caso de erro, tenta reconectar após 1s
    """
    global _current_host, _current_port, _origin_master_uuid, _origin_master_addr

    # Sprint 03: verifica se foi iniciado já como Worker emprestado (via variável de ambiente)
    _is_borrowed = bool(_origin_master_uuid)

    while True:
        # Lê o estado atual de forma thread-safe (pode ter mudado por redirect/release)
        with _state_lock:
            host = _current_host
            port = _current_port
            is_borrowed = bool(_origin_master_uuid)

        # Cria novo socket TCP para cada tentativa de conexão
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((host, port))

            # Sprint 03: se Worker emprestado, registra-se no novo Master antes do handshake
            if is_borrowed:
                _send_register_temporary(sock)
                # Nota: o servidor pode não enviar resposta imediata ao register; continua

            # Handshake padrão (Sprint 01/02): anuncia presença e identidade ao Master
            handshake = {"WORKER": WORKER_ALIVE, "WORKER_UUID": WORKER_UUID}
            if is_borrowed:
                # Inclui o UUID do Master de origem para que o novo Master saiba a procedência
                handshake["SERVER_UUID"] = _origin_master_uuid
            sock.sendall((json.dumps(handshake) + "\n").encode())

            # Aguarda resposta do Master ao handshake
            reply = recv_json_line(sock)

            # Sprint 03: Master pode enviar mensagem M2M antes da tarefa (ex.: redirect imediato)
            if is_m2m_message(reply):
                action = _handle_m2m_from_master(reply)
                if action in ("redirect", "release"):
                    continue  # fecha socket atual e reconecta ao novo destino no próximo ciclo
                # "ignore" → continua o ciclo normalmente como se fosse resposta de tarefa

            # Mostra a tarefa/resposta completa recebida do Master para debug/visibilidade
            try:
                print(f"[WORKER] Tarefa recebida: {json.dumps(reply, ensure_ascii=False)}")
            except Exception:
                # Caso o payload não seja serializável por algum motivo, faz print simples
                print(f"[WORKER] Tarefa recebida (raw): {reply}")

            # Master não tem tarefas disponíveis neste momento
            if reply.get("TASK") == TASK_NO_TASK:
                # Em vez de sleep cego de 30s, escutamos ativamente no socket em blocos de 1s.
                # Isso permite processar command_redirect/release enviados de forma assíncrona
                # pelo Master enquanto o Worker aguarda por novas tarefas.
                slept = 0
                while slept < NO_TASK_SLEEP_SEC:
                    try:
                        msg = recv_json_line(sock, timeout=10)
                        if is_m2m_message(msg):
                            action = _handle_m2m_from_master(msg)
                            if action in ("redirect", "release"):
                                break  # sai do loop de espera e reconecta no loop externo
                    except (socket.timeout, TimeoutError):
                        # Timeout de 1s normal — incrementa contador e continua esperando
                        slept += 1
                        continue
                    except Exception:
                        # Erro de conexão — sai para restabelecer no loop externo
                        break
                continue  # próxima tentativa de conexão após período de espera

            # Valida que a resposta contém um TASK conhecido (pode ser qualquer tipo)
            task_name = reply.get("TASK")
            if not task_name:
                raise ValueError(f"resposta inesperada do master: {reply}")

            # Executa a task via dispatcher genérico — handlers suportam QUERY, PRINT, SLEEP, SCHEDULE, etc.
            try:
                result = execute_task(task_name, reply)
                print(f"[WORKER] Resultado tarefa {task_name}: {result}")
            except Exception as e:
                print(f"[WORKER] falha ao executar tarefa: {e}")
                err_status = globals().get("STATUS_ERROR", "ERROR")
                body = {
                    "STATUS": err_status,
                    "TASK": task_name,
                    "WORKER_UUID": WORKER_UUID,
                    "ERROR": str(e),
                }
                sock.sendall((json.dumps(body) + "\n").encode())
                continue

            # Envia relatório de status com o resultado ao Master (Sprint 01/02)
            body = {
                "STATUS": STATUS_OK,     # indica que a tarefa foi concluída com sucesso
                "TASK": task_name,       # confirma o tipo de tarefa que está sendo reportada
                "WORKER_UUID": WORKER_UUID,  # identifica este Worker ao Master
                "RESULT": result,
            }
            sock.sendall((json.dumps(body) + "\n").encode())

            # Aguarda confirmação do Master (ACK)
            ack = recv_json_line(sock)

            # Sprint 03: Master pode enviar command_release junto com / após ACK
            # (ao devolver o Worker logo após ele concluir a tarefa)
            if is_m2m_message(ack):
                action = _handle_m2m_from_master(ack)
                if action in ("redirect", "release"):
                    continue  # reconecta ao destino correto no próximo ciclo

            # Valida o ACK: deve ter STATUS=ACK e WORKER_UUID correto
            if (
                ack.get("STATUS") != STATUS_ACK
                or ack.get("WORKER_UUID") != WORKER_UUID
            ):
                raise ValueError(f"ACK inválido: {ack}")

            print(f"[WORKER] ACK recebido — ciclo concluído para WORKER_UUID={WORKER_UUID}")

        except (
            socket.timeout,
            OSError,
            ValueError,
            json.JSONDecodeError,
            ConnectionError,
        ) as e:
            print(f"[WORKER] erro: {e}; a tentar de novo...")
            # Sprint 03: CT08 — se Master atual caiu e somos Worker emprestado,
            # tenta voltar automaticamente ao Master original sem esperar command_release
            with _state_lock:
                if _origin_master_addr and _origin_master_uuid:
                    print(f"[WORKER] Master atual caiu; voltando ao Master original {_origin_master_addr}")
                    parts = _origin_master_addr.rsplit(":", 1)
                    if len(parts) == 2:
                        # Restaura endereço do Master original e limpa estado de empréstimo
                        _current_host = parts[0]
                        _current_port = int(parts[1])
                        _origin_master_addr = ""
                        _origin_master_uuid = ""
            # Aguarda 1s antes de tentar reconectar para não sobrecarregar o servidor
            time.sleep(1)
        finally:
            # Sempre fecha o socket ao sair do bloco, independente do caminho de execução
            sock.close()


def main() -> None:
    """Ponto de entrada do Worker.

    Inicializa e inicia:
    1. Thread de heartbeat (opcional, controlada por P2P_ENABLE_HEARTBEAT)
    2. Loop principal de trabalho (síncrono, bloqueia até interrupção)
    """
    print(f"[WORKER] UUID={WORKER_UUID} a ligar a {HOST}:{PORT}")
    if ORIGIN_MASTER_UUID:
        # Modo emprestado: o Worker já sabe de antemão que pertence a outro Master
        print(
            f"[WORKER] Modo emprestado: handshake incluirá SERVER_UUID={ORIGIN_MASTER_UUID} (Master de origem)"
        )
    # Verifica se o heartbeat está ativo via variável de ambiente
    hb = os.environ.get("P2P_ENABLE_HEARTBEAT", "1").strip().lower()
    if hb not in ("0", "false", "no", "off"):
        # Inicia thread daemon de heartbeat — termina automaticamente quando o processo principal encerra
        threading.Thread(target=_heartbeat_schedule_loop, daemon=True).start()
    # Inicia o ciclo principal — bloqueia aqui até Ctrl+C ou erro fatal
    run_worker_loop()


if __name__ == "__main__":
    main()