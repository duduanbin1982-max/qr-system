from modules.audit_policy import AUDIT_MIN_RETENTION_DAYS


def test_audit_retention_floor_is_three_years():
    assert AUDIT_MIN_RETENTION_DAYS == 1095
