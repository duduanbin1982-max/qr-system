"""Process handoff quality review data access."""
from modules.repositories.context import resolve_db


class HandoffReviewRepository:
    @staticmethod
    def previous_process(order_id, to_process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT prev_op.process_id, prev_op.seq_order, p.name AS process_name "
            "FROM order_processes cur_op "
            "JOIN order_processes prev_op ON prev_op.order_id = cur_op.order_id AND prev_op.seq_order < cur_op.seq_order "
            "JOIN processes p ON p.id = prev_op.process_id "
            "WHERE cur_op.order_id = ? AND cur_op.process_id = ? "
            "ORDER BY prev_op.seq_order DESC LIMIT 1",
            (order_id, to_process_id),
        ).fetchone()

    @staticmethod
    def process_name(process_id, db=None):
        db = resolve_db(db)
        row = db.execute("SELECT name FROM processes WHERE id = ?", (process_id,)).fetchone()
        return row["name"] if row else ""

    @staticmethod
    def latest_previous_work(order_id, from_process_id, serial_no="", db=None):
        db = resolve_db(db)
        if serial_no:
            return db.execute(
                "SELECT wr.*, u.name AS worker_name, u.employee_no "
                "FROM work_records wr JOIN users u ON u.id = wr.user_id "
                "WHERE wr.order_id = ? AND wr.process_id = ? AND wr.serial_no = ? "
                "AND wr.type = 'normal' AND wr.status = 'approved' "
                "ORDER BY wr.created_at DESC, wr.id DESC LIMIT 1",
                (order_id, from_process_id, serial_no),
            ).fetchone()

        contributors = db.execute(
            "SELECT wr.user_id, COUNT(*) AS record_count, COALESCE(SUM(wr.quantity), 0) AS quantity "
            "FROM work_records wr "
            "WHERE wr.order_id = ? AND wr.process_id = ? "
            "AND wr.type = 'normal' AND wr.status = 'approved' "
            "GROUP BY wr.user_id",
            (order_id, from_process_id),
        ).fetchall()
        if len(contributors) != 1:
            return None

        return db.execute(
            "SELECT wr.*, u.name AS worker_name, u.employee_no "
            "FROM work_records wr JOIN users u ON u.id = wr.user_id "
            "WHERE wr.order_id = ? AND wr.process_id = ? "
            "AND wr.type = 'normal' AND wr.status = 'approved' "
            "ORDER BY wr.created_at DESC, wr.id DESC LIMIT 1",
            (order_id, from_process_id),
        ).fetchone()

    @staticmethod
    def latest_evaluator_work(order_id, evaluator_user_id, serial_no="", db=None):
        db = resolve_db(db)
        params = [order_id, evaluator_user_id]
        serial_clause = ""
        if serial_no:
            serial_clause = " AND wr.serial_no = ?"
            params.append(serial_no)
        return db.execute(
            "SELECT wr.* "
            "FROM work_records wr "
            "WHERE wr.order_id = ? AND wr.user_id = ? "
            "AND wr.type = 'normal' AND wr.status = 'approved' "
            + serial_clause +
            " ORDER BY wr.created_at DESC, wr.id DESC LIMIT 1",
            tuple(params),
        ).fetchone()

    @staticmethod
    def existing_review(order_id, from_process_id, to_process_id, evaluator_user_id, serial_no="", db=None):
        db = resolve_db(db)
        if serial_no:
            return db.execute(
                "SELECT * FROM process_handoff_reviews "
                "WHERE order_id = ? AND serial_no = ? AND from_process_id = ? AND to_process_id = ?",
                (order_id, serial_no, from_process_id, to_process_id),
            ).fetchone()
        return db.execute(
            "SELECT * FROM process_handoff_reviews "
            "WHERE order_id = ? AND (serial_no IS NULL OR serial_no = '') "
            "AND from_process_id = ? AND to_process_id = ? AND evaluator_user_id = ?",
            (order_id, from_process_id, to_process_id, evaluator_user_id),
        ).fetchone()

    @staticmethod
    def insert_review(data, db):
        cur = db.execute(
            "INSERT INTO process_handoff_reviews ("
            "order_id, serial_no, from_process_id, to_process_id, from_user_id, evaluator_user_id, "
            "source_work_record_id, quantity, rating, issue_type, comment, status"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data["order_id"], data.get("serial_no", ""), data["from_process_id"], data["to_process_id"],
                data["from_user_id"], data["evaluator_user_id"], data.get("source_work_record_id"),
                data.get("quantity", 1), data["rating"], data.get("issue_type", ""),
                data.get("comment", ""), data.get("status", "confirmed"),
            ),
        )
        return cur.lastrowid

    @staticmethod
    def list_reviews(year_month="", status="", user_id=None, page=1, per_page=100, db=None):
        db = resolve_db(db)
        where = []
        params = []
        if year_month:
            where.append("phr.created_at LIKE ?")
            params.append(year_month + "%")
        if status:
            where.append("phr.status = ?")
            params.append(status)
        if user_id:
            where.append("phr.from_user_id = ?")
            params.append(user_id)
        where_clause = " AND ".join(where) if where else "1=1"
        total = db.execute(
            "SELECT COUNT(*) FROM process_handoff_reviews phr WHERE " + where_clause,
            params,
        ).fetchone()[0]
        offset = (page - 1) * per_page
        rows = db.execute(
            "SELECT phr.*, o.order_no, o.product_name, "
            "from_p.name AS from_process_name, to_p.name AS to_process_name, "
            "from_u.name AS from_user_name, from_u.employee_no AS from_employee_no, "
            "eval_u.name AS evaluator_name, confirm_u.name AS confirmer_name "
            "FROM process_handoff_reviews phr "
            "JOIN orders o ON o.id = phr.order_id "
            "JOIN processes from_p ON from_p.id = phr.from_process_id "
            "JOIN processes to_p ON to_p.id = phr.to_process_id "
            "JOIN users from_u ON from_u.id = phr.from_user_id "
            "JOIN users eval_u ON eval_u.id = phr.evaluator_user_id "
            "LEFT JOIN users confirm_u ON confirm_u.id = phr.confirmed_by "
            "WHERE " + where_clause + " ORDER BY phr.created_at DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "per_page": per_page}

    @staticmethod
    def monthly_metrics(year_month, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT from_user_id AS user_id, COUNT(*) AS review_count, ROUND(AVG(rating), 2) AS avg_rating, "
            "SUM(CASE WHEN rating <= 2 THEN 1 ELSE 0 END) AS low_count, "
            "SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) AS good_count "
            "FROM process_handoff_reviews "
            "WHERE created_at LIKE ? AND status = 'confirmed' "
            "GROUP BY from_user_id",
            (year_month + "%",),
        ).fetchall()

    @staticmethod
    def update_status(review_id, data, db):
        db.execute(
            "UPDATE process_handoff_reviews SET status = ?, confirm_note = ?, confirmed_by = ?, "
            "confirmed_at = datetime('now','localtime'), updated_at = datetime('now','localtime') WHERE id = ?",
            (data.get("status", "confirmed"), data.get("confirm_note", ""), data.get("confirmed_by"), review_id),
        )
