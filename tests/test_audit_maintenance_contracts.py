from pathlib import Path

from modules.repositories.audit_log_repository import AuditLogRepository


def test_database_maintenance_never_deletes_audit_logs():
    script = Path(__file__).parents[1] / "scripts" / "db-maintenance.py"
    source = script.read_text(encoding="utf-8")
    assert "DELETE FROM audit_logs" not in source
    assert "controlled archive workflow owns cleanup" in source


def test_repository_exposes_no_direct_audit_log_cleanup_bypass():
    assert not hasattr(AuditLogRepository, "clear_logs_txn")
