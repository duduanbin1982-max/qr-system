"""Role identity and approval-reference hardening migrations."""

import json

from modules.migration_helpers import add_column_if_missing
from modules.permission_catalog import infer_page_permissions


def _table_exists(db, table):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _index_exists(db, name):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone() is not None


def m069_role_identity_and_approval_refs(db):
    """Add immutable role aliases and stable approval role references.

    Legacy role-code columns remain readable/writable for one compatibility
    window; application services keep both columns synchronized.
    """
    db.execute(
        """CREATE TABLE IF NOT EXISTS role_code_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_id INTEGER,
            role_code TEXT NOT NULL,
            valid_from TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            valid_to TEXT,
            reason TEXT NOT NULL DEFAULT 'initial role code',
            changed_by INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(role_id, role_code),
            CHECK(trim(role_code) <> ''),
            CHECK(valid_to IS NULL OR valid_to >= valid_from),
            FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE SET NULL,
            FOREIGN KEY(changed_by) REFERENCES users(id) ON DELETE SET NULL
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_role_code_aliases_code "
        "ON role_code_aliases(role_code, valid_to)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_role_code_aliases_role "
        "ON role_code_aliases(role_id, valid_from)"
    )

    if _table_exists(db, "roles"):
        db.execute(
            """INSERT OR IGNORE INTO role_code_aliases(role_id, role_code, reason)
               SELECT id, code, 'initial role code backfill' FROM roles
               WHERE trim(COALESCE(code, '')) <> ''"""
        )

    if _table_exists(db, "approval_config"):
        add_column_if_missing(db, "approval_config", "approver_role_id", "INTEGER")
        add_column_if_missing(db, "approval_config", "approver_role_2_id", "INTEGER")
        add_column_if_missing(db, "approval_config", "approver_role_3_id", "INTEGER")
        for id_column, code_column in (
            ("approver_role_id", "approver_role"),
            ("approver_role_2_id", "approver_role_2"),
            ("approver_role_3_id", "approver_role_3"),
        ):
            db.execute(
                f"""UPDATE approval_config
                    SET {id_column} = (
                        SELECT r.id FROM roles r
                        WHERE r.code = approval_config.{code_column}
                        ORDER BY CASE WHEN r.status='active' THEN 0 ELSE 1 END, r.id
                        LIMIT 1
                    )
                    WHERE NULLIF(trim(COALESCE({code_column}, '')), '') IS NOT NULL
                      AND {id_column} IS NULL"""
            )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_approval_config_role_ids "
            "ON approval_config(approver_role_id, approver_role_2_id, approver_role_3_id)"
        )

    if _table_exists(db, "roles"):
        # Existing data was checked before rollout; these triggers enforce the
        # same contract for all legacy SQL writers during the compatibility window.
        db.execute(
            """CREATE TRIGGER IF NOT EXISTS validate_role_code_insert
               BEFORE INSERT ON roles
               WHEN length(trim(COALESCE(NEW.code, ''))) < 2
                 OR length(trim(COALESCE(NEW.code, ''))) > 64
                 OR NEW.code != lower(NEW.code)
                 OR NEW.code GLOB '*[^a-z0-9_]*'
               BEGIN SELECT RAISE(ABORT, 'role code must be lowercase [a-z0-9_] and 2-64 chars'); END"""
        )
        db.execute(
            """CREATE TRIGGER IF NOT EXISTS validate_role_code_update
               BEFORE UPDATE OF code ON roles
               WHEN length(trim(COALESCE(NEW.code, ''))) < 2
                 OR length(trim(COALESCE(NEW.code, ''))) > 64
                 OR NEW.code != lower(NEW.code)
                 OR NEW.code GLOB '*[^a-z0-9_]*'
               BEGIN SELECT RAISE(ABORT, 'role code must be lowercase [a-z0-9_] and 2-64 chars'); END"""
        )
        db.execute(
            """CREATE TRIGGER IF NOT EXISTS validate_role_level_insert
               BEFORE INSERT ON roles
               WHEN NEW.level IS NULL OR NEW.level < 1
                    OR NEW.level != CAST(NEW.level AS INTEGER)
               BEGIN SELECT RAISE(ABORT, 'role level must be a positive integer'); END"""
        )
        db.execute(
            """CREATE TRIGGER IF NOT EXISTS validate_role_level_update
               BEFORE UPDATE OF level ON roles
               WHEN NEW.level IS NULL OR NEW.level < 1
                    OR NEW.level != CAST(NEW.level AS INTEGER)
               BEGIN SELECT RAISE(ABORT, 'role level must be a positive integer'); END"""
        )
        db.execute(
            """CREATE TRIGGER IF NOT EXISTS protect_referenced_role_code_update
               BEFORE UPDATE OF code ON roles
               WHEN NEW.code <> OLD.code AND (
                   EXISTS (SELECT 1 FROM user_roles WHERE role_id = OLD.id)
                   OR EXISTS (SELECT 1 FROM users WHERE role = OLD.code)
                   OR EXISTS (SELECT 1 FROM approval_config WHERE
                       approver_role_id = OLD.id OR approver_role_2_id = OLD.id
                       OR approver_role_3_id = OLD.id
                       OR approver_role = OLD.code OR approver_role_2 = OLD.code
                       OR approver_role_3 = OLD.code)
               )
               BEGIN SELECT RAISE(ABORT, 'referenced role code is immutable'); END"""
        )
        db.execute(
            """CREATE TRIGGER IF NOT EXISTS record_direct_role_code_alias
               AFTER UPDATE OF code ON roles
               WHEN NEW.code <> OLD.code
               BEGIN
                   UPDATE role_code_aliases SET valid_to = datetime('now','localtime')
                   WHERE role_id = OLD.id AND role_code = OLD.code AND valid_to IS NULL;
                   INSERT OR IGNORE INTO role_code_aliases(role_id, role_code, reason)
                   VALUES (NEW.id, NEW.code, 'direct SQL role code change');
               END"""
        )
        if not _index_exists(db, "idx_roles_name_unique_nocase"):
            db.execute(
                "CREATE UNIQUE INDEX idx_roles_name_unique_nocase "
                "ON roles(name COLLATE NOCASE)"
            )
        if not _index_exists(db, "idx_role_groups_name_unique_nocase"):
            db.execute(
                "CREATE UNIQUE INDEX idx_role_groups_name_unique_nocase "
                "ON role_groups(name COLLATE NOCASE)"
            )

        db.execute(
            """CREATE TABLE IF NOT EXISTS role_permission_migration_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role_id INTEGER NOT NULL,
                role_code TEXT NOT NULL,
                old_permissions_json TEXT NOT NULL,
                new_permissions_json TEXT NOT NULL,
                mapping_json TEXT NOT NULL,
                assigned_user_count INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE(role_id, mapping_json),
                FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE RESTRICT
            )"""
        )
        db.execute(
            """CREATE TRIGGER IF NOT EXISTS prevent_role_permission_evidence_update
               BEFORE UPDATE ON role_permission_migration_evidence BEGIN
               SELECT RAISE(ABORT, 'role permission migration evidence is immutable'); END"""
        )
        db.execute(
            """CREATE TRIGGER IF NOT EXISTS prevent_role_permission_evidence_delete
               BEFORE DELETE ON role_permission_migration_evidence BEGIN
               SELECT RAISE(ABORT, 'role permission migration evidence is immutable'); END"""
        )
        for row in db.execute("SELECT id, code, permissions FROM roles ORDER BY id").fetchall():
            try:
                old_permissions = json.loads(row["permissions"] or "[]")
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(old_permissions, list):
                continue
            new_permissions = []
            mapping = {}
            for permission in old_permissions:
                replacement = "page:quality-management" if permission == "page:production.quality" else permission
                if replacement != permission:
                    mapping[permission] = replacement
                if replacement not in new_permissions:
                    new_permissions.append(replacement)
            new_permissions.extend(code for code in infer_page_permissions(new_permissions) if code not in new_permissions)
            if new_permissions == old_permissions:
                continue
            mapping_json = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            db.execute(
                "INSERT OR IGNORE INTO role_permission_migration_evidence "
                "(role_id, role_code, old_permissions_json, new_permissions_json, mapping_json, "
                "assigned_user_count, reason) VALUES (?,?,?,?,?,?,?)",
                (
                    row["id"], row["code"],
                    json.dumps(old_permissions, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(new_permissions, ensure_ascii=False, separators=(",", ":")),
                    mapping_json,
                    db.execute("SELECT COUNT(*) FROM user_roles WHERE role_id = ?", (row["id"],)).fetchone()[0],
                    "v069 controlled legacy permission mapping and page-chain backfill",
                ),
            )
            db.execute(
                "UPDATE roles SET permissions = ? WHERE id = ?",
                (json.dumps(new_permissions, ensure_ascii=False, separators=(",", ":")), row["id"]),
            )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_role_permission_evidence_role "
            "ON role_permission_migration_evidence(role_id, created_at)"
        )


MIGRATIONS = [
    (69, "Add immutable role-code aliases and stable approval role IDs", m069_role_identity_and_approval_refs),
]
