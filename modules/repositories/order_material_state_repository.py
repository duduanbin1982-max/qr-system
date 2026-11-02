"""Persistence queries for immutable order material state evidence."""


class OrderMaterialStateRepository:
    """Keep state SQL on the caller's existing SQLite transaction."""

    @staticmethod
    def event_records(event_id, *, db):
        live = [
            dict(row) for row in db.execute(
                "SELECT * FROM audit_logs WHERE event_id=?", (event_id,)
            ).fetchall()
        ]
        archived = [
            dict(row) for row in db.execute(
                "SELECT event_id,payload FROM audit_log_archive WHERE event_id=?",
                (event_id,),
            ).fetchall()
        ]
        return live, archived

    @staticmethod
    def find_order(order_id, *, db):
        row = db.execute(
            "SELECT id,quantity FROM orders WHERE id=?", (order_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def snapshot_rows(order_id, *, db):
        return [
            dict(row) for row in db.execute(
                "SELECT material_id,process_id,quantity_per_unit "
                "FROM order_materials WHERE order_id=? ORDER BY id",
                (order_id,),
            ).fetchall()
        ]

    @staticmethod
    def has_prior_approved_normal_report(order_id, work_record_id, *, db):
        return db.execute(
            "SELECT 1 FROM work_records WHERE order_id=? AND type='normal' "
            "AND status='approved' AND (? IS NULL OR id<>?) LIMIT 1",
            (order_id, work_record_id, work_record_id),
        ).fetchone() is not None

    @staticmethod
    def consumptions(order_id, *, db):
        return [
            dict(row) for row in db.execute(
                "SELECT * FROM material_consumptions WHERE order_id=? ORDER BY id",
                (order_id,),
            ).fetchall()
        ]

    @staticmethod
    def source_logs(order_id, *, db):
        """Include every original source and reversals, without hiding duplicates."""
        return [
            dict(row) for row in db.execute(
                "SELECT ml.* FROM material_logs ml "
                "JOIN material_consumptions mc ON mc.id=ml.source_id "
                "WHERE mc.order_id=? AND ml.source_type IN "
                "('consumption','auto_consumption','order_common_consumption',"
                "'consumption_reversal') ORDER BY ml.id",
                (order_id,),
            ).fetchall()
        ]

    @staticmethod
    def logs_by_ids(log_ids, *, db):
        if not log_ids:
            return []
        placeholders = ",".join("?" for _ in log_ids)
        return [
            dict(row) for row in db.execute(
                f"SELECT * FROM material_logs WHERE id IN ({placeholders}) ORDER BY id",
                tuple(log_ids),
            ).fetchall()
        ]
