"""Bind payroll audit policy versions to calculation snapshots."""

from modules.migration_helpers import add_column_if_missing


def m100_payroll_audit_policy_version(db):
    try:
        db.execute("BEGIN IMMEDIATE")
        add_column_if_missing(
            db, "payroll_batches", "audit_rule_version", "TEXT NOT NULL DEFAULT ''",
        )
        db.execute("DROP TRIGGER IF EXISTS prevent_invalid_payroll_batch_transition")
        db.execute(
            """
            CREATE TRIGGER prevent_invalid_payroll_batch_transition
            BEFORE UPDATE OF status ON payroll_batches
            WHEN OLD.status<>NEW.status AND NOT (
                (OLD.status='draft' AND NEW.status IN ('exceptions_pending','review_pending','voided')) OR
                (OLD.status='exceptions_pending' AND NEW.status IN ('draft','review_pending','voided')) OR
                (OLD.status='review_pending' AND NEW.status IN ('locked','voided')) OR
                (OLD.status='locked' AND NEW.status IN ('confirmed','voided')) OR
                (OLD.status='confirmed' AND NEW.status='voided') OR
                (OLD.status='review_pending' AND NEW.status IN ('draft','exceptions_pending')
                    AND NEW.audit_rule_version<>OLD.audit_rule_version
                    AND NEW.audit_run_version=OLD.audit_run_version+1
                    AND NEW.row_version=OLD.row_version+1)
            )
            BEGIN SELECT RAISE(ABORT,'invalid payroll batch status transition'); END
            """
        )
        db.execute("DROP TRIGGER IF EXISTS protect_payroll_batch_amounts")
        db.execute(
            """
            CREATE TRIGGER protect_payroll_batch_amounts
            BEFORE UPDATE OF payroll_month,version,period_start,period_end,source_cutoff_at,input_digest,
                audit_rule_version,normal_wage_cents,rework_wage_cents,bonus_cents,allowance_cents,
                deduction_cents,payable_wage_cents,source_record_count,priced_record_count,
                exception_count,prepared_by,prepared_at
            ON payroll_batches
            WHEN OLD.status IN ('locked','confirmed','voided') OR OLD.legacy_imported=1
            BEGIN SELECT RAISE(ABORT,'locked payroll batches are immutable'); END
            """
        )
        db.execute("DROP TRIGGER IF EXISTS protect_payroll_audit_rule_version")
        db.execute(
            """
            CREATE TRIGGER protect_payroll_audit_rule_version
            BEFORE UPDATE OF audit_rule_version ON payroll_batches
            WHEN NEW.audit_rule_version<>OLD.audit_rule_version AND NOT (
                OLD.status IN ('draft','exceptions_pending')
                    AND NEW.status IN ('draft','exceptions_pending')
                    AND NEW.audit_run_version=OLD.audit_run_version+1
                    AND NEW.row_version=OLD.row_version+1
                OR OLD.status='review_pending'
                    AND NEW.status IN ('draft','exceptions_pending')
                    AND NEW.audit_run_version=OLD.audit_run_version+1
                    AND NEW.row_version=OLD.row_version+1
            )
            BEGIN SELECT RAISE(ABORT,'audit rule version requires recalculation'); END
            """
        )
        db.commit()
    except Exception:
        if db.in_transaction:
            db.rollback()
        raise


MIGRATIONS = [
    (100, "Bind audit policy version to payroll calculations", m100_payroll_audit_policy_version),
]
