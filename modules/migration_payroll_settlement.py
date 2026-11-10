"""Persistent payroll export, receipt, reconciliation, and close ledger."""


def m097_payroll_settlement(db):
    try:
        db.executescript(
            """
        BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS payroll_settlements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK(status IN (
                'exported','receipting','difference_pending','reconciled','closed'
            )),
            expected_total_cents INTEGER NOT NULL DEFAULT 0,
            successful_paid_cents INTEGER NOT NULL DEFAULT 0,
            difference_cents INTEGER NOT NULL DEFAULT 0,
            blocking_difference_count INTEGER NOT NULL DEFAULT 0,
            current_export_batch_id INTEGER,
            latest_reconciliation_run_id INTEGER,
            row_version INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER,
            created_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(batch_id) REFERENCES payroll_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS payroll_export_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            settlement_id INTEGER NOT NULL,
            export_version INTEGER NOT NULL CHECK(export_version > 0),
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active','superseded','cancelled')),
            row_count INTEGER NOT NULL CHECK(row_count >= 0),
            total_cents INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64),
            csv_content_blob BLOB NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_by INTEGER,
            created_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            superseded_at TEXT NOT NULL DEFAULT '',
            superseded_by_export_id INTEGER,
            FOREIGN KEY(settlement_id) REFERENCES payroll_settlements(id) ON DELETE RESTRICT,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(superseded_by_export_id) REFERENCES payroll_export_batches(id) ON DELETE RESTRICT,
            UNIQUE(settlement_id,export_version)
        );

        CREATE TABLE IF NOT EXISTS payroll_export_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            export_batch_id INTEGER NOT NULL,
            employee_line_id INTEGER NOT NULL,
            employee_id INTEGER,
            employee_no_snapshot TEXT NOT NULL DEFAULT '',
            employee_name_snapshot TEXT NOT NULL,
            payable_cents INTEGER NOT NULL,
            payment_reference TEXT NOT NULL UNIQUE,
            sequence_no INTEGER NOT NULL CHECK(sequence_no > 0),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(export_batch_id) REFERENCES payroll_export_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(employee_line_id) REFERENCES payroll_employee_lines(id) ON DELETE RESTRICT,
            FOREIGN KEY(employee_id) REFERENCES users(id) ON DELETE SET NULL,
            UNIQUE(export_batch_id,employee_line_id),
            UNIQUE(export_batch_id,sequence_no)
        );

        CREATE TABLE IF NOT EXISTS payroll_receipt_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            export_batch_id INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('accepted','validation_failed','superseded')),
            source_filename TEXT NOT NULL DEFAULT '',
            content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64),
            accepted_row_count INTEGER NOT NULL DEFAULT 0,
            failed_row_count INTEGER NOT NULL DEFAULT 0,
            idempotency_key TEXT NOT NULL UNIQUE,
            uploaded_by INTEGER,
            uploaded_by_name TEXT NOT NULL DEFAULT '',
            uploaded_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(export_batch_id) REFERENCES payroll_export_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(uploaded_by) REFERENCES users(id) ON DELETE SET NULL,
            UNIQUE(export_batch_id,content_sha256)
        );

        CREATE TABLE IF NOT EXISTS payroll_receipt_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_batch_id INTEGER NOT NULL,
            row_number INTEGER NOT NULL CHECK(row_number > 0),
            payment_reference TEXT NOT NULL DEFAULT '',
            employee_no_snapshot TEXT NOT NULL DEFAULT '',
            employee_name_snapshot TEXT NOT NULL DEFAULT '',
            paid_cents INTEGER,
            payment_status TEXT NOT NULL DEFAULT '',
            paid_at TEXT NOT NULL DEFAULT '',
            external_transaction_no TEXT NOT NULL DEFAULT '',
            failure_reason TEXT NOT NULL DEFAULT '',
            validation_status TEXT NOT NULL CHECK(validation_status IN ('valid','invalid')),
            validation_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(receipt_batch_id) REFERENCES payroll_receipt_batches(id) ON DELETE RESTRICT,
            UNIQUE(receipt_batch_id,row_number)
        );

        CREATE TABLE IF NOT EXISTS payroll_reconciliation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            settlement_id INTEGER NOT NULL,
            export_batch_id INTEGER NOT NULL,
            run_version INTEGER NOT NULL CHECK(run_version > 0),
            status TEXT NOT NULL CHECK(status IN ('difference_pending','reconciled')),
            expected_total_cents INTEGER NOT NULL,
            successful_paid_cents INTEGER NOT NULL,
            difference_cents INTEGER NOT NULL,
            blocking_count INTEGER NOT NULL DEFAULT 0,
            receipt_digest TEXT NOT NULL CHECK(length(receipt_digest)=64),
            idempotency_key TEXT NOT NULL UNIQUE,
            executed_by INTEGER,
            executed_by_name TEXT NOT NULL DEFAULT '',
            executed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(settlement_id) REFERENCES payroll_settlements(id) ON DELETE RESTRICT,
            FOREIGN KEY(export_batch_id) REFERENCES payroll_export_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(executed_by) REFERENCES users(id) ON DELETE SET NULL,
            UNIQUE(settlement_id,run_version)
        );

        CREATE TABLE IF NOT EXISTS payroll_reconciliation_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reconciliation_run_id INTEGER NOT NULL,
            export_item_id INTEGER,
            payment_reference TEXT NOT NULL DEFAULT '',
            expected_cents INTEGER NOT NULL DEFAULT 0,
            successful_paid_cents INTEGER NOT NULL DEFAULT 0,
            difference_cents INTEGER NOT NULL DEFAULT 0,
            difference_type TEXT NOT NULL CHECK(difference_type IN (
                'missing_receipt','underpaid','overpaid','duplicate_success',
                'unknown_reference','employee_mismatch','failed_payment','invalid_amount'
            )),
            blocking INTEGER NOT NULL CHECK(blocking IN (0,1)),
            detail_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(reconciliation_run_id) REFERENCES payroll_reconciliation_runs(id) ON DELETE RESTRICT,
            FOREIGN KEY(export_item_id) REFERENCES payroll_export_items(id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS payroll_reconciliation_resolutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reconciliation_item_id INTEGER NOT NULL,
            receipt_item_id INTEGER,
            resolution_code TEXT NOT NULL CHECK(resolution_code IN (
                'exclude_duplicate','accept_name_mismatch','exclude_unknown_reference'
            )),
            resolution_reason TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            resolved_by INTEGER,
            resolved_by_name TEXT NOT NULL DEFAULT '',
            resolved_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(reconciliation_item_id) REFERENCES payroll_reconciliation_items(id) ON DELETE RESTRICT,
            FOREIGN KEY(receipt_item_id) REFERENCES payroll_receipt_items(id) ON DELETE RESTRICT,
            FOREIGN KEY(resolved_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS payroll_close_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            settlement_id INTEGER NOT NULL UNIQUE,
            export_batch_id INTEGER NOT NULL,
            reconciliation_run_id INTEGER NOT NULL,
            expected_total_cents INTEGER NOT NULL,
            successful_paid_cents INTEGER NOT NULL,
            close_digest TEXT NOT NULL CHECK(length(close_digest)=64),
            close_reason TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            closed_by INTEGER,
            closed_by_name TEXT NOT NULL DEFAULT '',
            closed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(settlement_id) REFERENCES payroll_settlements(id) ON DELETE RESTRICT,
            FOREIGN KEY(export_batch_id) REFERENCES payroll_export_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(reconciliation_run_id) REFERENCES payroll_reconciliation_runs(id) ON DELETE RESTRICT,
            FOREIGN KEY(closed_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_payroll_settlements_status
            ON payroll_settlements(status,updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_payroll_export_batches_settlement
            ON payroll_export_batches(settlement_id,export_version DESC);
        CREATE INDEX IF NOT EXISTS idx_payroll_receipt_batches_export
            ON payroll_receipt_batches(export_batch_id,uploaded_at);
        CREATE INDEX IF NOT EXISTS idx_payroll_receipt_items_reference
            ON payroll_receipt_items(payment_reference,validation_status,payment_status);
        CREATE INDEX IF NOT EXISTS idx_payroll_reconciliation_runs_settlement
            ON payroll_reconciliation_runs(settlement_id,run_version DESC);
        CREATE INDEX IF NOT EXISTS idx_payroll_reconciliation_items_run
            ON payroll_reconciliation_items(reconciliation_run_id,blocking,difference_type);

        CREATE TRIGGER IF NOT EXISTS protect_payroll_export_item_update
        BEFORE UPDATE ON payroll_export_items
        BEGIN SELECT RAISE(ABORT,'payroll export items are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_export_item_delete
        BEFORE DELETE ON payroll_export_items
        BEGIN SELECT RAISE(ABORT,'payroll export items are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_export_content_update
        BEFORE UPDATE OF settlement_id,export_version,row_count,total_cents,content_sha256,
            csv_content_blob,idempotency_key,created_by,created_by_name,created_at
        ON payroll_export_batches
        BEGIN SELECT RAISE(ABORT,'payroll export content is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_export_batch_delete
        BEFORE DELETE ON payroll_export_batches
        BEGIN SELECT RAISE(ABORT,'payroll export batches are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_receipt_batch_update
        BEFORE UPDATE ON payroll_receipt_batches
        BEGIN SELECT RAISE(ABORT,'payroll receipt batches are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_receipt_batch_delete
        BEFORE DELETE ON payroll_receipt_batches
        BEGIN SELECT RAISE(ABORT,'payroll receipt batches are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_receipt_item_update
        BEFORE UPDATE ON payroll_receipt_items
        BEGIN SELECT RAISE(ABORT,'payroll receipt items are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_receipt_item_delete
        BEFORE DELETE ON payroll_receipt_items
        BEGIN SELECT RAISE(ABORT,'payroll receipt items are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_reconciliation_run_update
        BEFORE UPDATE ON payroll_reconciliation_runs
        BEGIN SELECT RAISE(ABORT,'payroll reconciliation runs are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_reconciliation_run_delete
        BEFORE DELETE ON payroll_reconciliation_runs
        BEGIN SELECT RAISE(ABORT,'payroll reconciliation runs are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_reconciliation_item_update
        BEFORE UPDATE ON payroll_reconciliation_items
        BEGIN SELECT RAISE(ABORT,'payroll reconciliation items are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_reconciliation_item_delete
        BEFORE DELETE ON payroll_reconciliation_items
        BEGIN SELECT RAISE(ABORT,'payroll reconciliation items are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_reconciliation_resolution_update
        BEFORE UPDATE ON payroll_reconciliation_resolutions
        BEGIN SELECT RAISE(ABORT,'payroll reconciliation resolutions are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_reconciliation_resolution_delete
        BEFORE DELETE ON payroll_reconciliation_resolutions
        BEGIN SELECT RAISE(ABORT,'payroll reconciliation resolutions are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_close_record_update
        BEFORE UPDATE ON payroll_close_records
        BEGIN SELECT RAISE(ABORT,'payroll close records are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_payroll_close_record_delete
        BEFORE DELETE ON payroll_close_records
        BEGIN SELECT RAISE(ABORT,'payroll close records are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS protect_closed_payroll_settlement
        BEFORE UPDATE ON payroll_settlements
        WHEN OLD.status='closed'
        BEGIN SELECT RAISE(ABORT,'closed payroll settlements are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS prevent_payroll_settlement_delete
        BEFORE DELETE ON payroll_settlements
        BEGIN SELECT RAISE(ABORT,'payroll settlements are auditable and cannot be deleted'); END;
        COMMIT;
        """
        )
    except Exception:
        if db.in_transaction:
            db.rollback()
        raise


MIGRATIONS = [
    (97, "Add persistent payroll settlement ledger", m097_payroll_settlement),
]
