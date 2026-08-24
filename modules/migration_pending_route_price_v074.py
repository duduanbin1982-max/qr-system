"""V074 pending route-price lifecycle and audit controls."""

from modules.migration_helpers import MigrationInvariantError
from modules.migration_process_versioning_v062 import (
    PRICE_VERSION_MUTATION_TRIGGERS,
    _create_price_binding_indexes,
    _create_price_binding_triggers,
)


V074_PRICE_COLUMNS = {
    "idempotency_key",
    "request_digest",
    "route_content_digest_snapshot",
    "process_content_digest_snapshot",
    "voided_at",
    "voided_by",
    "voided_by_name",
    "void_reason",
}


def _blocking_price_issues(db):
    rows = db.execute(
        "SELECT price.id FROM route_price_versions price "
        "LEFT JOIN process_route_version_items item "
        "ON item.route_version_id=price.route_version_id "
        "AND item.process_id=price.process_id "
        "AND item.process_version_id=price.process_version_id "
        "WHERE price.route_version_id IS NULL OR price.process_version_id IS NULL "
        "OR item.id IS NULL ORDER BY price.id"
    ).fetchall()
    return [int(row[0]) for row in rows]


def _duplicate_pending_draft_price_ids(db):
    rows = db.execute(
        "SELECT price.id FROM route_price_versions price "
        "JOIN process_route_versions route_version "
        "ON route_version.id=price.route_version_id "
        "JOIN process_versions process_version "
        "ON process_version.id=price.process_version_id "
        "JOIN ("
        "SELECT draft.route_version_id,draft.process_version_id "
        "FROM route_price_versions draft "
        "JOIN process_route_versions draft_route "
        "ON draft_route.id=draft.route_version_id "
        "JOIN process_versions draft_process "
        "ON draft_process.id=draft.process_version_id "
        "WHERE draft.status='draft' AND draft_route.status='pending_approval' "
        "AND draft_process.status IN ('published','pending_approval') "
        "GROUP BY draft.route_version_id,draft.process_version_id HAVING COUNT(*)>1"
        ") duplicate ON duplicate.route_version_id=price.route_version_id "
        "AND duplicate.process_version_id=price.process_version_id "
        "WHERE price.status='draft' AND route_version.status='pending_approval' "
        "AND process_version.status IN ('published','pending_approval') ORDER BY price.id"
    ).fetchall()
    return [int(row[0]) for row in rows]


def _route_price_columns(db):
    return {row["name"] for row in db.execute("PRAGMA table_info(route_price_versions)")}


def _direct_price_reference_tables(db):
    tables = [
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    return [
        table
        for table in tables
        if table != "route_price_versions"
        and any(
            row[2] == "route_price_versions"
            for row in db.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
        )
    ]


def _detach_price_reference_tables(db):
    detached = []
    for table in _direct_price_reference_tables(db):
        schema = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()[0]
        columns = [
            row[1] for row in db.execute(f'PRAGMA table_info("{table}")').fetchall()
        ]
        dependent_objects = [
            row[0]
            for row in db.execute(
                "SELECT sql FROM sqlite_master WHERE tbl_name=? "
                "AND type IN ('index','trigger') AND sql IS NOT NULL "
                "ORDER BY type,name",
                (table,),
            ).fetchall()
        ]
        backup_table = f"__v074_{table}_backup"
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (backup_table,),
        ).fetchone():
            raise MigrationInvariantError(
                f"V074 temporary backup table already exists: {backup_table}"
            )
        db.execute(f'CREATE TABLE "{backup_table}" AS SELECT * FROM "{table}"')
        db.execute(f'DROP TABLE "{table}"')
        detached.append(
            {
                "table": table,
                "backup_table": backup_table,
                "schema": schema,
                "columns": columns,
                "dependent_objects": dependent_objects,
            }
        )
    return detached


def _restore_price_reference_tables(db, detached):
    for item in detached:
        db.execute(item["schema"])
        columns = ",".join(f'"{column}"' for column in item["columns"])
        db.execute(
            f'INSERT INTO "{item["table"]}" ({columns}) '
            f'SELECT {columns} FROM "{item["backup_table"]}"'
        )
        for statement in item["dependent_objects"]:
            db.execute(statement)
        db.execute(f'DROP TABLE "{item["backup_table"]}"')


