"""Mensagens de controlo P2P (valores em MAIÚSCULAS).

Este módulo centraliza todas as constantes, validadores e construtores
do protocolo de comunicação entre Workers e Masters (Sprint 01/02)
e entre Masters (M2M — Sprint 03).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Sprint 01/02: Constantes do protocolo Worker ↔ Master
# ---------------------------------------------------------------------------

# Valor enviado pelo Worker no campo "WORKER" para indicar que está vivo
WORKER_ALIVE = "ALIVE"

# Tipo de tarefa: o Master envia este valor para indicar que há uma query a processar
QUERY = "QUERY"

# Resposta do Master quando não há tarefas disponíveis na fila
TASK_NO_TASK = "NO_TASK"

# Status de sucesso enviado pelo Worker após concluir uma tarefa
STATUS_OK = "OK"

# Status de falha enviado pelo Worker quando não consegue executar a tarefa
STATUS_NOK = "NOK"

# Confirmação enviada pelo Master ao receber o resultado do Worker (acknowledgement)
STATUS_ACK = "ACK"


def validate_worker_handshake(payload: dict) -> None:
    """Valida o payload de handshake enviado pelo Worker ao se conectar.

    Verifica:
    - Campo "WORKER" deve ter o valor ALIVE para confirmar que o Worker está ativo
    - Campo "WORKER_UUID" deve ser uma string não vazia (identificador único do Worker)

    Lança ValueError com mensagem descritiva se qualquer campo estiver ausente ou inválido.
    """
    # Verifica se o campo WORKER contém o valor esperado "ALIVE"
    if payload.get("WORKER") != WORKER_ALIVE:
        raise ValueError("missing or invalid WORKER (expected ALIVE)")

    # Verifica se WORKER_UUID é uma string não vazia (identificador único do Worker)
    uid = payload.get("WORKER_UUID")
    if not isinstance(uid, str) or not uid:
        raise ValueError("WORKER_UUID is required and must be a non-empty string")


def validate_status_report(payload: dict) -> None:
    """Valida o payload de relatório de status enviado pelo Worker após executar uma tarefa.

    Verifica:
    - Campo "STATUS" deve ser OK ou NOK (distinção de maiúsculas/minúsculas)
    - Campo "TASK" deve ser QUERY (só processamos relatórios de tarefas do tipo QUERY)
    - Campo "WORKER_UUID" deve ser uma string não vazia

    Lança ValueError com mensagem descritiva se qualquer campo estiver ausente ou inválido.
    """
    # Verifica se o status é um dos valores permitidos: OK ou NOK
    status = payload.get("STATUS")
    if status not in (STATUS_OK, STATUS_NOK):
        raise ValueError("STATUS must be OK or NOK (case-sensitive)")

    # Verifica se a tarefa reportada é do tipo QUERY
    if payload.get("TASK") != QUERY:
        raise ValueError("TASK must be QUERY for this report")

    # Verifica se o identificador do Worker está presente
    uid = payload.get("WORKER_UUID")
    if not isinstance(uid, str) or not uid:
        raise ValueError("WORKER_UUID is required and must be a non-empty string")


# ---------------------------------------------------------------------------
# Sprint 03: Tipos de mensagem Master-to-Master (case-sensitive, minúsculas)
# ---------------------------------------------------------------------------

# Master A solicita Workers emprestados ao Master B por estar sobrecarregado
M2M_REQUEST_HELP        = "request_help"

# Master B aceita o pedido e vai redirecionar Workers para o Master A
M2M_RESPONSE_ACCEPTED   = "response_accepted"

# Master B recusa o pedido (ex.: sem Workers ociosos disponíveis)
M2M_RESPONSE_REJECTED   = "response_rejected"

# Master B ordena ao Worker que se reconecte ao Master A (redirecionamento)
M2M_COMMAND_REDIRECT    = "command_redirect"

# Worker emprestado envia esta mensagem ao chegar no novo Master para se registrar
M2M_REGISTER_TEMP_WORKER = "register_temporary_worker"

# Master A ordena ao Worker emprestado que volte ao Master original (devolução)
M2M_COMMAND_RELEASE     = "command_release"

# Master A notifica o Master B que o Worker emprestado foi devolvido
M2M_NOTIFY_RETURNED     = "notify_worker_returned"

# Sprint 03: Conjunto de todos os tipos M2M conhecidos (para strict parsing)
# Usado para rejeitar rapidamente mensagens com tipos desconhecidos ou inválidos
M2M_KNOWN_TYPES: frozenset[str] = frozenset({
    M2M_REQUEST_HELP,
    M2M_RESPONSE_ACCEPTED,
    M2M_RESPONSE_REJECTED,
    M2M_COMMAND_REDIRECT,
    M2M_REGISTER_TEMP_WORKER,
    M2M_COMMAND_RELEASE,
    M2M_NOTIFY_RETURNED,
})


def validate_m2m_message(msg: dict) -> None:
    """Sprint 03: Valida envelope M2M obrigatório.

    Toda mensagem M2M deve ter os campos:
    - "type":       identifica o tipo da operação (ex.: request_help)
    - "request_id": UUID único para rastreamento/correlação da mensagem
    - "payload":    dicionário com os dados específicos do tipo

    Campos desconhecidos são ignorados (compatibilidade futura).
    Lança ValueError com detalhe se campos obrigatórios ausentes.
    """
    # Verifica a presença dos três campos obrigatórios do envelope M2M
    for field in ("type", "request_id", "payload"):
        if field not in msg:
            raise ValueError(f"Campo obrigatório '{field}' ausente na mensagem M2M")

    # O payload deve ser sempre um objeto JSON (dicionário), nunca uma string ou lista
    if not isinstance(msg["payload"], dict):
        raise ValueError("Campo 'payload' deve ser um objeto JSON")


def make_m2m_message(msg_type: str, payload: dict, request_id: str | None = None) -> dict:
    """Sprint 03: Monta envelope M2M padrão.

    Cria um dicionário com a estrutura padrão de mensagem M2M:
    - "type":       tipo da operação
    - "request_id": UUID gerado automaticamente se não fornecido
    - "payload":    dados específicos da operação

    Args:
        msg_type:   tipo da mensagem (usar as constantes M2M_* deste módulo)
        payload:    dados do corpo da mensagem
        request_id: identificador opcional; se None, um UUID4 é gerado
    """
    import uuid
    return {
        "type": msg_type,
        # Gera UUID único se não fornecido — garante rastreabilidade de cada mensagem
        "request_id": request_id or str(uuid.uuid4()),
        "payload": payload,
    }


def is_m2m_message(payload: dict) -> bool:
    """Sprint 03: Retorna True se payload pertence ao protocolo M2M.

    Detecta mensagens M2M verificando:
    - Presença do campo "type"
    - Valor de "type" está entre os tipos M2M conhecidos

    Usado para diferenciar mensagens de Worker (WORKER_ALIVE, STATUS) de
    mensagens entre Masters (request_help, command_redirect, etc.).
    """
    return "type" in payload and payload.get("type") in M2M_KNOWN_TYPES
