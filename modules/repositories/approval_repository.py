"""Persistence operations for approval records and approval configuration."""
from modules.repositories.context import resolve_db
from modules.process_fact_projection import (
    process_value_sql,
    process_version_join,
    warn_legacy_fact_rows,
)


class ApprovalRepository:
    """Approval persistence gateway."""

    # ============================================================
    # Queries
    # ============================================================

    @staticmethod
    def count_by_status(status_condition, db=None):
        """Count pending records or processed history records."""
        db = resolve_db(db)
        op = '=' if status_condition == 'pending' else '!='
        return db.execute(f'''
            SELECT COUNT(*) FROM approval_records ar
            LEFT JOIN work_records wr ON ar.work_record_id = wr.id
            LEFT JOIN orders o ON wr.order_id = o.id
            WHERE ar.status {op} 'pending' AND (o.deleted_at IS NULL OR o.id IS NULL)
        ''').fetchone()[0]

    @staticmethod
    def find_by_status(status_condition, limit, offset, db=None):
        """Return approval records with linked work, order, process, and user data."""
        db = resolve_db(db)
        op = '=' if status_condition == 'pending' else '!='
        order_column = 'ar.created_at' if status_condition == 'pending' else 'COALESCE(ar.processed_at, ar.created_at)'
        process_name = process_value_sql("wr", "process_version", "p")
        rows = db.execute(
            "SELECT ar.*,o.order_no,wr.process_id,wr.process_version_id,"
            + process_name + " AS process_name,u.name AS worker_name,wr.quantity,"
            "wr.serial_no,wr.report_source,wr.actual_completed_at,wr.backfill_reason,"
            "wr.submit_position_id,wr.submit_position_name,wr.remark "
            "FROM approval_records ar "
            "LEFT JOIN work_records wr ON ar.work_record_id=wr.id "
            "LEFT JOIN orders o ON wr.order_id=o.id "
            "LEFT JOIN processes p ON wr.process_id=p.id "
            + process_version_join("wr", "process_version")
            + "LEFT JOIN users u ON wr.user_id=u.id "
            f"WHERE ar.status {op} 'pending' AND (o.deleted_at IS NULL OR o.id IS NULL) "
            f"ORDER BY {order_column} DESC,ar.id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        warn_legacy_fact_rows("work_records", rows)
        return rows

    @staticmethod
    def find_by_id(record_id, db=None):
        """Find one approval record by ID."""
        db = resolve_db(db)
        return db.execute(
            'SELECT * FROM approval_records WHERE id = ?', (record_id,)
        ).fetchone()


    @staticmethod
    def find_work_record(wr_id, db=None):
        """查询报工记录，包含多级审批所需的 process_id。"""
        db = resolve_db(db)
        return db.execute(
            "SELECT wr.id, wr.quantity, wr.order_id, wr.status, wr.process_id, "
                "wr.user_id, wr.serial_no, wr.report_source, wr.actual_completed_at, "
                "wr.backfill_reason, wr.submit_position_id, wr.submit_position_name, wr.remark, "
            "COALESCE(u.name, u.username, '') AS user_name "
            "FROM work_records wr LEFT JOIN users u ON u.id = wr.user_id WHERE wr.id = ?",
            (wr_id,),
        ).fetchone()

    @staticmethod
    def find_order(oid, db=None):
        """Find the order required for approval invariant checks."""
        db = resolve_db(db)
        return db.execute(
            'SELECT quantity, completed, deleted_at FROM orders WHERE id = ?', (oid,)
        ).fetchone()

    @staticmethod
    def find_order_process(order_id, process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT completed FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id),
        ).fetchone()

    # ============================================================
    # Mutations
    # ============================================================

    @staticmethod
    def approve(record_id, approver_id, approver_name, comment, db=None):
        """Mark an approval record approved and store approver details."""
        db = resolve_db(db)
        cur = db.execute('''
            UPDATE approval_records
            SET status = 'approved', approver_id = ?, approver_name = ?,
                comment = ?, processed_at = datetime('now','localtime')
            WHERE id = ? AND status = 'pending'
        ''', (approver_id, approver_name, comment, record_id))
        return cur.rowcount

    @staticmethod
    def reject(record_id, approver_id, approver_name, comment, db=None):
        """Mark an approval record rejected and store approver details."""
        db = resolve_db(db)
        cur = db.execute('''
            UPDATE approval_records
            SET status = 'rejected', approver_id = ?, approver_name = ?,
                comment = ?, processed_at = datetime('now','localtime')
            WHERE id = ? AND status = 'pending'
        ''', (approver_id, approver_name, comment, record_id))
        return cur.rowcount

    @staticmethod
    def update_work_record_status(wr_id, status, db=None):
        """Update the linked work-report status."""
        db = resolve_db(db)
        cur = db.execute(
            'UPDATE work_records SET status = ? WHERE id = ? AND status = ?',
            (status, wr_id, 'pending'),
        )
        return cur.rowcount

    @staticmethod
    def advance_level(record_id, approver_id, approver_name, comment, next_level, current_level, db=None):
        """Advance approval to next level without finalizing."""
        db = resolve_db(db)
        cur = db.execute("""
            UPDATE approval_records
            SET current_level = ?, approver_id = ?, approver_name = ?,
                comment = ?, processed_at = datetime('now','localtime')
            WHERE id = ? AND status = 'pending' AND current_level = ?
        """, (next_level, approver_id, approver_name, comment, record_id, current_level))
        return cur.rowcount

    @staticmethod
    def insert_approval_step(approval_record_id, step_level, approver_id, approver_name,
                             approver_role, action, comment, db=None):
        """Append a step-level audit row for approval history."""
        db = resolve_db(db)
        cur = db.execute("""
            INSERT INTO approval_steps (
                approval_record_id, step_level, approver_id, approver_name,
                approver_role, action, comment
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            approval_record_id, step_level, approver_id, approver_name,
            approver_role, action, comment,
        ))
        return cur.lastrowid

    # ============================================================
    # 审批配置
    # ============================================================

    @staticmethod
    def find_all_configs(db=None):
        """返回全部工序及其审批配置。"""
        db = resolve_db(db)
        return db.execute("""
            SELECT ac.id, p.id as process_id, COALESCE(ac.require_approval, 0) as require_approval,
                   COALESCE(ac.approver_role, 'admin') as approver_role,
                   COALESCE(ac.approval_level, 1) as approval_level,
                   COALESCE(ac.approver_role_2, '') as approver_role_2,
                   COALESCE(ac.approver_role_3, '') as approver_role_3,
                   p.name as process_name, p.category
            FROM processes p
            LEFT JOIN approval_config ac ON ac.process_id = p.id
            ORDER BY p.name
        """).fetchall()

    @staticmethod
    def upsert_config(process_id, require_approval, approver_role, approver_role_2, approver_role_3, approval_level, db=None):
        """插入或更新审批配置；关闭审批时删除配置。"""
        db = resolve_db(db)
        existing = db.execute(
            "SELECT id FROM approval_config WHERE process_id = ?", (process_id,)
        ).fetchone()
        if require_approval:
            if existing:
                db.execute(
                    "UPDATE approval_config SET require_approval=?, approver_role=?, approver_role_2=?, approver_role_3=?, approval_level=? WHERE process_id=?",
                    (require_approval, approver_role, approver_role_2, approver_role_3, approval_level, process_id)
                )
            else:
                db.execute(
                    "INSERT INTO approval_config (process_id, require_approval, approver_role, approver_role_2, approver_role_3, approval_level) VALUES (?,?,?,?,?,?)",
                    (process_id, require_approval, approver_role, approver_role_2, approver_role_3, approval_level)
                )
        else:
            # 关闭审批时直接删除，避免保留无效角色配置。
            if existing:
                db.execute("DELETE FROM approval_config WHERE process_id = ?", (process_id,))

    @staticmethod
    def get_approval_stats(db=None):
        """返回审批统计数据。"""
        db = resolve_db(db)
        pending = db.execute("SELECT COUNT(*) FROM approval_records WHERE status='pending'").fetchone()[0]
        avg_row = db.execute("""
            SELECT ROUND(AVG(
                (julianday(processed_at) - julianday(created_at)) * 24
            ), 1) as avg_hours
            FROM approval_records
            WHERE status != 'pending' AND processed_at IS NOT NULL
        """).fetchone()
        pending_over = db.execute("""
            SELECT COUNT(*) FROM approval_records
            WHERE status='pending' AND created_at < datetime('now','localtime','-24 hours')
        """).fetchone()[0]
        total = db.execute("SELECT COUNT(*) FROM approval_records").fetchone()[0]
        return {
            "pending": pending,
            "avg_hours": avg_row["avg_hours"] if avg_row and avg_row["avg_hours"] else 0,
            "pending_over_24h": pending_over,
            "total": total
        }

    @staticmethod
    def find_approval_config(process_id, db=None):
        """查询单个工序的审批配置。"""
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM approval_config WHERE process_id = ?", (process_id,)
        ).fetchone()