def _rebuild_route_price_versions(db):
    if V074_PRICE_COLUMNS.issubset(_route_price_columns(db)):
        return

    managed_triggers = set(PRICE_VERSION_MUTATION_TRIGGERS) | {
        "prevent_referenced_price_version_delete",
    }
    preserved_triggers = [
        (row["name"], row["sql"])
        for row in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' "
            "AND sql LIKE '%route_price_versions%'"
        ).fetchall()
        if row["name"] not in managed_triggers and row["sql"]
    ]
    for trigger_name in (*PRICE_VERSION_MUTATION_TRIGGERS, "prevent_referenced_price_version_delete"):
        db.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
    for trigger_name, _ in preserved_triggers:
        db.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
    db.execute(
            """
            CREATE TABLE route_price_versions_v074 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id INTEGER NOT NULL,
                process_id INTEGER NOT NULL,
                normal_unit_price_micros INTEGER NOT NULL CHECK(normal_unit_price_micros >= 0),
                rework_rate_basis_points INTEGER NOT NULL DEFAULT 0
                    CHECK(rework_rate_basis_points BETWEEN 0 AND 10000),
                rework_rate_configured INTEGER NOT NULL DEFAULT 0
                    CHECK(rework_rate_configured IN (0,1)),
                valid_from TEXT NOT NULL,
                valid_to TEXT,
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK(status IN ('draft','approved','retired','voided')),
                created_by INTEGER,
                created_by_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                approved_by INTEGER,
                approved_by_name TEXT NOT NULL DEFAULT '',
                approved_at TEXT NOT NULL DEFAULT '',
                remark TEXT NOT NULL DEFAULT '',
                legacy_route_price_id INTEGER,
                row_version INTEGER NOT NULL DEFAULT 0,
                route_version_id INTEGER REFERENCES process_route_versions(id) ON DELETE RESTRICT,
                process_version_id INTEGER REFERENCES process_versions(id) ON DELETE RESTRICT,
                legacy_binding_unavailable INTEGER NOT NULL DEFAULT 0
                    CHECK(legacy_binding_unavailable IN (0,1)),
                idempotency_key TEXT,
                request_digest TEXT NOT NULL DEFAULT '',
                route_content_digest_snapshot TEXT NOT NULL DEFAULT '',
                process_content_digest_snapshot TEXT NOT NULL DEFAULT '',
                voided_at TEXT,
                voided_by INTEGER,
                voided_by_name TEXT NOT NULL DEFAULT '',
                void_reason TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(route_id) REFERENCES process_routes(id) ON DELETE RESTRICT,
                FOREIGN KEY(process_id) REFERENCES processes(id) ON DELETE RESTRICT,
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY(voided_by) REFERENCES users(id) ON DELETE SET NULL,
                UNIQUE(legacy_route_price_id),
                CHECK(valid_to IS NULL OR valid_to = '' OR valid_to > valid_from)
            )
            """
    )
    db.execute(
            """
            INSERT INTO route_price_versions_v074 (
                id,route_id,process_id,normal_unit_price_micros,rework_rate_basis_points,
                rework_rate_configured,valid_from,valid_to,status,created_by,created_by_name,
                created_at,approved_by,approved_by_name,approved_at,remark,legacy_route_price_id,
                row_version,route_version_id,process_version_id,legacy_binding_unavailable
            )
            SELECT id,route_id,process_id,normal_unit_price_micros,rework_rate_basis_points,
                rework_rate_configured,valid_from,valid_to,status,created_by,created_by_name,
                created_at,approved_by,approved_by_name,approved_at,remark,legacy_route_price_id,
                row_version,route_version_id,process_version_id,legacy_binding_unavailable
            FROM route_price_versions
            """
    )
    db.execute("DROP TABLE route_price_versions")
    db.execute("ALTER TABLE route_price_versions_v074 RENAME TO route_price_versions")
    for _, trigger_sql in preserved_triggers:
        db.execute(trigger_sql)


def _create_member_event_table(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS master_data_release_member_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('added','removed','replaced')),
            member_type TEXT NOT NULL CHECK(member_type IN
                ('process_version','route_version','price_version')),
            member_id INTEGER NOT NULL,
            replacement_member_id INTEGER,
            actor_id INTEGER,
            actor_name TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(batch_id) REFERENCES master_data_release_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    _create_immutable_table_triggers(
        db,
        "master_data_release_member_events",
        "master data release member events are immutable",
    )


def _create_reference_audit_table(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS route_price_reference_compat_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            price_version_id INTEGER NOT NULL,
            published_route_content_digest TEXT NOT NULL DEFAULT '',
            published_process_content_digest TEXT NOT NULL DEFAULT '',
            price_route_content_digest_snapshot TEXT NOT NULL DEFAULT '',
            price_process_content_digest_snapshot TEXT NOT NULL DEFAULT '',
            mismatch INTEGER NOT NULL CHECK(mismatch IN (0,1)),
            detail_json TEXT NOT NULL DEFAULT '{}',
            observed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(price_version_id) REFERENCES route_price_versions(id) ON DELETE RESTRICT,
            UNIQUE(price_version_id,published_route_content_digest,published_process_content_digest)
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_route_price_reference_compat_audit_price "
        "ON route_price_reference_compat_audit(price_version_id,observed_at)"
    )
    _create_immutable_table_triggers(
        db,
        "route_price_reference_compat_audit",
        "route price reference compatibility evidence is immutable",
    )


