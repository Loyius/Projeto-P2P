import pytest

from protocol import validate_worker_handshake, validate_status_report, QUERY
from protocol import STATUS_OK, STATUS_NOK


def test_handshake_accepts_unknown_keys():
    validate_worker_handshake(
        {"WORKER": "ALIVE", "WORKER_UUID": "w1", "EXTRA": 123}
    )


def test_handshake_rejects_missing_uuid():
    with pytest.raises(ValueError):
        validate_worker_handshake({"WORKER": "ALIVE"})


def test_handshake_rejects_wrong_alive_case():
    with pytest.raises(ValueError):
        validate_worker_handshake({"WORKER": "alive", "WORKER_UUID": "w1"})


def test_status_ok():
    validate_status_report(
        {"STATUS": "OK", "TASK": QUERY, "WORKER_UUID": "w1"}
    )


def test_status_nok():
    validate_status_report(
        {"STATUS": "NOK", "TASK": QUERY, "WORKER_UUID": "w1"}
    )
