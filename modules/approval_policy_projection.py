"""Read-only SQL projection for the effective approval policy."""

from modules import config


def _tables(db):
    return {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('approval_policy_revisions','approval_policies','approval_policy_revision_steps')"
        ).fetchall()
    }


def effective_snapshot(process_id, db, versioned=None):
    versioned = config.APPROVAL_POLICY_VERSIONED_QUERY_ENABLED if versioned is None else bool(versioned)
    if not versioned or len(_tables(db)) < 3:
        row = db.execute(
            "SELECT * FROM approval_config WHERE process_id=? AND require_approval=1", (process_id,)
        ).fetchone()
        if not row:
            return {"require_approval": False, "approval_level": 1, "roles": [], "source": "legacy_config"}, None
        data = dict(row)
        level = max(1, min(3, int(data.get("approval_level") or 1)))
        roles = []
        for step_level, (role_id_key, role_code_key) in enumerate((
            ("approver_role_id", "approver_role"),
            ("approver_role_2_id", "approver_role_2"),
            ("approver_role_3_id", "approver_role_3"),
        )[:level], start=1):
            code = data.get(role_code_key) or ("admin" if step_level == 1 else "")
            if code:
                roles.append({"level": step_level, "role_id": data.get(role_id_key), "code": code, "name": code})
        return {"require_approval": True, "approval_level": level, "roles": roles, "source": "legacy_config"}, None

    revision = db.execute(
        "SELECT r.*,p.policy_key FROM approval_policy_revisions r "
        "JOIN approval_policies p ON p.id=r.policy_id "
        "WHERE p.process_id IS ? AND r.status='published' ORDER BY r.version DESC LIMIT 1",
        (process_id,),
    ).fetchone()
    if not revision:
        revision = db.execute(
            "SELECT r.*,p.policy_key FROM approval_policy_revisions r "
            "JOIN approval_policies p ON p.id=r.policy_id "
            "WHERE p.process_id IS NULL AND r.status='published' ORDER BY r.version DESC LIMIT 1"
        ).fetchone()
    if not revision:
        return {"require_approval": False, "approval_level": 1, "roles": [], "source": "default"}, None
    steps = db.execute(
        "SELECT step_level,role_id,role_code_snapshot,role_name_snapshot "
        "FROM approval_policy_revision_steps WHERE revision_id=? ORDER BY step_level",
        (revision["id"],),
    ).fetchall()
    return {
        "policy_key": revision["policy_key"],
        "require_approval": bool(revision["require_approval"]),
        "approval_level": revision["approval_level"],
        "roles": [{"level": s["step_level"], "role_id": s["role_id"], "code": s["role_code_snapshot"], "name": s["role_name_snapshot"]} for s in steps],
        "source": "versioned",
    }, revision["id"]
