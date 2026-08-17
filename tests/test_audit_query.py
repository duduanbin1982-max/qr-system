import pytest

from modules.audit_query import parse_audit_query


def test_audit_query_normalizes_valid_bounds():
    assert parse_audit_query("2", "20", "2026-08-01", "2026-08-17", " order ") == {
        "page": 2,
        "limit": 20,
        "date_from": "2026-08-01",
        "date_to": "2026-08-17",
        "keyword": "order",
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 0},
        {"limit": 0},
        {"limit": 201},
        {"date_from": "2026/08/01"},
        {"date_from": "2026-08-18", "date_to": "2026-08-17"},
    ],
)
def test_audit_query_rejects_invalid_bounds(kwargs):
    with pytest.raises(ValueError):
        parse_audit_query(**kwargs)