def _create_immutable_table_triggers(db, table_name, message):
    for action in ("update", "delete"):
        db.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS protect_{table_name}_{action}
            BEFORE {action.upper()} ON {table_name}
            BEGIN SELECT RAISE(ABORT, '{message}'); END
            """
        )


def _create_price_v074_indexes(db):
    _create_price_binding_indexes(db)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_price_versions_lookup "
        "ON route_price_versions(route_id,process_id,status,valid_from,valid_to)"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_route_price_versions_idempotency "
        "ON route_price_versions(idempotency_key) "
        "WHERE idempotency_key IS NOT NULL AND idempotency_key<>''"
    )


def _create_price_v074_triggers(db):
    for trigger_name in (*PRICE_VERSION_MUTATION_TRIGGERS, "prevent_referenced_price_version_delete"):
        db.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
    db.execute("DROP TRIGGER IF EXISTS protect_voided_price_version")
    _create_price_binding_triggers(db)
    db.execute(
        """
        CREATE TRIGGER prevent_referenced_price_version_delete
        BEFORE DELETE ON route_price_versions
        WHEN OLD.status<>'draft' OR EXISTS (
            SELECT 1 FROM payroll_detail_lines WHERE price_version_id=OLD.id
        ) OR EXISTS (
            SELECT 1 FROM payroll_work_price_resolutions WHERE price_version_id=OLD.id
        )
        BEGIN SELECT RAISE(ABORT,'referenced price versions cannot be deleted'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER protect_voided_price_version
        BEFORE UPDATE ON route_price_versions
        WHEN OLD.status='voided'
        BEGIN SELECT RAISE(ABORT,'voided price versions are immutable'); END
        """
    )


def _backfill_price_digest_snapshots(db):
    db.execute(
        """
        UPDATE route_price_versions
        SET route_content_digest_snapshot=(
                SELECT content_digest FROM process_route_versions
                WHERE id=route_price_versions.route_version_id
            ),
            process_content_digest_snapshot=(
                SELECT content_digest FROM process_versions
                WHERE id=route_price_versions.process_version_id
            )
        WHERE route_version_id IS NOT NULL AND process_version_id IS NOT NULL
        """
    )
    rows = db.execute(
        "SELECT id FROM route_price_versions WHERE status='draft' ORDER BY id"
    ).fetchall()
    for row in rows:
        price_id = int(row[0])
        db.execute(
            "INSERT INTO payroll_events "
            "(event_type,operator_name,reason,payload_json,idempotency_key) "
            "SELECT ?,?,?,?,? WHERE NOT EXISTS ("
            "SELECT 1 FROM payroll_events WHERE idempotency_key=?"
            ")",
            (
                "price_version_v074_digest_backfilled",
                "migration-v074",
                "Backfilled exact route and process content digests for draft price version.",
                '{"source":"v074"}',
                f"v074:price:{price_id}:digest",
                f"v074:price:{price_id}:digest",
            ),
        )


def m074_pending_route_price_controls(db):
    blocking = _blocking_price_issues(db)
    blocking.extend(_duplicate_pending_draft_price_ids(db))
    blocking = sorted(set(blocking))
    if blocking:
        raise MigrationInvariantError(
            "V074 invalid exact price bindings: " + ",".join(map(str, blocking))
        )
    db.execute("SAVEPOINT pending_route_price_v074")
    try:
        # Keep connection-level foreign-key enforcement intact. SQLite defers
        # checks until the table swap has recreated the referenced table.
        db.execute("PRAGMA defer_foreign_keys=ON")
        rebuilding_price_table = not V074_PRICE_COLUMNS.issubset(
            _route_price_columns(db)
        )
        price_reference_tables = (
            _detach_price_reference_tables(db) if rebuilding_price_table else []
        )
        _rebuild_route_price_versions(db)
        _restore_price_reference_tables(db, price_reference_tables)
        _backfill_price_digest_snapshots(db)
        _create_member_event_table(db)
        _create_reference_audit_table(db)
        _create_price_v074_indexes(db)
        _create_price_v074_triggers(db)
    except Exception:
        db.execute("ROLLBACK TO pending_route_price_v074")
        db.execute("RELEASE pending_route_price_v074")
        raise
    db.execute("RELEASE pending_route_price_v074")


PENDING_ROUTE_PRICE_MIGRATIONS = [
    (74, "Add pending route-price lifecycle and audit controls", m074_pending_route_price_controls),
]
