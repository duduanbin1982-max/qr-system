"""
qr-system — ScanRepository（扫码报工数据访问层）
"""
import sqlite3

from modules.repositories.context import resolve_db
from modules.process_fact_projection import (
    capture_process_fact_binding,
    compatible_process_projection,
    warn_legacy_fact_rows,
)
from modules.approval_policy_projection import effective_snapshot as project_effective_snapshot


def _has_column(db, table, column):
    return any(row[1] == column for row in db.execute(f"PRAGMA table_info({table})"))


class ScanRepository:
    """扫码报工数据访问 — 封装扫码流程中的数据库操作。"""

    @staticmethod
    def find_order_by_no(order_no, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM orders WHERE order_no = ? AND deleted_at IS NULL",
            (order_no,)
        ).fetchone()

    @staticmethod
    def get_order(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL",
            (order_id,)
        ).fetchone()

    @staticmethod
    def get_order_for_stock(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT o.id, o.order_no, o.product_code, o.product_name, o.quantity, p.spec "
            "FROM orders o LEFT JOIN order_product_links opl ON opl.order_id = o.id "
            "LEFT JOIN products p ON p.id = opl.product_id "
            "WHERE o.id = ?",
            (order_id,)
        ).fetchone()

    @staticmethod
    def get_order_quantity(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT quantity FROM orders WHERE id = ?",
            (order_id,)
        ).fetchone()

    @staticmethod
    def get_order_processes(order_id, db=None):
        db = resolve_db(db)
        process_name, version_join, _ = compatible_process_projection(
            db, "op", "process_version", "p"
        )
        rows = db.execute(
            "SELECT op.*," + process_name + " AS process_name "
            "FROM order_processes op JOIN processes p ON op.process_id=p.id "
            + version_join
            + "WHERE op.order_id=? ORDER BY op.seq_order",
            (order_id,)
        ).fetchall()
        warn_legacy_fact_rows("order_processes", rows)
        return rows

    @staticmethod
    def get_item_by_serial(serial_no, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM product_items WHERE serial_no = ?", (serial_no,)
        ).fetchone()

    @staticmethod
    def get_item_by_position(order_id, position_no, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM product_items WHERE order_id = ? AND position_no = ?",
            (order_id, position_no)
        ).fetchone()

    @staticmethod
    def get_items_by_order(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM product_items WHERE order_id = ? ORDER BY position_no",
            (order_id,)
        ).fetchall()

    @staticmethod
    def get_order_process(order_id, process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id)
        ).fetchone()

    @staticmethod
    def get_work_fact_binding(order_id, process_id, db=None):
        """Return the exact order binding inherited by a new work fact."""
        db = resolve_db(db)
        policy_fields = (
            ",op.approval_policy_revision_id,op.approval_policy_source "
            if _has_column(db, "order_processes", "approval_policy_revision_id")
            else ",NULL AS approval_policy_revision_id,'legacy_unbound' AS approval_policy_source "
        )
        return db.execute(
            "SELECT op.process_id,op.process_version_id,op.process_code_snapshot,"
            "op.process_name_snapshot,op.process_category_snapshot,"
            "order_row.route_id,order_row.route_version_id,"
            "order_row.route_name_snapshot "
            + policy_fields +
            "FROM order_processes op JOIN orders order_row ON order_row.id=op.order_id "
            "WHERE op.order_id=? AND op.process_id=?",
            (order_id, process_id),
        ).fetchone()

    @staticmethod
    def get_user_position(user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT user.position_id,COALESCE(position.name,'') AS position_name "
            "FROM users user LEFT JOIN positions position "
            "ON position.id=user.position_id WHERE user.id=?",
            (user_id,),
        ).fetchone()

    @staticmethod
    def database_now(db=None):
        db = resolve_db(db)
        return db.execute("SELECT datetime('now','localtime')").fetchone()[0]

    @staticmethod
    def find_order_process_id(order_id, process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id)
        ).fetchone()

    @staticmethod
    def get_prev_incomplete_processes(order_id, current_seq, db=None):
        db = resolve_db(db)
        process_name, version_join, version_id = compatible_process_projection(
            db, "op", "process_version", "p"
        )
        rows = db.execute(
            "SELECT op.process_id," + version_id + " AS process_version_id,op.seq_order," + process_name
            + " AS process_name "
            "FROM order_processes op "
            "JOIN processes p ON op.process_id = p.id "
            + version_join
            + "WHERE op.order_id = ? AND op.seq_order < ? "
            "AND (op.completed IS NULL OR op.completed = 0) "
            "ORDER BY op.seq_order",
            (order_id, current_seq)
        ).fetchall()
        warn_legacy_fact_rows("order_processes", rows)
        return rows

    @staticmethod
    def get_prev_order_process(order_id, current_seq, db=None):
        db = resolve_db(db)
        process_name, version_join, _ = compatible_process_projection(
            db, "op", "process_version", "p"
        )
        row = db.execute(
            "SELECT op.*," + process_name + " AS process_name FROM order_processes op "
            "JOIN processes p ON op.process_id = p.id "
            + version_join
            + "WHERE op.order_id = ? AND op.seq_order < ? "
            "ORDER BY op.seq_order DESC LIMIT 1",
            (order_id, current_seq)
        ).fetchone()
        warn_legacy_fact_rows("order_processes", [row] if row else [])
        return row

    @staticmethod
    def find_next_process(order_id, current_seq, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT op.process_id FROM order_processes op WHERE op.order_id = ? AND op.seq_order > ? "
            "ORDER BY op.seq_order LIMIT 1",
            (order_id, current_seq)
        ).fetchone()

    @staticmethod
    def get_last_process_seq(order_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT MAX(seq_order) as max_seq FROM order_processes WHERE order_id = ?",
            (order_id,)
        ).fetchone()
        return row["max_seq"] if row else None

    @staticmethod
    def is_last_process(order_id, process_id, db=None):
        db = resolve_db(db)
        max_row = db.execute(
            "SELECT MAX(seq_order) as max_seq FROM order_processes WHERE order_id = ?",
            (order_id,)
        ).fetchone()
        if not max_row or max_row["max_seq"] is None:
            return False
        cur_row = db.execute(
            "SELECT seq_order FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id)
        ).fetchone()
        return cur_row is not None and cur_row["seq_order"] == max_row["max_seq"]

    @staticmethod
    def get_work_records(order_id, db=None, limit=None):
        db = resolve_db(db)
        if limit:
            return db.execute(
                "SELECT wr.*, u.name as worker_name FROM work_records wr "
                "LEFT JOIN users u ON wr.user_id = u.id "
                "WHERE wr.order_id = ? ORDER BY wr.created_at DESC LIMIT ?",
                (order_id, limit)
            ).fetchall()
        return db.execute(
            "SELECT wr.*, u.name as worker_name FROM work_records wr "
            "LEFT JOIN users u ON wr.user_id = u.id "
            "WHERE wr.order_id = ? ORDER BY wr.created_at DESC",
            (order_id,)
        ).fetchall()

    @staticmethod
    def get_user_order_report(order_id, user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM work_records WHERE order_id = ? AND user_id = ? AND type = 'normal'",
            (order_id, user_id)
        ).fetchone()

    @staticmethod
    def get_process_name(process_id, db=None):
        db = resolve_db(db)
        row = db.execute("SELECT name FROM processes WHERE id = ?", (process_id,)).fetchone()
        return row["name"] if row else "\u672a\u77e5\u5de5\u5e8f"

    @staticmethod
    def find_duplicate_normal_report(order_id, process_id, serial_no, user_id, db=None):
        db = resolve_db(db)
        if serial_no:
            return db.execute(
                "SELECT id FROM work_records WHERE order_id = ? AND process_id = ? "
                "AND serial_no = ? AND type = 'normal' AND status != 'rejected'",
                (order_id, process_id, serial_no)
            ).fetchone()
        return db.execute(
            "SELECT id FROM work_records WHERE order_id = ? AND process_id = ? "
            "AND user_id = ? AND type = 'normal' AND status != 'rejected'",
            (order_id, process_id, user_id)
        ).fetchone()

    @staticmethod
    def find_duplicate_defect_report(order_id, process_id, user_id, report_type, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM work_records WHERE order_id = ? AND process_id = ? "
            "AND user_id = ? AND type = ? "
            "AND created_at > datetime('now', '-10 seconds')",
            (order_id, process_id, user_id, report_type)
        ).fetchone()

    @staticmethod
    def find_approval_config(process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM approval_config WHERE process_id = ? AND require_approval = 1",
            (process_id,)
        ).fetchone()

    @staticmethod
    def insert_report_work_record(
        order_id,
        process_id,
        user_id,
        report_type,
        quantity,
        remark,
        work_status,
        serial_no,
        report_source="standard",
        actual_completed_at=None,
        backfill_reason="",
        submit_position_id=None,
        submit_position_name="",
        submit_position_version_id=None,
        fact_binding=None,
        db=None,
    ):
        db = resolve_db(db)
        binding = dict(fact_binding or {})
        if not _has_column(db, "work_records", "approval_policy_revision_id"):
            binding.pop("approval_policy_revision_id", None)
            binding.pop("approval_policy_source", None)
            cur = db.execute(
                "INSERT INTO work_records "
                "(order_id, process_id, user_id, type, quantity, remark, status, serial_no, "
                "report_source, actual_completed_at, backfill_reason, submit_position_id, "
                "submit_position_name, submit_position_version_id, process_version_id, "
                "process_code_snapshot, process_name_snapshot, process_category_snapshot, "
                "route_id, route_version_id, route_name_snapshot, version_binding_source) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (order_id, process_id, user_id, report_type, quantity, remark, work_status,
                 serial_no, report_source, actual_completed_at, backfill_reason,
                 submit_position_id, submit_position_name, submit_position_version_id,
                 binding.get("process_version_id"), binding.get("process_code_snapshot", ""),
                 binding.get("process_name_snapshot", ""), binding.get("process_category_snapshot", ""),
                 binding.get("route_id"), binding.get("route_version_id"), binding.get("route_name_snapshot", ""),
                 binding.get("version_binding_source", "captured" if binding.get("process_version_id") else "")),
            )
            return cur.lastrowid
        cur = db.execute(
            "INSERT INTO work_records "
            "(order_id, process_id, user_id, type, quantity, remark, status, serial_no, "
            "report_source, actual_completed_at, backfill_reason, "
            "submit_position_id, submit_position_name, submit_position_version_id, "
            "process_version_id, "
            "process_code_snapshot, process_name_snapshot, process_category_snapshot, "
            "route_id, route_version_id, route_name_snapshot, version_binding_source, "
            "approval_policy_revision_id, approval_policy_source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                order_id,
                process_id,
                user_id,
                report_type,
                quantity,
                remark,
                work_status,
                serial_no,
                report_source,
                actual_completed_at,
                backfill_reason,
                submit_position_id,
                submit_position_name,
                submit_position_version_id,
                binding.get("process_version_id"),
                binding.get("process_code_snapshot", ""),
                binding.get("process_name_snapshot", ""),
                binding.get("process_category_snapshot", ""),
                binding.get("route_id"),
                binding.get("route_version_id"),
                binding.get("route_name_snapshot", ""),
                binding.get(
                    "version_binding_source",
                    "captured" if binding.get("process_version_id") else "",
                ),
                binding.get("approval_policy_revision_id"),
                binding.get("approval_policy_source", "legacy_snapshot"),
            ),
        )
        return cur.lastrowid

    @staticmethod
    def list_serial_report_states(order_id, serial_no, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT process_id, status, report_source FROM work_records "
            "WHERE order_id = ? AND serial_no = ? AND type = 'normal' "
            "AND status != 'rejected' ORDER BY id DESC",
            (order_id, serial_no),
        ).fetchall()

    @staticmethod
    def list_approved_serial_work_records(order_id, serial_no, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT wr.id, wr.order_id, wr.process_id, wr.user_id, wr.serial_no, "
            "wr.quantity, wr.report_source, wr.actual_completed_at, wr.backfill_reason, "
            "wr.submit_position_id, wr.submit_position_name, "
            "wr.submit_position_version_id, "
            "COALESCE(u.name, u.username, '') AS user_name "
            "FROM work_records wr LEFT JOIN users u ON u.id = wr.user_id "
            "LEFT JOIN order_processes op ON op.order_id = wr.order_id "
            "AND op.process_id = wr.process_id "
            "WHERE wr.order_id = ? AND wr.serial_no = ? AND wr.type = 'normal' "
            "AND wr.status = 'approved' ORDER BY op.seq_order, wr.id",
            (order_id, serial_no),
        ).fetchall()

    @staticmethod
    def has_approved_serial_backfill(order_id, serial_no, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT 1 FROM work_records WHERE order_id = ? AND serial_no = ? "
            "AND type = 'normal' AND status = 'approved' "
            "AND report_source = 'serial_backfill' LIMIT 1",
            (order_id, serial_no),
        ).fetchone() is not None

    @staticmethod
    def find_first_unreported_serial_process(order_id, serial_no, db=None):
        db = resolve_db(db)
        process_name, version_join, _ = compatible_process_projection(
            db, "op", "process_version", "p"
        )
        row = db.execute(
            "SELECT op.*," + process_name + " AS process_name FROM order_processes op "
            "JOIN processes p ON p.id = op.process_id "
            + version_join
            + "WHERE op.order_id = ? AND NOT EXISTS ("
            "SELECT 1 FROM work_records wr WHERE wr.order_id = op.order_id "
            "AND wr.process_id = op.process_id AND wr.serial_no = ? "
            "AND wr.type = 'normal' AND wr.status = 'approved') "
            "ORDER BY op.seq_order, op.id LIMIT 1",
            (order_id, serial_no),
        ).fetchone()
        warn_legacy_fact_rows("order_processes", [row] if row else [])
        return row

    @staticmethod
    def insert_approval_record(work_record_id, db=None):
        db = resolve_db(db)
        existing = db.execute(
            "SELECT id FROM approval_records WHERE work_record_id=? AND status='pending'",
            (work_record_id,),
        ).fetchone()
        if existing:
            return existing["id"]
        if not _has_column(db, "approval_records", "approval_policy_revision_id"):
            cur = db.execute(
                "INSERT INTO approval_records (work_record_id,status) VALUES (?, 'pending')",
                (work_record_id,),
            )
            return cur.lastrowid
        work_record = db.execute(
            "SELECT process_id,approval_policy_revision_id FROM work_records WHERE id=?", (work_record_id,)
        ).fetchone()
        revision_id = work_record["approval_policy_revision_id"] if work_record else None
        if revision_id:
            snapshot = {"require_approval": True, "approval_level": 1, "roles": [], "source": "bound_revision"}
            if _has_column(db, "approval_policy_revisions", "id"):
                revision = db.execute(
                    "SELECT require_approval,approval_level FROM approval_policy_revisions WHERE id=?",
                    (revision_id,),
                ).fetchone()
                if revision:
                    snapshot.update({"require_approval": bool(revision[0]), "approval_level": revision[1]})
        else:
            snapshot, revision_id = project_effective_snapshot(
                work_record["process_id"] if work_record else None, db=db
            )
        import json
        cur = db.execute(
            "INSERT INTO approval_records "
            "(work_record_id,status,approval_policy_revision_id,policy_source,policy_snapshot_json) "
            "VALUES (?, 'pending', ?, ?, ?)",
            (work_record_id, revision_id, snapshot.get("source", "default"),
             json.dumps(snapshot, ensure_ascii=False, sort_keys=True)),
        )
        return cur.lastrowid

    @staticmethod
    def update_order_process_completed(order_id, process_id, completed, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE order_processes SET completed = ?, "
            "status = CASE "
            "WHEN ? >= (SELECT quantity FROM orders WHERE id = ?) THEN 'completed' "
            "WHEN ? > 0 THEN 'in_progress' "
            "ELSE status END "
            "WHERE order_id = ? AND process_id = ?",
            (completed, completed, order_id, completed, order_id, process_id),
        )

    @staticmethod
    def advance_product_item(item_id, next_process_id, version, db=None):
        db = resolve_db(db)
        return db.execute(
            "UPDATE product_items SET current_process_id = ?, status = 'in_progress', version = version + 1 "
            "WHERE id = ? AND version = ?",
            (next_process_id, item_id, version),
        )

    @staticmethod
    def set_product_item_current_process(item_id, process_id, version, db=None):
        db = resolve_db(db)
        return db.execute(
            "UPDATE product_items SET current_process_id = ?, status = 'in_progress', "
            "completed_at = NULL, version = version + 1 WHERE id = ? AND version = ?",
            (process_id, item_id, version),
        )

    @staticmethod
    def complete_product_item(item_id, version, db=None):
        db = resolve_db(db)
        return db.execute(
            "UPDATE product_items SET current_process_id = NULL, status = 'completed', "
            "completed_at = datetime('now','localtime'), version = version + 1 WHERE id = ? AND version = ?",
            (item_id, version),
        )

    @staticmethod
    def refresh_order_completion(order_id, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE orders SET completed = (SELECT COUNT(*) FROM product_items WHERE order_id = ? AND status = 'completed'), "
            "completed_at = NULL, updated_at = datetime('now','localtime'), "
            "status = 'producing' WHERE id = ?",
            (order_id, order_id),
        )

    @staticmethod
    def count_completed_items(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) as cnt FROM product_items WHERE order_id = ? AND status = 'completed'",
            (order_id,)
        ).fetchone()["cnt"]

    @staticmethod
    def find_inventory_by_model(product_code, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, product_model, product_name, quantity FROM inventory WHERE product_model = ?",
            (product_code,)
        ).fetchone()

    @staticmethod
    def complete_order(order_id, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE orders SET status = 'completed', "
            "completed_at = COALESCE(NULLIF(completed_at, ''), datetime('now','localtime')), "
            "updated_at = datetime('now','localtime') WHERE id = ?",
            (order_id,),
        )

    @staticmethod
    def insert_scrap_record(order_id, process_id, user_id, quantity, reason, db=None):
        db = resolve_db(db)
        binding = capture_process_fact_binding(
            db, order_id=order_id, process_id=process_id
        )
        cursor = db.execute(
            "INSERT INTO scrap_records (order_id,process_id,user_id,quantity,reason,"
            "process_version_id,process_code_snapshot,process_name_snapshot,"
            "process_category_snapshot,route_id,route_version_id,route_name_snapshot,"
            "version_binding_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                order_id, process_id, user_id, quantity, reason,
                binding["process_version_id"], binding["process_code_snapshot"],
                binding["process_name_snapshot"], binding["process_category_snapshot"],
                binding["route_id"], binding["route_version_id"],
                binding["route_name_snapshot"], binding["version_binding_source"],
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def update_order_process_scrapped(order_id, process_id, scrapped, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE order_processes SET scrapped = ? WHERE order_id = ? AND process_id = ?",
            (scrapped, order_id, process_id),
        )

    @staticmethod
    def refresh_order_scrapped(order_id, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE orders SET scrapped = (SELECT COALESCE(SUM(scrapped),0) FROM order_processes WHERE order_id = ?), "
            "updated_at = datetime('now','localtime') WHERE id = ?",
            (order_id, order_id),
        )

    @staticmethod
    def insert_rework_record(order_id, process_id, user_id, quantity, reason, db=None):
        db = resolve_db(db)
        binding = capture_process_fact_binding(
            db, order_id=order_id, process_id=process_id
        )
        db.execute(
            "INSERT INTO rework_records (order_id,process_id,user_id,quantity,reason,"
            "process_version_id,process_code_snapshot,process_name_snapshot,"
            "process_category_snapshot,route_id,route_version_id,route_name_snapshot,"
            "version_binding_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                order_id, process_id, user_id, quantity, reason,
                binding["process_version_id"], binding["process_code_snapshot"],
                binding["process_name_snapshot"], binding["process_category_snapshot"],
                binding["route_id"], binding["route_version_id"],
                binding["route_name_snapshot"], binding["version_binding_source"],
            ),
        )

    @staticmethod
    def update_order_process_rework(order_id, process_id, rework, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE order_processes SET rework = ? WHERE order_id = ? AND process_id = ?",
            (rework, order_id, process_id),
        )

    @staticmethod
    def refresh_order_rework(order_id, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE orders SET rework = (SELECT COALESCE(SUM(rework),0) FROM order_processes WHERE order_id = ?), "
            "updated_at = datetime('now','localtime') WHERE id = ?",
            (order_id, order_id),
        )

    @staticmethod
    def find_or_create_inventory(product_code, product_name, order_id=None, specification="", db=None):
        db = resolve_db(db)
        if order_id:
            inv = db.execute(
                "SELECT id FROM inventory WHERE product_model = ? AND order_id = ? "
                "AND deleted_at IS NULL",
                (product_code, order_id),
            ).fetchone()
            if inv:
                return inv["id"]
        try:
            cur = db.execute(
                "INSERT INTO inventory (product_model, product_name, quantity, order_id, specification) "
                "VALUES (?, ?, 0, ?, ?)",
                (product_code, product_name or product_code, order_id, specification or ""),
            )
        except sqlite3.IntegrityError as exc:
            # Compatibility for databases created by the former global UNIQUE
            # product_model definition. New databases allow one row per order.
            if "inventory.product_model" not in str(exc):
                raise
            existing = db.execute(
                "SELECT id FROM inventory WHERE product_model = ? "
                "AND deleted_at IS NULL ORDER BY id LIMIT 1",
                (product_code,),
            ).fetchone()
            if not existing:
                raise
            return existing["id"]
        return cur.lastrowid

    @staticmethod
    def find_inbound_inventory_log(order_id, serial_no=None, db=None):
        db = resolve_db(db)
        if serial_no:
            return db.execute(
                "SELECT id FROM inventory_logs WHERE order_id = ? AND type = 'in' AND remark LIKE ?",
                (order_id, "%" + serial_no + "%")
            ).fetchone()
        return db.execute(
            "SELECT id FROM inventory_logs WHERE order_id = ? AND type = 'in'",
            (order_id,)
        ).fetchone()

    @staticmethod
    def order_has_process_in_scope(order_id, process_ids, db=None):
        db = resolve_db(db)
        placeholders = ",".join("?" for _ in process_ids)
        row = db.execute(
            f"SELECT 1 FROM order_processes WHERE order_id = ? AND process_id IN ({placeholders})",
            [order_id] + process_ids
        ).fetchone()
        return row is not None

    @staticmethod
    def insert_work_record(data, db=None):
        db = resolve_db(db)
        binding = ScanRepository.get_work_fact_binding(
            data["order_id"], data["process_id"], db=db
        )
        if binding is None or binding["process_version_id"] is None:
            raise ValueError("订单工序缺少版本绑定，禁止报工")
        return ScanRepository.insert_report_work_record(
            data["order_id"],
            data["process_id"],
            data["user_id"],
            data.get("type", "normal"),
            data.get("quantity", 1),
            data.get("remark", ""),
            "approved",
            data.get("serial_no", ""),
            fact_binding=binding,
            db=db,
        )


    @staticmethod
    def auto_inbound_item(order_id, db=None):
        """自动入库：检查订单最后一道工序是否全部完成。"""
        db = resolve_db(db)
        items = db.execute(
            "SELECT * FROM product_items WHERE order_id = ? AND status = 'in_progress'",
            (order_id,)
        ).fetchall()
        return len(items)

    @staticmethod
    def find_process_name(process_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT name FROM processes WHERE id=?", (process_id,)).fetchone()

    @staticmethod
    def count_approved_normal_work_records(order_id, process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) FROM work_records "
            "WHERE order_id=? AND process_id=? AND type='normal' AND status='approved'",
            (order_id, process_id),
        ).fetchone()[0]

    @staticmethod
    def find_first_article_inspection(order_id, process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM quality_inspections "
            "WHERE order_id=? AND process_id=? AND inspection_type='first_article'",
            (order_id, process_id),
        ).fetchone()

    @staticmethod
    def find_order_status(order_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
