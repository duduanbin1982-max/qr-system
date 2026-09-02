"""Role-group permission retirement and immutable cutover evidence."""


def m068_retire_role_group_permissions(db):
    """Prepare an auditable cutover without changing legacy permission data."""

    db.execute(
        """CREATE TABLE IF NOT EXISTS role_group_permission_cutovers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256) = 64),
            source_user_version INTEGER NOT NULL,
            actor_user_id INTEGER NOT NULL,
            actor_name TEXT NOT NULL CHECK(trim(actor_name) <> ''),
            approved_by_user_id INTEGER NOT NULL,
            approved_by_name TEXT NOT NULL CHECK(trim(approved_by_name) <> ''),
            group_count INTEGER NOT NULL CHECK(group_count >= 0),
            role_count INTEGER NOT NULL CHECK(role_count >= 0),
            user_count INTEGER NOT NULL CHECK(user_count >= 0),
            manifest_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'applied' CHECK(status = 'applied'),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            CHECK(actor_user_id <> approved_by_user_id)
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS role_group_permission_archive (
            cutover_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            group_name TEXT NOT NULL,
            group_status TEXT NOT NULL,
            permissions_json TEXT NOT NULL,
            role_codes_json TEXT NOT NULL DEFAULT '[]',
            role_count INTEGER NOT NULL CHECK(role_count >= 0),
            user_count INTEGER NOT NULL CHECK(user_count >= 0),
            archived_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY(cutover_id, group_id),
            FOREIGN KEY(cutover_id)
                REFERENCES role_group_permission_cutovers(id) ON DELETE RESTRICT
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_role_group_permission_archive_group "
        "ON role_group_permission_archive(group_id, cutover_id)"
    )

    for table in (
        "role_group_permission_cutovers",
        "role_group_permission_archive",
    ):
        db.execute(
            f"CREATE TRIGGER IF NOT EXISTS prevent_{table}_update "
            f"BEFORE UPDATE ON {table} BEGIN "
            "SELECT RAISE(ABORT, 'role-group permission evidence is immutable'); END"
        )
        db.execute(
            f"CREATE TRIGGER IF NOT EXISTS prevent_{table}_delete "
            f"BEFORE DELETE ON {table} BEGIN "
            "SELECT RAISE(ABORT, 'role-group permission evidence is immutable'); END"
        )

    db.execute(
        "CREATE TRIGGER IF NOT EXISTS prevent_role_group_permission_insert "
        "BEFORE INSERT ON role_groups "
        "WHEN trim(COALESCE(NEW.permissions, '')) NOT IN ('', '[]') BEGIN "
        "SELECT RAISE(ABORT, 'role groups cannot grant permissions'); END"
    )
    db.execute(
        "CREATE TRIGGER IF NOT EXISTS prevent_role_group_permission_update "
        "BEFORE UPDATE OF permissions ON role_groups "
        "WHEN trim(COALESCE(NEW.permissions, '')) NOT IN ('', '[]') BEGIN "
        "SELECT RAISE(ABORT, 'role groups cannot grant permissions'); END"
    )


MIGRATIONS = [
    (
        68,
        "Archive and retire role-group permissions without automatic data cleanup",
        m068_retire_role_group_permissions,
    ),
]
