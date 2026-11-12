"""Payroll idempotency and accounting state invariants."""

from modules.migration_helpers import MigrationInvariantError, add_column_if_missing


def _require_consistent_settlements(db):
    inconsistent = db.execute(
        """
        SELECT settlement.id, settlement.batch_id
        FROM payroll_settlements AS settlement
        LEFT JOIN payroll_batches AS batch ON batch.id=settlement.batch_id
        WHERE batch.id IS NULL
           OR batch.status <> 'confirmed'
           OR batch.superseded_by_batch_id IS NOT NULL
        ORDER BY settlement.id
        LIMIT 1
        """
    ).fetchone()
    if inconsistent is not None:
        raise MigrationInvariantError(
            "payroll settlement is not bound to a current confirmed batch: "
            f"settlement_id={inconsistent[0]}, batch_id={inconsistent[1]}"
        )

    negative_export = db.execute(
        """
        SELECT id, export_batch_id, payable_cents
        FROM payroll_export_items
        WHERE payable_cents < 0
        ORDER BY id
        LIMIT 1
        """
    ).fetchone()
    if negative_export is not None:
        raise MigrationInvariantError(
            "negative payroll export item requires financial review before migration: "
            f"item_id={negative_export[0]}, export_batch_id={negative_export[1]}, "
            f"payable_cents={negative_export[2]}"
        )


def m098_payroll_risk_closure(db):
    try:
        db.execute("BEGIN IMMEDIATE")
        _require_consistent_settlements(db)

        add_column_if_missing(
            db, "payroll_adjustments", "idempotency_key",
            "TEXT NOT NULL DEFAULT ''",
        )
        add_column_if_missing(
            db, "payroll_adjustments", "request_digest",
            "TEXT NOT NULL DEFAULT ''",
        )
        db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_payroll_adjustment_idempotency
            ON payroll_adjustments(idempotency_key)
            WHERE idempotency_key <> ''
            """
        )

        db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_payroll_settlement_current_batch_insert
            BEFORE INSERT ON payroll_settlements
            WHEN NOT EXISTS (
                SELECT 1
                FROM payroll_batches AS batch
                WHERE batch.id=NEW.batch_id
                  AND batch.status='confirmed'
                  AND batch.superseded_by_batch_id IS NULL
            )
            BEGIN
                SELECT RAISE(ABORT,'payroll settlement requires current confirmed batch');
            END
            """
        )
        db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_payroll_settlement_batch_immutable
            BEFORE UPDATE OF batch_id ON payroll_settlements
            WHEN NEW.batch_id <> OLD.batch_id
            BEGIN
                SELECT RAISE(ABORT,'payroll settlement batch is immutable');
            END
            """
        )
        db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_payroll_settled_batch_immutable
            BEFORE UPDATE OF status, superseded_by_batch_id ON payroll_batches
            WHEN EXISTS (
                SELECT 1 FROM payroll_settlements
                WHERE batch_id=OLD.id
            )
            AND (
                NEW.status <> 'confirmed'
                OR NEW.superseded_by_batch_id IS NOT NULL
            )
            BEGIN
                SELECT RAISE(ABORT,'settled payroll batch must remain current confirmed');
            END
            """
        )
        db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_payroll_batch_nonnegative_transition
            BEFORE UPDATE OF status ON payroll_batches
            WHEN NEW.status <> OLD.status
             AND NEW.status IN ('review_pending','locked','confirmed')
             AND EXISTS (
                SELECT 1
                FROM payroll_employee_lines AS line
                WHERE line.batch_id=OLD.id
                  AND line.payable_wage_cents < 0
             )
            BEGIN
                SELECT RAISE(ABORT,'negative payroll employee lines block batch transition');
            END
            """
        )
        db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_payroll_employee_line_insert_immutable
            BEFORE INSERT ON payroll_employee_lines
            WHEN (
                SELECT status FROM payroll_batches WHERE id=NEW.batch_id
            ) IN ('locked','confirmed','voided')
              OR COALESCE((
                SELECT legacy_imported FROM payroll_batches WHERE id=NEW.batch_id
              ),0)=1
            BEGIN
                SELECT RAISE(ABORT,'locked payroll employee lines are immutable');
            END
            """
        )
        db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_payroll_export_item_nonnegative
            BEFORE INSERT ON payroll_export_items
            WHEN NEW.payable_cents < 0
            BEGIN
                SELECT RAISE(ABORT,'negative payroll export items are forbidden');
            END
            """
        )
        db.commit()
    except Exception:
        if db.in_transaction:
            db.rollback()
        raise


MIGRATIONS = [
    (98, "Close payroll idempotency and accounting state risks", m098_payroll_risk_closure),
]
