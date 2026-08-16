"""Employee identity, role, and retention safeguards."""


def _has_column(db, table, column):
    return any(row["name"] == column for row in db.execute(
        "PRAGMA table_info(" + table + ")"
    ).fetchall())


def _add_column(db, table, definition):
    column = definition.split()[0]
    if not _has_column(db, table, column):
        db.execute("ALTER TABLE " + table + " ADD COLUMN " + definition)


def m059_harden_user_identity_and_retention(db):
    """Retain historical facts when an employee identity is removed.

    The employee number index is intentionally installed only after checking
    existing normalized values. A migration must never guess which duplicated
    historical employee number is authoritative.
    """
    _add_column(db, "users", "purged_at TEXT DEFAULT ''")
    _add_column(db, "users", "purged_by INTEGER")
    _add_column(db, "users", "purge_reason TEXT DEFAULT ''")

    duplicates = db.execute(
        "SELECT lower(trim(employee_no)) AS employee_no, "
        "GROUP_CONCAT(id || ':' || username, ', ') AS users, COUNT(*) AS count "
        "FROM users WHERE trim(COALESCE(employee_no, '')) <> '' "
        "GROUP BY lower(trim(employee_no)) HAVING COUNT(*) > 1 "
        "ORDER BY employee_no"
    ).fetchall()
    if duplicates:
        summary = "; ".join(
            row["employee_no"] + " (" + row["users"] + ")"
            for row in duplicates[:10]
        )
        suffix = "" if len(duplicates) <= 10 else "; ..."
        raise RuntimeError(
            "Migration v59 blocked: duplicate normalized employee numbers require "
            "manual resolution: " + summary + suffix
        )

    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_employee_no_normalized "
        "ON users(lower(trim(employee_no))) "
        "WHERE trim(COALESCE(employee_no, '')) <> ''"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_purged_at "
        "ON users(purged_at) WHERE purged_at <> ''"
    )


MIGRATIONS = [
    (
        59,
        "Harden employee identity uniqueness and historical retention",
        m059_harden_user_identity_and_retention,
    ),
]
