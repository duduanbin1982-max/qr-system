"""Deterministic payroll audit findings."""

from modules.migration_helpers import add_column_if_missing


def m099_payroll_audit_findings(db):
    try:
        db.execute("BEGIN IMMEDIATE")
        add_column_if_missing(
            db, "payroll_batches", "audit_run_version", "INTEGER NOT NULL DEFAULT 0",
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS payroll_audit_findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                calculation_version INTEGER NOT NULL CHECK(calculation_version > 0),
                finding_type TEXT NOT NULL CHECK(finding_type IN (
                    'pending_approval_work','duplicate_serial_work','duplicate_work_candidate',
                    'cross_period_work','high_payroll_deviation'
                )),
                severity TEXT NOT NULL CHECK(severity IN ('blocking','review')),
                status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved','superseded')),
                subject_type TEXT NOT NULL CHECK(subject_type IN ('work_record','employee')),
                subject_id INTEGER NOT NULL CHECK(subject_id > 0),
                rule_version TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                resolution_code TEXT NOT NULL DEFAULT '',
                resolution_reason TEXT NOT NULL DEFAULT '',
                resolved_by INTEGER,
                resolved_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY(batch_id) REFERENCES payroll_batches(id) ON DELETE RESTRICT,
                FOREIGN KEY(resolved_by) REFERENCES users(id) ON DELETE RESTRICT,
                UNIQUE(batch_id,calculation_version,finding_type,subject_type,subject_id),
                CHECK(
                    (status='open' AND resolution_code='' AND resolution_reason='' AND resolved_at='')
                    OR
                    (status IN ('resolved','superseded') AND resolution_code<>''
                        AND length(trim(resolution_reason))>0 AND resolved_at<>'')
                )
            )
            """
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_payroll_audit_findings_current "
            "ON payroll_audit_findings(batch_id,calculation_version,status,severity,finding_type)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_payroll_audit_findings_subject "
            "ON payroll_audit_findings(subject_type,subject_id,finding_type)"
        )
        db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_payroll_audit_finding_definition_immutable
            BEFORE UPDATE OF batch_id,calculation_version,finding_type,severity,subject_type,
                subject_id,rule_version,snapshot_json,created_at ON payroll_audit_findings
            BEGIN
                SELECT RAISE(ABORT,'payroll audit finding evidence is immutable');
            END
            """
        )
        db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_payroll_audit_finding_resolution_once
            BEFORE UPDATE OF status,resolution_code,resolution_reason,resolved_by,resolved_at
                ON payroll_audit_findings
            WHEN OLD.status<>'open'
              OR NEW.status NOT IN ('resolved','superseded')
              OR NEW.resolution_code=''
              OR length(trim(NEW.resolution_reason))=0
              OR NEW.resolved_at=''
            BEGIN
                SELECT RAISE(ABORT,'payroll audit finding resolution is one-way and requires evidence');
            END
            """
        )
        db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_payroll_audit_finding_no_delete
            BEFORE DELETE ON payroll_audit_findings
            BEGIN
                SELECT RAISE(ABORT,'payroll audit findings are immutable');
            END
            """
        )
        db.commit()
    except Exception:
        if db.in_transaction:
            db.rollback()
        raise


MIGRATIONS = [
    (99, "Add deterministic payroll audit findings", m099_payroll_audit_findings),
]
