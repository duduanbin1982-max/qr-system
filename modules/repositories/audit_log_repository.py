"""qr-system - AuditLogRepository

All SQL for audit_logs, user_roles, menu_permissions tables.
"""
import json
import uuid

from modules.repositories.context import resolve_db
from modules.audit_action_catalog import describe_action
from modules.audit_policy import sanitize_audit_detail
from modules.audit_writer import insert_audit_log


class AuditLogRepository:
    """Audit log + user roles + menu permissions data access."""

    # ============================================================
    # Operation Logs
    # ============================================================
    @staticmethod
    def insert_log(
        user_id,
        action,
        target_type="",
        target_id=0,
        detail="",
        db=None,
        *,
        event_id=None,
        request_id="",
    ):
        db = resolve_db(db)
        return insert_audit_log(
            db,
            user_id,
            action,
            target_type,
            target_id,
            detail,
            event_id=event_id,
            request_id=request_id,
        )

    @staticmethod
    def enqueue_event_txn(
        user_id,
        action,
        target_type="",
        target_id=0,
        detail=None,
        db=None,
        *,
        event_id=None,
        request_id="",
    ):
        """Persist a durable event envelope inside the caller's transaction."""

        db = resolve_db(db)
        metadata = describe_action(action)
        event_id = event_id or uuid.uuid4().hex
        payload = json.dumps(
            {
                "event_id": event_id,
                "user_id": user_id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "detail": sanitize_audit_detail(detail),
                "category": metadata.category,
                "severity": metadata.severity,
                "mandatory": int(metadata.mandatory),
                "schema_version": 1,
                "redaction_version": 1,
                "request_id": request_id or "",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        db.execute(
            "INSERT OR IGNORE INTO audit_event_outbox "
            "(event_id, action, category, payload) VALUES (?,?,?,?)",
            (event_id, action, metadata.category, payload),
        )
        return event_id

    @staticmethod
    def publish_pending_events(limit=100, db=None):
        """Publish pending outbox events; caller owns the transaction."""

        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM audit_event_outbox "
            "WHERE status IN ('pending','failed') "
            "AND (next_retry_at IS NULL OR next_retry_at <= datetime('now','localtime')) "
            "ORDER BY id LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
        published = 0
        failed = 0
        for row in rows:
            try:
                payload = json.loads(row["payload"] or "{}")
                db.execute(
                    "INSERT OR IGNORE INTO audit_logs "
                    "(event_id,user_id,action,target_type,target_id,detail,category,"
                    "severity,mandatory,schema_version,redaction_version,request_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        payload["event_id"],
                        payload.get("user_id"),
                        payload["action"],
                        payload.get("target_type", ""),
                        payload.get("target_id", 0),
                        sanitize_audit_detail(payload.get("detail", "")),
                        payload.get("category", row["category"]),
                        payload.get("severity", "info"),
                        int(payload.get("mandatory", 0)),
                        int(payload.get("schema_version", 1)),
                        int(payload.get("redaction_version", 1)),
                        payload.get("request_id", ""),
                    ),
                )
                db.execute(
                    "UPDATE audit_event_outbox SET status='published', attempts=attempts+1, "
                    "last_error='', published_at=datetime('now','localtime') WHERE id=?",
                    (row["id"],),
                )
                published += 1
            except Exception as exc:
                db.execute(
                    "UPDATE audit_event_outbox SET status='failed', attempts=attempts+1, "
                    "last_error=?, next_retry_at=datetime('now','localtime','+5 minutes') "
                    "WHERE id=?",
                    (str(exc)[:500], row["id"]),
                )
                failed += 1
        return {"published": published, "failed": failed}

    @staticmethod
    def list_logs(page=1, limit=50, action="", keyword="", user_id=None, category="", date_from="", date_to="", db=None):
        db = resolve_db(db)
        where = ["1=1"]
        params = []
        if action:
            where.append("al.action = ?"); params.append(action)
        if keyword:
            escaped_keyword = (
                keyword.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            where.append(
                "(al.detail LIKE ? ESCAPE '\\' OR al.target_type LIKE ? ESCAPE '\\')"
            )
            params.extend([
                "%" + escaped_keyword + "%",
                "%" + escaped_keyword + "%",
            ])
        if user_id:
            where.append("al.user_id = ?"); params.append(user_id)
        if category:
            where.append("al.category = ?")
            params.append(category)
        if date_from:
            where.append("al.created_at >= ?"); params.append(date_from)
        if date_to:
            where.append("al.created_at < datetime(?, '+1 day')"); params.append(date_to)
        where_sql = " AND ".join(where)

        total = db.execute(
            "SELECT COUNT(*) FROM audit_logs al WHERE " + where_sql, params
        ).fetchone()[0]
        rows = db.execute(
            "SELECT al.*, u.name as user_name "
            "FROM audit_logs al LEFT JOIN users u ON al.user_id = u.id "
            "WHERE " + where_sql + " "
            "ORDER BY al.created_at DESC, al.id DESC LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit]
        ).fetchall()
        logs = []
        for row in rows:
            item = dict(row)
            item["detail"] = sanitize_audit_detail(item.get("detail", ""))
            logs.append(item)
        return {"logs": logs, "total": total}

    # ============================================================
    # User Roles
    # ============================================================
    @staticmethod
    def get_user_roles(uid, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT r.*, rg.name as group_name "
            "FROM user_roles ur "
            "JOIN roles r ON ur.role_id = r.id "
            "LEFT JOIN role_groups rg ON r.group_id = rg.id "
            "WHERE ur.user_id = ? "
            "ORDER BY r.level, r.id",
            (uid,)
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def set_user_roles_txn(uid, role_ids, db):
        db.execute("DELETE FROM user_roles WHERE user_id = ?", (uid,))
        for rid in role_ids:
            db.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (uid, rid))

    @staticmethod
    def validate_role_ids(role_ids, db=None):
        db = resolve_db(db)
        placeholders = ",".join("?" for _ in role_ids)
        valid = {r[0] for r in db.execute(
            "SELECT id FROM roles WHERE id IN (" + placeholders + ")", role_ids
        ).fetchall()}
        invalid = [str(rid) for rid in role_ids if rid not in valid]
        return valid, invalid

    @staticmethod
    def batch_set_roles_txn(user_ids, role_ids, action, db):
        for uid in user_ids:
            if action == "set":
                db.execute("DELETE FROM user_roles WHERE user_id = ?", (uid,))
                for rid in role_ids:
                    db.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)", (uid, rid))
            elif action == "add":
                for rid in role_ids:
                    db.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)", (uid, rid))
            elif action == "remove":
                for rid in role_ids:
                    db.execute("DELETE FROM user_roles WHERE user_id = ? AND role_id = ?", (uid, rid))

    # ============================================================
    # Permission Matrix
    # ============================================================
    @staticmethod
    def get_active_users(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, username, name, nickname, role, status FROM users WHERE status='active' ORDER BY id"
        ).fetchall()

    @staticmethod
    def get_user_role_mappings(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT ur.user_id, ur.role_id, r.name as role_name, r.code as role_code, "
            "r.permissions, r.status as role_status "
            "FROM user_roles ur JOIN roles r ON ur.role_id = r.id ORDER BY r.level"
        ).fetchall()

    @staticmethod
    def get_all_roles(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, name, code, permissions, status, level FROM roles ORDER BY level"
        ).fetchall()

    # ============================================================
    # Menu Permissions CRUD
    # ============================================================
    @staticmethod
    def list_menu_permissions(db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM menu_permissions ORDER BY sort_order ASC, id ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def find_menu_by_page(page, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id FROM menu_permissions WHERE page = ?", (page,)
        ).fetchone()

    @staticmethod
    def insert_menu_permission_txn(page, permission, label, icon, sort_order, db):
        db.execute(
            "INSERT INTO menu_permissions (page, permission, label, icon, sort_order) VALUES (?,?,?,?,?)",
            (page, permission, label, (icon or "")[:20], sort_order)
        )

    @staticmethod
    def update_menu_permission_txn(page, set_clause, values, db):
        db.execute("UPDATE menu_permissions SET " + set_clause + " WHERE page = ?", values)

    @staticmethod
    def delete_menu_permission_txn(page, db):
        db.execute("DELETE FROM menu_permissions WHERE page = ?", (page,))

    @staticmethod
    def batch_update_menu_permissions_txn(items, db):
        for item in items:
            page = item.get("page", "").strip()
            if not page:
                continue
            permission = item.get("permission", "")
            label = item.get("label", "")
            icon = (item.get("icon", "") or "")[:20]
            sort_order = item.get("sort_order")
            if sort_order is not None:
                db.execute(
                    "UPDATE menu_permissions SET permission=?, label=?, icon=?, sort_order=? WHERE page=?",
                    (permission, label, icon, int(sort_order), page))
            else:
                db.execute(
                    "UPDATE menu_permissions SET permission=?, label=?, icon=? WHERE page=?",
                    (permission, label, icon, page))

    # ============================================================
    # Cleanup
    # ============================================================
    @staticmethod
    def create_cleanup_request_txn(before_days, reason, requested_by, db):
        before_at = db.execute(
            "SELECT datetime('now','localtime', ?)",
            (f"-{int(before_days)} days",),
        ).fetchone()[0]
        affected_count = db.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE created_at < ?",
            (before_at,),
        ).fetchone()[0]
        cursor = db.execute(
            "INSERT INTO audit_log_cleanup_requests "
            "(before_at, reason, requested_by, affected_count) VALUES (?,?,?,?)",
            (before_at, reason, requested_by, affected_count),
        )
        return {
            "id": cursor.lastrowid,
            "before_at": before_at,
            "affected_count": affected_count,
        }

    @staticmethod
    def list_cleanup_requests(status="", limit=100, db=None):
        db = resolve_db(db)
        where = ""
        params = []
        if status:
            where = "WHERE request.status=?"
            params.append(status)
        rows = db.execute(
            "SELECT request.*, requester.name AS requested_by_name, "
            "approver.name AS approved_by_name "
            "FROM audit_log_cleanup_requests request "
            "LEFT JOIN users requester ON requester.id=request.requested_by "
            "LEFT JOIN users approver ON approver.id=request.approved_by "
            + where
            + " ORDER BY request.requested_at DESC, request.id DESC LIMIT ?",
            params + [max(1, min(int(limit), 200))],
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def find_cleanup_request(request_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM audit_log_cleanup_requests WHERE id=?",
            (request_id,),
        ).fetchone()

    @staticmethod
    def reject_cleanup_request_txn(request_id, approver_id, decision_reason, db):
        result = db.execute(
            "UPDATE audit_log_cleanup_requests SET status='rejected', approved_by=?, "
            "approved_at=datetime('now','localtime'), decision_reason=? "
            "WHERE id=? AND status='pending' AND requested_by<>?",
            (approver_id, decision_reason, request_id, approver_id),
        )
        return result.rowcount == 1

    @staticmethod
    def execute_cleanup_request_txn(request_id, approver_id, decision_reason, db):
        request_row = AuditLogRepository.find_cleanup_request(request_id, db=db)
        if request_row is None:
            raise ValueError("清理申请不存在")
        if request_row["status"] != "pending":
            raise ValueError("清理申请已经处理")
        if int(request_row["requested_by"]) == int(approver_id):
            raise ValueError("申请人不能批准自己的清理申请")

        archive_batch_id = uuid.uuid4().hex
        rows = db.execute(
            "SELECT * FROM audit_logs WHERE created_at < ? ORDER BY id",
            (request_row["before_at"],),
        ).fetchall()
        for row in rows:
            payload = dict(row)
            payload["detail"] = sanitize_audit_detail(payload.get("detail", ""))
            payload["redaction_version"] = max(
                int(payload.get("redaction_version") or 1), 1
            )
            db.execute(
                "INSERT INTO audit_log_archive "
                "(archive_batch_id, source_id, event_id, payload) VALUES (?,?,?,?)",
                (
                    archive_batch_id,
                    row["id"],
                    row["event_id"],
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ),
                ),
            )
        deleted = db.execute(
            "DELETE FROM audit_logs WHERE created_at < ?",
            (request_row["before_at"],),
        ).rowcount
        db.execute(
            "UPDATE audit_log_cleanup_requests SET status='executed', approved_by=?, "
            "approved_at=datetime('now','localtime'), decision_reason=?, "
            "affected_count=?, archive_batch_id=?, "
            "executed_at=datetime('now','localtime') WHERE id=?",
            (
                approver_id,
                decision_reason,
                deleted,
                archive_batch_id,
                request_id,
            ),
        )
        return {
            "deleted": deleted,
            "archived": len(rows),
            "archive_batch_id": archive_batch_id,
        }
