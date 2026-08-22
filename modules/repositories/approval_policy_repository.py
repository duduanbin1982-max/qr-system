"""Persistence gateway for versioned approval policies."""

import json

from modules.repositories.context import resolve_db
from modules.approval_policy_projection import effective_snapshot as project_effective_snapshot


class ApprovalPolicyRepository:
    @staticmethod
    def record_compat_audit(process_id, legacy_digest, versioned_digest, detail, db=None):
        """Persist a dual-read comparison when the optional audit table exists."""
        db = resolve_db(db)
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='approval_policy_compat_audit'"
        ).fetchone()
        if not table:
            return False
        db.execute(
            "INSERT OR IGNORE INTO approval_policy_compat_audit "
            "(process_id,legacy_digest,versioned_digest,mismatch,detail_json) VALUES (?,?,?,?,?)",
            (
                process_id,
                legacy_digest,
                versioned_digest,
                int(legacy_digest != versioned_digest),
                json.dumps(detail or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        return True

    @staticmethod
    def effective_snapshot(process_id, db=None):
        db = resolve_db(db)
        return project_effective_snapshot(process_id, db)
    @staticmethod
    def create_policy(policy_key, process_id, name, db):
        cur = db.execute(
            "INSERT INTO approval_policies(policy_key,process_id,name) VALUES (?,?,?)",
            (policy_key, process_id, name),
        )
        return cur.lastrowid

    @staticmethod
    def next_version(policy_id, db=None):
        db = resolve_db(db)
        return int(db.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM approval_policy_revisions WHERE policy_id=?",
            (policy_id,),
        ).fetchone()[0])
    @staticmethod
    def list_policies(db=None, include_history=False):
        db = resolve_db(db)
        status_clause = "" if include_history else "AND p.status='active'"
        return db.execute(
            "SELECT p.*,r.version,r.status AS revision_status,r.require_approval,"
            "r.approval_level,r.idempotency_key,r.created_by,r.created_by_name,"
            "r.published_at FROM approval_policies p "
            "LEFT JOIN approval_policy_revisions r ON r.id=p.current_revision_id "
            f"WHERE 1=1 {status_clause} ORDER BY p.process_id IS NULL DESC,p.process_id,p.id"
        ).fetchall()

    @staticmethod
    def find_policy(policy_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM approval_policies WHERE id=?", (policy_id,)).fetchone()

    @staticmethod
    def find_policy_by_process(process_id, db=None):
        db = resolve_db(db)
        if process_id is None:
            return db.execute("SELECT * FROM approval_policies WHERE process_id IS NULL").fetchone()
        return db.execute("SELECT * FROM approval_policies WHERE process_id=?", (process_id,)).fetchone()

    @staticmethod
    def find_revision(revision_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT r.*,p.policy_key,p.process_id,p.name AS policy_name "
            "FROM approval_policy_revisions r JOIN approval_policies p ON p.id=r.policy_id "
            "WHERE r.id=?", (revision_id,)
        ).fetchone()

    @staticmethod
    def find_published_revision(process_id, db=None):
        db = resolve_db(db)
        if process_id is None:
            return db.execute(
                "SELECT r.*,p.policy_key,p.process_id,p.name AS policy_name "
                "FROM approval_policy_revisions r JOIN approval_policies p ON p.id=r.policy_id "
                "WHERE p.process_id IS NULL AND r.status='published' ORDER BY r.version DESC LIMIT 1"
            ).fetchone()
        return db.execute(
            "SELECT r.*,p.policy_key,p.process_id,p.name AS policy_name "
            "FROM approval_policy_revisions r JOIN approval_policies p ON p.id=r.policy_id "
            "WHERE p.process_id=? AND r.status='published' ORDER BY r.version DESC LIMIT 1",
            (process_id,),
        ).fetchone()

    @staticmethod
    def list_revisions(policy_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM approval_policy_revisions WHERE policy_id=? ORDER BY version DESC",
            (policy_id,),
        ).fetchall()

    @staticmethod
    def list_steps(revision_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM approval_policy_revision_steps WHERE revision_id=? ORDER BY step_level",
            (revision_id,),
        ).fetchall()

    @staticmethod
    def find_by_idempotency_key(key, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM approval_policy_revisions WHERE idempotency_key=?", (key,)
        ).fetchone()

    @staticmethod
    def create_revision(policy_id, version, require_approval, approval_level,
                        idempotency_key, actor, steps, db):
        cur = db.execute(
            "INSERT INTO approval_policy_revisions "
            "(policy_id,version,status,require_approval,approval_level,idempotency_key,created_by,created_by_name) "
            "VALUES (?,?, 'draft',?,?,?,?,?)",
            (policy_id, version, int(require_approval), int(approval_level), idempotency_key,
             actor.get("id"), actor.get("name", "")),
        )
        revision_id = cur.lastrowid
        for step in steps:
            db.execute(
                "INSERT INTO approval_policy_revision_steps "
                "(revision_id,step_level,role_id,role_code_snapshot,role_name_snapshot) VALUES (?,?,?,?,?)",
                (revision_id, step["level"], step.get("role_id"), step["code"], step["name"]),
            )
        return revision_id

    @staticmethod
    def update_draft(revision_id, expected_row_version, require_approval,
                     approval_level, steps, db):
        cur = db.execute(
            "UPDATE approval_policy_revisions SET require_approval=?,approval_level=?,"
            "row_version=row_version+1 WHERE id=? AND status='draft' AND row_version=?",
            (int(require_approval), int(approval_level), revision_id, expected_row_version),
        )
        if cur.rowcount != 1:
            return False
        db.execute("DELETE FROM approval_policy_revision_steps WHERE revision_id=?", (revision_id,))
        for step in steps:
            db.execute(
                "INSERT INTO approval_policy_revision_steps "
                "(revision_id,step_level,role_id,role_code_snapshot,role_name_snapshot) VALUES (?,?,?,?,?)",
                (revision_id, step["level"], step.get("role_id"), step["code"], step["name"]),
            )
        return True

    @staticmethod
    def transition(revision_id, from_status, to_status, actor, db):
        fields = {
            "pending_approval": "submitted_by=?,submitted_by_name=?,submitted_at=datetime('now','localtime')",
            "published": "approved_by=?,approved_by_name=?,approved_at=datetime('now','localtime'),published_at=datetime('now','localtime')",
            "rejected": "approved_by=?,approved_by_name=?,approved_at=datetime('now','localtime')",
            "superseded": "superseded_at=datetime('now','localtime')",
        }
        assignment = fields.get(to_status, "")
        params = []
        if to_status in {"pending_approval", "published", "rejected"}:
            params.extend([actor.get("id"), actor.get("name", "")])
        params.extend([to_status, revision_id, from_status])
        cur = db.execute(
            f"UPDATE approval_policy_revisions SET status=?" + (f",{assignment}" if assignment else "") +
            " WHERE id=? AND status=?",
            [to_status] + params[:len(params)-3] + params[-2:],
        )
        return cur.rowcount

    @staticmethod
    def insert_event(revision_id, event_type, actor, details=None, idempotency_key=None, db=None):
        db = resolve_db(db)
        db.execute(
            "INSERT OR IGNORE INTO approval_policy_events "
            "(revision_id,event_type,actor_id,actor_name,idempotency_key,details_json) VALUES (?,?,?,?,?,?)",
            (revision_id, event_type, actor.get("id"), actor.get("name", ""), idempotency_key,
             json.dumps(details or {}, ensure_ascii=False, sort_keys=True)),
        )

    @staticmethod
    def set_current_revision(policy_id, revision_id, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE approval_policies SET current_revision_id=?,updated_at=datetime('now','localtime') WHERE id=?",
            (revision_id, policy_id),
        )

    @staticmethod
    def supersede_published(policy_id, except_revision_id, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE approval_policy_revisions SET status='superseded',superseded_at=datetime('now','localtime') "
            "WHERE policy_id=? AND status='published' AND id<>?",
            (policy_id, except_revision_id),
        )
