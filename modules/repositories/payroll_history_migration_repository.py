"""SQL access used by the controlled historical payroll cutover."""

from modules.repositories.context import resolve_db


class PayrollHistoryMigrationRepository:
    @staticmethod
    def table_names(db=None):
        db = resolve_db(db)
        return {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    @staticmethod
    def source_records(period_start, period_end, db=None):
        db = resolve_db(db)
        return [
            dict(row)
            for row in db.execute(
                """
                SELECT wr.id AS work_record_id,wr.type AS work_type,wr.quantity,
                       wr.created_at AS work_recorded_at,wr.process_id,wr.user_id,
                       o.id AS order_id,o.order_no,o.route_id,
                       r.id AS existing_resolution_id,r.resolution_method AS existing_method,
                       r.policy_code AS existing_policy_code,
                       r.price_version_id AS existing_price_version_id
                FROM work_records wr
                LEFT JOIN orders o ON o.id=wr.order_id
                LEFT JOIN payroll_work_price_resolutions r ON r.work_record_id=wr.id
                WHERE wr.status='approved' AND wr.type IN ('normal','rework')
                  AND wr.created_at>=? AND wr.created_at<?
                ORDER BY wr.created_at,wr.id
                """,
                (period_start, period_end),
            ).fetchall()
        ]

    @staticmethod
    def current_price_candidates(route_id, process_id, db=None):
        db = resolve_db(db)
        return [
            dict(row)
            for row in db.execute(
                """
                SELECT v.* FROM route_price_versions v
                JOIN route_prices legacy ON legacy.id=v.legacy_route_price_id
                WHERE v.route_id=? AND v.process_id=? AND v.status='approved'
                  AND legacy.status='active'
                ORDER BY v.id
                """,
                (route_id, process_id),
            ).fetchall()
        ]

    @staticmethod
    def preparer(preparer_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT id,name,username FROM users WHERE id=?", (preparer_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def legacy_batch(payroll_month, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_batches WHERE payroll_month=? AND version=1 "
            "AND legacy_imported=1 ORDER BY id LIMIT 1",
            (payroll_month,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def migration_manifest(payroll_month, policy_code, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_migration_manifests "
            "WHERE payroll_month=? AND policy_code=?",
            (payroll_month, policy_code),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_migration_manifest(payload, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            """
            INSERT INTO payroll_migration_manifests (
                payroll_month,policy_code,period_start,period_end,
                source_record_count,resolved_record_count,unresolved_record_count,
                records_json,manifest_sha256,prepared_by,prepared_by_name,batch_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload["payroll_month"], payload["policy_code"],
                payload["period_start"], payload["period_end"],
                payload["source_record_count"], payload["resolved_record_count"],
                payload["unresolved_record_count"], payload["records_json"],
                payload["manifest_sha256"], payload["prepared_by"],
                payload["prepared_by_name"], payload.get("batch_id"),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def migration_manifest_by_id(manifest_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_migration_manifests WHERE id=?",
            (manifest_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def event_exists(idempotency_key, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT 1 FROM payroll_events WHERE idempotency_key=? LIMIT 1",
            (idempotency_key,),
        ).fetchone() is not None

    @staticmethod
    def reclassify_exception(batch_id, work_record_id, exception_type, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            """
            UPDATE payroll_exceptions
            SET exception_type=?,updated_at=datetime('now','localtime')
            WHERE batch_id=? AND work_record_id=? AND status='pending'
            """,
            (exception_type, batch_id, work_record_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(
                f"工资异常重分类失败: batch={batch_id}, work_record={work_record_id}"
            )
