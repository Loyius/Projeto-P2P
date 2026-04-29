"""Mensagens de controlo P2P (valores em MAIÚSCULAS)."""
from __future__ import annotations

WORKER_ALIVE = "ALIVE"
QUERY = "QUERY"
TASK_NO_TASK = "NO_TASK"
STATUS_OK = "OK"
STATUS_NOK = "NOK"
STATUS_ACK = "ACK"

# Validação do handshake
def validate_worker_handshake(payload: dict) -> None:
    if payload.get("WORKER") != WORKER_ALIVE:
        raise ValueError("missing or invalid WORKER (expected ALIVE)")
    uid = payload.get("WORKER_UUID")
    if not isinstance(uid, str) or not uid:
        raise ValueError("WORKER_UUID is required and must be a non-empty string")

# Validação do status report
def validate_status_report(payload: dict) -> None:
    status = payload.get("STATUS")
    if status not in (STATUS_OK, STATUS_NOK):
        raise ValueError("STATUS must be OK or NOK (case-sensitive)")
    if payload.get("TASK") != QUERY:
        raise ValueError("TASK must be QUERY for this report")
    uid = payload.get("WORKER_UUID")
    if not isinstance(uid, str) or not uid:
        raise ValueError("WORKER_UUID is required and must be a non-empty string")
