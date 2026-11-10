"""SQL access for the persistent payroll settlement sub-ledger."""

import json

from modules.repositories.context import resolve_db


class PayrollSettlementRepository:
    EXPORT_METADATA_COLUMNS = (
        "id,settlement_id,export_version,status,row_count,total_cents,content_sha256,"
        "idempotency_key,created_by,created_by_name,created_at,superseded_at,"
        "superseded_by_export_id"
    )

    @staticmethod
    def get_settlement(settlement_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_settlements WHERE id=?", (settlement_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_by_batch(batch_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_settlements WHERE batch_id=?", (batch_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def receipt_batch_count(export_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT COUNT(*) AS count FROM payroll_receipt_batches WHERE export_batch_id=?",
            (export_id,),
        ).fetchone()
        return int(row["count"])

    @staticmethod
    def supersede_export(export_id, superseded_by_export_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "UPDATE payroll_export_batches SET status='superseded',"
            "superseded_at=datetime('now','localtime'),superseded_by_export_id=? "
            "WHERE id=? AND status='active'",
            (superseded_by_export_id, export_id),
        ).rowcount

    @staticmethod
    def create_settlement(batch_id, total_cents, actor_id, actor_name, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            "INSERT INTO payroll_settlements "
            "(batch_id,status,expected_total_cents,created_by,created_by_name) "
            "VALUES (?,'exported',?,?,?)",
            (batch_id, total_cents, actor_id, actor_name),
        )
        return PayrollSettlementRepository.get_settlement(cursor.lastrowid, db)

    @staticmethod
    def next_export_version(settlement_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT COALESCE(MAX(export_version),0)+1 AS version "
            "FROM payroll_export_batches WHERE settlement_id=?",
            (settlement_id,),
        ).fetchone()
        return int(row["version"])

    @staticmethod
    def create_export_batch(settlement_id, version, rows, total_cents, digest,
                            content, idempotency_key, actor_id, actor_name, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            "INSERT INTO payroll_export_batches "
            "(settlement_id,export_version,status,row_count,total_cents,content_sha256,"
            "csv_content_blob,idempotency_key,created_by,created_by_name) "
            "VALUES (?,?, 'active',?,?,?,?,?,?,?)",
            (settlement_id, version, len(rows), total_cents, digest, content,
             idempotency_key, actor_id, actor_name),
        )
        export_id = cursor.lastrowid
        for row in rows:
            db.execute(
                "INSERT INTO payroll_export_items "
                "(export_batch_id,employee_line_id,employee_id,employee_no_snapshot,"
                "employee_name_snapshot,payable_cents,payment_reference,sequence_no) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (export_id, row["employee_line_id"], row.get("employee_id"),
                 row["employee_no_snapshot"], row["employee_name_snapshot"],
                 row["payable_cents"], row["payment_reference"], row["sequence_no"]),
            )
        return export_id

    @staticmethod
    def activate_export(settlement_id, total_cents, export_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "UPDATE payroll_settlements SET status='exported',expected_total_cents=?,"
            "successful_paid_cents=0,difference_cents=?,blocking_difference_count=0,"
            "current_export_batch_id=?,latest_reconciliation_run_id=NULL,"
            "row_version=row_version+1,updated_at=datetime('now','localtime') WHERE id=?",
            (total_cents, total_cents, export_id, settlement_id),
        ).rowcount

    @staticmethod
    def create_receipt_batch(export_id, status, filename, digest, accepted_count,
                             failed_count, idempotency_key, actor_id, actor_name, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            "INSERT INTO payroll_receipt_batches "
            "(export_batch_id,status,source_filename,content_sha256,accepted_row_count,"
            "failed_row_count,idempotency_key,uploaded_by,uploaded_by_name) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (export_id, status, filename, digest, accepted_count, failed_count,
             idempotency_key, actor_id, actor_name),
        )
        return cursor.lastrowid

    @staticmethod
    def insert_receipt_item(receipt_batch_id, row, db=None):
        db = resolve_db(db)
        return db.execute(
            "INSERT INTO payroll_receipt_items "
            "(receipt_batch_id,row_number,payment_reference,employee_no_snapshot,"
            "employee_name_snapshot,paid_cents,payment_status,paid_at,external_transaction_no,"
            "failure_reason,validation_status,validation_error) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (receipt_batch_id, row["row_number"], row.get("payment_reference", ""),
             row.get("employee_no_snapshot", ""), row.get("employee_name_snapshot", ""),
             row.get("paid_cents"), row.get("payment_status", ""), row.get("paid_at", ""),
             row.get("external_transaction_no", ""), row.get("failure_reason", ""),
             row["validation_status"], row["validation_error"]),
        ).lastrowid

    @staticmethod
    def mark_receipting(settlement_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "UPDATE payroll_settlements SET status='receipting',"
            "latest_reconciliation_run_id=NULL,row_version=row_version+1,"
            "updated_at=datetime('now','localtime') WHERE id=?",
            (settlement_id,),
        ).rowcount

    @staticmethod
    def get_receipt_batch_detail(receipt_batch_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_receipt_batches WHERE id=?", (receipt_batch_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["items"] = [dict(item) for item in db.execute(
            "SELECT * FROM payroll_receipt_items WHERE receipt_batch_id=? ORDER BY row_number",
            (receipt_batch_id,),
        ).fetchall()]
        return result

    @staticmethod
    def next_reconciliation_version(settlement_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT COALESCE(MAX(run_version),0)+1 AS version "
            "FROM payroll_reconciliation_runs WHERE settlement_id=?",
            (settlement_id,),
        ).fetchone()
        return int(row["version"])

    @staticmethod
    def create_reconciliation_run(settlement_id, export_id, version, status,
                                  expected_cents, paid_cents, difference_cents,
                                  blocking_count, receipt_digest, idempotency_key,
                                  actor_id, actor_name, findings, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            "INSERT INTO payroll_reconciliation_runs "
            "(settlement_id,export_batch_id,run_version,status,expected_total_cents,"
            "successful_paid_cents,difference_cents,blocking_count,receipt_digest,"
            "idempotency_key,executed_by,executed_by_name) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (settlement_id, export_id, version, status, expected_cents, paid_cents,
             difference_cents, blocking_count, receipt_digest, idempotency_key,
             actor_id, actor_name),
        )
        run_id = cursor.lastrowid
        for row in findings:
            db.execute(
                "INSERT INTO payroll_reconciliation_items "
                "(reconciliation_run_id,export_item_id,payment_reference,expected_cents,"
                "successful_paid_cents,difference_cents,difference_type,blocking,detail_json) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, row["export_item_id"], row["payment_reference"],
                 row["expected_cents"], row["successful_paid_cents"],
                 row["difference_cents"], row["difference_type"], row["blocking"],
                 row["detail_json"]),
            )
        return run_id

    @staticmethod
    def update_reconciliation_summary(settlement_id, status, paid_cents,
                                      difference_cents, blocking_count, run_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "UPDATE payroll_settlements SET status=?,successful_paid_cents=?,"
            "difference_cents=?,blocking_difference_count=?,latest_reconciliation_run_id=?,"
            "row_version=row_version+1,updated_at=datetime('now','localtime') WHERE id=?",
            (status, paid_cents, difference_cents, blocking_count, run_id, settlement_id),
        ).rowcount

    @staticmethod
    def get_resolution_by_key(idempotency_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_reconciliation_resolutions WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_reconciliation_item_context(item_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT item.*,run.settlement_id,run.export_batch_id,run.id AS run_id "
            "FROM payroll_reconciliation_items item "
            "JOIN payroll_reconciliation_runs run ON run.id=item.reconciliation_run_id "
            "WHERE item.id=?", (item_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_receipt_item_export(receipt_item_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT item.id,batch.export_batch_id FROM payroll_receipt_items item "
            "JOIN payroll_receipt_batches batch ON batch.id=item.receipt_batch_id "
            "WHERE item.id=?", (receipt_item_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def create_resolution(item_id, receipt_item_id, code, reason, idempotency_key,
                          actor_id, actor_name, db=None):
        db = resolve_db(db)
        return db.execute(
            "INSERT INTO payroll_reconciliation_resolutions "
            "(reconciliation_item_id,receipt_item_id,resolution_code,resolution_reason,"
            "idempotency_key,resolved_by,resolved_by_name) VALUES (?,?,?,?,?,?,?)",
            (item_id, receipt_item_id, code, reason, idempotency_key, actor_id, actor_name),
        ).lastrowid

    @staticmethod
    def get_close_record_by_key(idempotency_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_close_records WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def create_close_record(settlement_id, export_id, run_id, expected_cents,
                            paid_cents, digest, reason, idempotency_key,
                            actor_id, actor_name, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            "INSERT INTO payroll_close_records "
            "(settlement_id,export_batch_id,reconciliation_run_id,expected_total_cents,"
            "successful_paid_cents,close_digest,close_reason,idempotency_key,closed_by,closed_by_name) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (settlement_id, export_id, run_id, expected_cents, paid_cents, digest,
             reason, idempotency_key, actor_id, actor_name),
        )
        return cursor.lastrowid

    @staticmethod
    def mark_closed(settlement_id, expected_version, db=None):
        db = resolve_db(db)
        return db.execute(
            "UPDATE payroll_settlements SET status='closed',row_version=row_version+1,"
            "updated_at=datetime('now','localtime') "
            "WHERE id=? AND row_version=? AND status='reconciled'",
            (settlement_id, expected_version),
        ).rowcount

    @staticmethod
    def get_close_record_by_id(close_record_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_close_records WHERE id=?", (close_record_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_event(payload, db):
        key = str(payload.get("idempotency_key") or "")
        if key:
            row = db.execute(
                "SELECT * FROM payroll_events WHERE idempotency_key=? ORDER BY id LIMIT 1",
                (key,),
            ).fetchone()
            if row:
                return dict(row)
        db.execute(
            "INSERT INTO payroll_events "
            "(batch_id,event_type,from_status,to_status,operator_id,operator_name,reason,"
            "payload_json,request_id,idempotency_key) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (payload.get("batch_id"), payload["event_type"], payload.get("from_status", ""),
             payload.get("to_status", ""), payload.get("operator_id"),
             payload.get("operator_name", ""), payload.get("reason", ""),
             json.dumps(payload.get("payload", {}), ensure_ascii=False),
             payload.get("request_id", ""), payload.get("idempotency_key", "")),
        )
        if not key:
            return None
        row = db.execute(
            "SELECT * FROM payroll_events WHERE idempotency_key=? ORDER BY id LIMIT 1",
            (key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_export(export_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT " + PayrollSettlementRepository.EXPORT_METADATA_COLUMNS +
            " FROM payroll_export_batches WHERE id=?", (export_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_export_content(export_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT csv_content_blob FROM payroll_export_batches WHERE id=?",
            (export_id,),
        ).fetchone()
        return bytes(row["csv_content_blob"]) if row else None

    @staticmethod
    def get_export_by_key(idempotency_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT " + PayrollSettlementRepository.EXPORT_METADATA_COLUMNS +
            " FROM payroll_export_batches WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_exports(settlement_id, db=None):
        db = resolve_db(db)
        return [dict(row) for row in db.execute(
            "SELECT id,settlement_id,export_version,status,row_count,total_cents,"
            "content_sha256,idempotency_key,created_by_name,created_at,superseded_at,"
            "superseded_by_export_id FROM payroll_export_batches "
            "WHERE settlement_id=? ORDER BY export_version DESC",
            (settlement_id,),
        ).fetchall()]

    @staticmethod
    def export_items(export_id, db=None):
        db = resolve_db(db)
        return [dict(row) for row in db.execute(
            "SELECT * FROM payroll_export_items WHERE export_batch_id=? ORDER BY sequence_no",
            (export_id,),
        ).fetchall()]

    @staticmethod
    def get_receipt_by_key(idempotency_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_receipt_batches WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_receipt_by_digest(export_id, content_sha256, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_receipt_batches "
            "WHERE export_batch_id=? AND content_sha256=?",
            (export_id, content_sha256),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_receipt_batches(export_id, db=None):
        db = resolve_db(db)
        batches = [dict(row) for row in db.execute(
            "SELECT * FROM payroll_receipt_batches WHERE export_batch_id=? "
            "ORDER BY id DESC", (export_id,),
        ).fetchall()]
        for batch in batches:
            batch["invalid_items"] = [dict(row) for row in db.execute(
                "SELECT id,row_number,payment_reference,validation_error "
                "FROM payroll_receipt_items WHERE receipt_batch_id=? "
                "AND validation_status='invalid' ORDER BY row_number LIMIT 20",
                (batch["id"],),
            ).fetchall()]
        return batches

    @staticmethod
    def receipt_items(export_id, db=None):
        db = resolve_db(db)
        return [dict(row) for row in db.execute(
            "SELECT item.*,batch.export_batch_id FROM payroll_receipt_items item "
            "JOIN payroll_receipt_batches batch ON batch.id=item.receipt_batch_id "
            "WHERE batch.export_batch_id=? ORDER BY batch.id,item.row_number",
            (export_id,),
        ).fetchall()]

    @staticmethod
    def get_run_by_key(idempotency_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_reconciliation_runs WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_reconciliation_items(run_id, db=None):
        db = resolve_db(db)
        return [dict(row) for row in db.execute(
            "SELECT item.*,export_item.employee_no_snapshot,"
            "export_item.employee_name_snapshot "
            "FROM payroll_reconciliation_items item "
            "LEFT JOIN payroll_export_items export_item ON export_item.id=item.export_item_id "
            "WHERE item.reconciliation_run_id=? ORDER BY item.id", (run_id,),
        ).fetchall()]

    @staticmethod
    def list_resolutions(settlement_id, export_id, db=None):
        db = resolve_db(db)
        return [dict(row) for row in db.execute(
            "SELECT resolution.*,item.payment_reference,item.difference_type,"
            "run.export_batch_id FROM payroll_reconciliation_resolutions resolution "
            "JOIN payroll_reconciliation_items item "
            "ON item.id=resolution.reconciliation_item_id "
            "JOIN payroll_reconciliation_runs run ON run.id=item.reconciliation_run_id "
            "WHERE run.settlement_id=? AND run.export_batch_id=? ORDER BY resolution.id",
            (settlement_id, export_id),
        ).fetchall()]

    @staticmethod
    def latest_run(settlement_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_reconciliation_runs WHERE settlement_id=? "
            "ORDER BY run_version DESC LIMIT 1", (settlement_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def run_detail(run_id, db=None):
        db = resolve_db(db)
        run = db.execute(
            "SELECT * FROM payroll_reconciliation_runs WHERE id=?", (run_id,)
        ).fetchone()
        if not run:
            return None
        result = dict(run)
        result["items"] = PayrollSettlementRepository.list_reconciliation_items(run_id, db)
        return result

    @staticmethod
    def close_record(settlement_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_close_records WHERE settlement_id=?",
            (settlement_id,),
        ).fetchone()
        return dict(row) if row else None
