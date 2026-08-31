import json

from modules.audit_policy import REDACTED_VALUE, sanitize_audit_detail


def test_structured_audit_detail_redacts_secret_fields():
    detail = sanitize_audit_detail({
        "smtp_password": "super-secret",
        "board_token": "board-secret",
        "phone": "13800000000",
        "address": "sensitive-address",
        "changed_fields": ["smtp_host"],
    })

    payload = json.loads(detail)
    assert payload["smtp_password"] == REDACTED_VALUE
    assert payload["board_token"] == REDACTED_VALUE
    assert payload["phone"] == REDACTED_VALUE
    assert payload["address"] == REDACTED_VALUE
    assert payload["changed_fields"] == ["smtp_host"]


def test_legacy_string_detail_redacts_key_value_forms():
    detail = sanitize_audit_detail(
        "smtp_password=super-secret, board_token: 'board-secret', smtp_host=smtp.local"
    )

    assert "super-secret" not in detail
    assert "board-secret" not in detail
    assert "smtp_password=[REDACTED]" in detail
    assert "board_token: '[REDACTED]'" in detail
    assert "smtp_host=smtp.local" in detail
