"""Versioned approval-policy foundation migration (V071).

The legacy ``approval_config`` table remains readable during the compatibility
window.  This migration creates the immutable policy projection and captures
the effective policy on every existing approval record without changing the
current approval switch.
"""

import json

from modules.migration_helpers import add_column_if_missing


def _table_exists(db, name):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _create_policy_tables(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_key TEXT NOT NULL UNIQUE,
            process_id INTEGER,
            name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active','inactive')),
            current_revision_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(process_id) REFERENCES processes(id) ON DELETE RESTRICT,
            FOREIGN KEY(current_revision_id)
                REFERENCES approval_policy_revisions(id) ON DELETE RESTRICT
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_policy_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_id INTEGER NOT NULL,
            version INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft','pending_approval','published','superseded','rejected','retired')),
            require_approval INTEGER NOT NULL DEFAULT 0 CHECK(require_approval IN (0,1)),
            approval_level INTEGER NOT NULL DEFAULT 1 CHECK(approval_level BETWEEN 1 AND 3),
            source_type TEXT NOT NULL DEFAULT 'versioned',
            idempotency_key TEXT NOT NULL UNIQUE,
            row_version INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER,
            created_by_name TEXT NOT NULL DEFAULT '',
            submitted_by INTEGER,
            submitted_by_name TEXT NOT NULL DEFAULT '',
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            submitted_at TEXT,
            approved_at TEXT,
            published_at TEXT,
            superseded_at TEXT,
            FOREIGN KEY(policy_id) REFERENCES approval_policies(id) ON DELETE RESTRICT,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(submitted_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL,
            UNIQUE(policy_id, version)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_policy_revision_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision_id INTEGER NOT NULL,
            step_level INTEGER NOT NULL CHECK(step_level BETWEEN 1 AND 3),
            role_id INTEGER,
            role_code_snapshot TEXT NOT NULL DEFAULT '',
            role_name_snapshot TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(revision_id) REFERENCES approval_policy_revisions(id) ON DELETE RESTRICT,
            FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE SET NULL,
            UNIQUE(revision_id, step_level)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_policy_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            actor_id INTEGER,
            actor_name TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(revision_id) REFERENCES approval_policy_revisions(id) ON DELETE RESTRICT,
            FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE SET NULL,
            UNIQUE(revision_id, event_type, idempotency_key)
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_policies_process ON approval_policies(process_id, status)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_policy_revisions_policy ON approval_policy_revisions(policy_id, version DESC)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_policy_revisions_status ON approval_policy_revisions(status, published_at)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_policy_steps_revision ON approval_policy_revision_steps(revision_id, step_level)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_policy_events_revision ON approval_policy_events(revision_id, created_at)"
    )


def _create_immutable_triggers(db):
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS protect_published_approval_policy_revision
        BEFORE UPDATE ON approval_policy_revisions
        WHEN OLD.status IN ('published','superseded','retired') AND (
            NEW.policy_id <> OLD.policy_id OR NEW.version <> OLD.version OR
            NEW.require_approval <> OLD.require_approval OR
            NEW.approval_level <> OLD.approval_level OR
            NEW.source_type <> OLD.source_type OR
            NEW.idempotency_key <> OLD.idempotency_key OR
            NEW.created_by IS NOT OLD.created_by OR
            NEW.created_by_name <> OLD.created_by_name
        )
        BEGIN SELECT RAISE(ABORT, 'published approval policy revision is immutable'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS protect_published_approval_policy_revision_delete
        BEFORE DELETE ON approval_policy_revisions
        WHEN OLD.status IN ('published','superseded','retired')
        BEGIN SELECT RAISE(ABORT, 'published approval policy revision cannot be deleted'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS protect_published_approval_policy_step
        BEFORE UPDATE ON approval_policy_revision_steps
        WHEN EXISTS (
            SELECT 1 FROM approval_policy_revisions r
            WHERE r.id=OLD.revision_id AND r.status IN ('published','superseded','retired')
        )
        BEGIN SELECT RAISE(ABORT, 'published approval policy step is immutable'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS protect_published_approval_policy_step_delete
        BEFORE DELETE ON approval_policy_revision_steps
        WHEN EXISTS (
            SELECT 1 FROM approval_policy_revisions r
            WHERE r.id=OLD.revision_id AND r.status IN ('published','superseded','retired')
        )
        BEGIN SELECT RAISE(ABORT, 'published approval policy step cannot be deleted'); END
        """
    )


def _ensure_fact_snapshot_columns(db):
    add_column_if_missing(
        db, "approval_records", "approval_policy_revision_id",
        "INTEGER REFERENCES approval_policy_revisions(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(db, "approval_records", "policy_source", "TEXT NOT NULL DEFAULT 'legacy_config'")
    add_column_if_missing(db, "approval_records", "policy_snapshot_json", "TEXT NOT NULL DEFAULT '{}'" )
    add_column_if_missing(db, "approval_steps", "role_id_snapshot", "INTEGER")
    add_column_if_missing(db, "approval_steps", "role_code_snapshot", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "approval_steps", "role_name_snapshot", "TEXT NOT NULL DEFAULT ''")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_records_policy_revision ON approval_records(approval_policy_revision_id)"
    )


def _seed_baselines(db):
    if not _table_exists(db, "approval_config"):
        return
    configs = db.execute(
        "SELECT process_id, COALESCE(require_approval,0), COALESCE(approver_role,'admin'), "
        "COALESCE(approver_role_2,''), COALESCE(approver_role_3,''), COALESCE(approval_level,1), "
        "approver_role_id, approver_role_2_id, approver_role_3_id FROM approval_config "
        "ORDER BY process_id NULLS FIRST, id"
    ).fetchall()
    for row in configs:
        process_id, require, role1, role2, role3, level, role1_id, role2_id, role3_id = row
        policy_key = f"process:{process_id}" if process_id is not None else "global"
        process_name = ""
        if process_id is not None:
            process = db.execute("SELECT name FROM processes WHERE id=?", (process_id,)).fetchone()
            process_name = process[0] if process else ""
        db.execute(
            "INSERT OR IGNORE INTO approval_policies(policy_key,process_id,name) VALUES (?,?,?)",
            (policy_key, process_id, process_name or policy_key),
        )
        policy = db.execute("SELECT id FROM approval_policies WHERE policy_key=?", (policy_key,)).fetchone()
        if not policy:
            continue
        policy_id = policy[0]
        idem = f"approval-policy-v071-baseline-{policy_key}"
        db.execute(
            "INSERT OR IGNORE INTO approval_policy_revisions "
            "(policy_id,version,status,require_approval,approval_level,source_type,idempotency_key) "
            "VALUES (?,?,?,?,?,?,?)",
            (policy_id, 1, "published", int(require), max(1, min(3, int(level or 1))), "legacy_baseline", idem),
        )
        revision = db.execute(
            "SELECT id FROM approval_policy_revisions WHERE policy_id=? AND version=1", (policy_id,)
        ).fetchone()
        if not revision:
            continue
        revision_id = revision[0]
        db.execute(
            "UPDATE approval_policies SET current_revision_id=?,updated_at=datetime('now','localtime') WHERE id=?",
            (revision_id, policy_id),
        )
        roles = [(role1_id, role1), (role2_id, role2), (role3_id, role3)]
        for level_no, (role_id, role_code) in enumerate(roles[: max(1, min(3, int(level or 1)))], start=1):
            code = (role_code or "admin").strip().lower()
            role = db.execute("SELECT id,name,code FROM roles WHERE id=?", (role_id,)).fetchone() if role_id else None
            if role is None:
                role = db.execute("SELECT id,name,code FROM roles WHERE code=?", (code,)).fetchone()
            db.execute(
                "INSERT OR IGNORE INTO approval_policy_revision_steps "
                "(revision_id,step_level,role_id,role_code_snapshot,role_name_snapshot) VALUES (?,?,?,?,?)",
                (revision_id, level_no, role[0] if role else None, role[2] if role else code, role[1] if role else code),
            )
        db.execute(
            "INSERT OR IGNORE INTO approval_policy_events "
            "(revision_id,event_type,actor_name,idempotency_key,details_json) VALUES (?,?,?,?,?)",
            (revision_id, "baseline_created", "migration-v071", idem + ":event",
             json.dumps({"source": "approval_config"}, ensure_ascii=False)),
        )


def _backfill_approval_snapshots(db):
    if not _table_exists(db, "approval_records"):
        return
    rows = db.execute(
        "SELECT ar.id,wr.process_id FROM approval_records ar "
        "LEFT JOIN work_records wr ON wr.id=ar.work_record_id "
        "WHERE COALESCE(ar.policy_snapshot_json,'{}') IN ('','{}')"
    ).fetchall()
    for record_id, process_id in rows:
        policy_key = f"process:{process_id}" if process_id is not None else "global"
        revision = db.execute(
            "SELECT r.id,r.require_approval,r.approval_level,p.policy_key "
            "FROM approval_policy_revisions r JOIN approval_policies p ON p.id=r.policy_id "
            "WHERE p.policy_key=? AND r.status='published' ORDER BY r.version DESC LIMIT 1",
            (policy_key,),
        ).fetchone()
        if not revision:
            snapshot = {"require_approval": False, "approval_level": 1, "roles": [], "source": "legacy_config"}
            db.execute(
                "UPDATE approval_records SET policy_source='legacy_config',policy_snapshot_json=? WHERE id=?",
                (json.dumps(snapshot, ensure_ascii=False, sort_keys=True), record_id),
            )
            continue
        steps = db.execute(
            "SELECT step_level,role_id,role_code_snapshot,role_name_snapshot "
            "FROM approval_policy_revision_steps WHERE revision_id=? ORDER BY step_level",
            (revision[0],),
        ).fetchall()
        snapshot = {
            "policy_key": revision[3],
            "require_approval": bool(revision[1]),
            "approval_level": revision[2],
            "roles": [
                {"level": step[0], "role_id": step[1], "code": step[2], "name": step[3]}
                for step in steps
            ],
            "source": "legacy_baseline",
        }
        db.execute(
            "UPDATE approval_records SET approval_policy_revision_id=?,policy_source='versioned_baseline',policy_snapshot_json=? WHERE id=?",
            (revision[0], json.dumps(snapshot, ensure_ascii=False, sort_keys=True), record_id),
        )


def _backfill_permissions(db):
    """Map the legacy combined approval permission to the split view/write set.

    ``approval_policies:approve`` is deliberately excluded: publishing a
    policy is a separate approval duty and must be assigned explicitly.
    """
    if not _table_exists(db, "roles"):
        return
    for row in db.execute("SELECT id,permissions FROM roles").fetchall():
        try:
            permissions = json.loads(row[1] or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(permissions, list) or "*" in permissions or "approvals:edit" not in permissions:
            continue
        additions = [
            "approvals:decision",
            "approval_policies:view",
            "approval_policies:create",
            "approval_policies:submit",
            "approval_policies:history",
            "approval_policies:impact",
        ]
        merged = list(dict.fromkeys(permissions + additions))
        db.execute("UPDATE roles SET permissions=? WHERE id=?", (json.dumps(merged, ensure_ascii=False), row[0]))


def m071_approval_policy_versioning(db):
    _create_policy_tables(db)
    _ensure_fact_snapshot_columns(db)
    _seed_baselines(db)
    _backfill_approval_snapshots(db)
    _backfill_permissions(db)
    _create_immutable_triggers(db)


def _published_revision_for_process(db, process_id):
    row = db.execute(
        "SELECT revision.id FROM approval_policy_revisions revision "
        "JOIN approval_policies policy ON policy.id=revision.policy_id "
        "WHERE policy.process_id=? AND revision.status='published' "
        "ORDER BY revision.version DESC LIMIT 1", (process_id,)
    ).fetchone()
    return row[0] if row else None


def m072_approval_policy_fact_bindings(db):
    """Bind route/order/work facts to the approval policy revision in force."""
    for table in ("process_route_version_items", "order_processes", "work_records"):
        if not _table_exists(db, table):
            continue
        add_column_if_missing(
            db, table, "approval_policy_revision_id",
            "INTEGER REFERENCES approval_policy_revisions(id) ON DELETE RESTRICT",
        )
        add_column_if_missing(db, table, "approval_policy_source", "TEXT NOT NULL DEFAULT 'legacy_unbound'")
        db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_approval_policy ON {table}(approval_policy_revision_id)"
        )
    for table in ("process_route_version_items", "order_processes"):
        if not _table_exists(db, table):
            continue
        rows = db.execute(
            f"SELECT id,process_id FROM {table} WHERE COALESCE(required_audit,0)=1 "
            "AND approval_policy_revision_id IS NULL"
        ).fetchall()
        for row_id, process_id in rows:
            revision_id = _published_revision_for_process(db, process_id)
            if revision_id:
                db.execute(
                    f"UPDATE {table} SET approval_policy_revision_id=?,approval_policy_source='v071_baseline' WHERE id=?",
                    (revision_id, row_id),
                )


def m073_approval_policy_compatibility_controls(db):
    """Create immutable evidence for controlled Legacy/versioned cutover."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_policy_compat_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_id INTEGER,
            legacy_digest TEXT NOT NULL,
            versioned_digest TEXT NOT NULL,
            mismatch INTEGER NOT NULL CHECK(mismatch IN (0,1)),
            detail_json TEXT NOT NULL DEFAULT '{}',
            observed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(process_id) REFERENCES processes(id) ON DELETE SET NULL,
            UNIQUE(process_id,legacy_digest,versioned_digest)
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_policy_compat_audit_process "
        "ON approval_policy_compat_audit(process_id,observed_at)"
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS protect_approval_policy_compat_audit_update
        BEFORE UPDATE ON approval_policy_compat_audit
        BEGIN SELECT RAISE(ABORT, 'approval policy compatibility evidence is immutable'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS protect_approval_policy_compat_audit_delete
        BEFORE DELETE ON approval_policy_compat_audit
        BEGIN SELECT RAISE(ABORT, 'approval policy compatibility evidence is immutable'); END
        """
    )


MIGRATIONS = [
    (71, "Add versioned approval policy and approval snapshots", m071_approval_policy_versioning),
    (72, "Bind route order and work facts to approval policy revisions", m072_approval_policy_fact_bindings),
    (73, "Add approval policy compatibility audit controls", m073_approval_policy_compatibility_controls),
]
