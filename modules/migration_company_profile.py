"""Versioned company-profile aggregate and permission migration."""

import json

from modules.domain.company_profile import COMPANY_PROFILE_FIELDS


def _company_field_checks():
    limits = {
        "company_name": 200,
        "contact": 100,
        "phone": 50,
        "address": 500,
        "description": 2000,
    }
    return ",\n            ".join(
        f"{field} TEXT NOT NULL DEFAULT '' CHECK(typeof({field})='text' AND length({field}) <= {limit})"
        for field, limit in limits.items()
    )


def _merge_role_permissions(db):
    for role in db.execute("SELECT id, code, permissions FROM roles").fetchall():
        try:
            permissions = json.loads(role["permissions"] or "[]")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(permissions, list) or "*" in permissions:
            continue

        additions = []
        if (
            "page:settings.company-info" in permissions
            or role["code"] == "production_manager"
        ):
            additions.extend(
                ["page:settings", "page:settings.company-info", "company_info:view"]
            )
        if "settings:manage" in permissions:
            additions.extend(
                [
                    "page:settings",
                    "page:settings.company-info",
                    "company_info:view",
                    "company_info:edit",
                ]
            )
        merged = list(dict.fromkeys([*permissions, *additions]))
        if merged != permissions:
            db.execute(
                "UPDATE roles SET permissions=? WHERE id=?",
                (json.dumps(merged, ensure_ascii=False), role["id"]),
            )


def m065_version_company_profile(db):
    checks = _company_field_checks()
    db.execute(
        f"""CREATE TABLE IF NOT EXISTS company_profiles (
            id INTEGER PRIMARY KEY CHECK(id=1),
            {checks},
            version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
            updated_by INTEGER,
            updated_by_name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )"""
    )
    db.execute(
        f"""CREATE TABLE IF NOT EXISTS company_profile_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL DEFAULT 1 CHECK(profile_id=1),
            {checks},
            version INTEGER NOT NULL CHECK(version >= 1),
            changed_fields TEXT NOT NULL DEFAULT '[]',
            actor_user_id INTEGER,
            actor_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(profile_id, version),
            FOREIGN KEY(profile_id) REFERENCES company_profiles(id) ON DELETE RESTRICT
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_profile_revisions_created "
        "ON company_profile_revisions(created_at DESC)"
    )
    db.execute(
        "CREATE TRIGGER IF NOT EXISTS prevent_company_profile_revision_update "
        "BEFORE UPDATE ON company_profile_revisions BEGIN "
        "SELECT RAISE(ABORT, 'company profile revisions are immutable'); END"
    )

    legacy = {
        row["key"]: row["value"] or ""
        for row in db.execute(
            "SELECT key, value FROM system_settings WHERE key IN (?,?,?,?,?)",
            COMPANY_PROFILE_FIELDS,
        ).fetchall()
    }
    values = [legacy.get(field, "") for field in COMPANY_PROFILE_FIELDS]
    db.execute(
        "INSERT OR IGNORE INTO company_profiles "
        "(id, company_name, contact, phone, address, description, version, updated_by_name) "
        "VALUES (1,?,?,?,?,?,1,'系统迁移')",
        values,
    )
    profile = db.execute("SELECT * FROM company_profiles WHERE id=1").fetchone()
    if not db.execute(
        "SELECT 1 FROM company_profile_revisions WHERE profile_id=1 AND version=?",
        (profile["version"],),
    ).fetchone():
        db.execute(
            "INSERT INTO company_profile_revisions "
            "(profile_id, company_name, contact, phone, address, description, version, "
            "changed_fields, actor_user_id, actor_name, created_at) "
            "VALUES (1,?,?,?,?,?,?,?,?,?,?)",
            (
                profile["company_name"],
                profile["contact"],
                profile["phone"],
                profile["address"],
                profile["description"],
                profile["version"],
                json.dumps(list(COMPANY_PROFILE_FIELDS), ensure_ascii=False),
                profile["updated_by"],
                profile["updated_by_name"] or "系统迁移",
                profile["updated_at"],
            ),
        )
    _merge_role_permissions(db)


MIGRATIONS = [
    (65, "Version company profile, history, and scoped permissions", m065_version_company_profile),
]
