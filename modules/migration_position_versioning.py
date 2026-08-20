"""Versioned position master-data schema and Legacy V1 migration."""

import hashlib
import json

from modules.domain.position_versioning import content_digest
from modules.migration_helpers import (
    MigrationInvariantError,
    add_column_if_missing,
    column_exists,
    table_exists,
)


MIGRATION_KEY = "v070:position-legacy-baseline"
TERMINAL_VERSION_STATUSES = ("published", "superseded", "retired")

FACT_VERSION_COLUMNS = (
    (
        "performance_assignment_history",
        "position_version_id",
        "INTEGER REFERENCES position_versions(id) ON DELETE RESTRICT",
    ),
    (
        "performance_source_facts",
        "position_version_id",
        "INTEGER REFERENCES position_versions(id) ON DELETE RESTRICT",
    ),
    (
        "performance_score_revisions",
        "position_version_id_snapshot",
        "INTEGER REFERENCES position_versions(id) ON DELETE RESTRICT",
    ),
    (
        "work_records",
        "submit_position_version_id",
        "INTEGER REFERENCES position_versions(id) ON DELETE RESTRICT",
    ),
    (
        "performance_position_target_versions",
        "position_version_id_snapshot",
        "INTEGER REFERENCES position_versions(id) ON DELETE RESTRICT",
    ),
)


def _create_exception_table(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS position_version_migration_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_key TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            legacy_id INTEGER NOT NULL DEFAULT 0,
            reason_code TEXT NOT NULL,
            blocking INTEGER NOT NULL DEFAULT 1 CHECK(blocking IN (0,1)),
            source_summary_json TEXT NOT NULL DEFAULT '{}',
            resolution_status TEXT NOT NULL DEFAULT 'open'
                CHECK(resolution_status IN ('open','resolved','accepted')),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(migration_key,entity_type,legacy_id,reason_code)
        )
        """
    )


def _collect_preflight_issues(db):
    issues = []
    required = {
        "positions": ("id", "name", "description", "status", "created_at"),
        "position_processes": ("id", "position_id", "process_id"),
        "processes": ("id",),
        "users": ("id", "position_id", "status"),
        "performance_assignment_history": (
            "id",
            "user_id",
            "position_id",
            "position_name_snapshot",
            "valid_from",
            "valid_to",
            "source_key",
        ),
        "performance_source_facts": ("id", "position_id_snapshot"),
        "performance_score_revisions": ("id", "position_id_snapshot"),
        "work_records": ("id",),
        "performance_position_target_versions": ("id", "position_id"),
    }
    for table, columns in required.items():
        if not table_exists(db, table):
            issues.append(
                {
                    "entity_type": "schema",
                    "legacy_id": 0,
                    "reason_code": "missing_required_table_" + table,
                    "summary": {"table": table},
                }
            )
            continue
        for column in columns:
            if not column_exists(db, table, column):
                issues.append(
                    {
                        "entity_type": "schema",
                        "legacy_id": 0,
                        "reason_code": f"missing_required_column_{table}_{column}",
                        "summary": {"table": table, "column": column},
                    }
                )

    if table_exists(db, "positions"):
        for row in db.execute(
            "SELECT id,status FROM positions "
            "WHERE COALESCE(status,'') NOT IN ('active','inactive') ORDER BY id"
        ).fetchall():
            issues.append(
                {
                    "entity_type": "position",
                    "legacy_id": row[0],
                    "reason_code": "invalid_lifecycle_status",
                    "summary": {"status": row[1]},
                }
            )
        if column_exists(db, "positions", "position_code"):
            for row in db.execute(
                "SELECT id,position_code FROM positions "
                "WHERE COALESCE(position_code,'')<>'' "
                "AND position_code<>printf('POS-%04d',id) ORDER BY id"
            ).fetchall():
                issues.append(
                    {
                        "entity_type": "position",
                        "legacy_id": row[0],
                        "reason_code": "stable_code_conflict",
                        "summary": {
                            "observed": row[1],
                            "expected": f"POS-{row[0]:04d}",
                        },
                    }
                )

    if table_exists(db, "position_processes"):
        queries = (
            (
                "missing_position_root",
                "SELECT mapping.id,mapping.position_id,mapping.process_id "
                "FROM position_processes mapping LEFT JOIN positions position "
                "ON position.id=mapping.position_id WHERE position.id IS NULL ORDER BY mapping.id",
            ),
            (
                "missing_process_root",
                "SELECT mapping.id,mapping.position_id,mapping.process_id "
                "FROM position_processes mapping LEFT JOIN processes process "
                "ON process.id=mapping.process_id WHERE process.id IS NULL ORDER BY mapping.id",
            ),
        )
        for reason_code, sql in queries:
            for row in db.execute(sql).fetchall():
                issues.append(
                    {
                        "entity_type": "position_process",
                        "legacy_id": row[0],
                        "reason_code": reason_code,
                        "summary": {
                            "position_id": row[1],
                            "process_id": row[2],
                        },
                    }
                )
        for row in db.execute(
            "SELECT MIN(id),position_id,process_id,COUNT(*) "
            "FROM position_processes GROUP BY position_id,process_id "
            "HAVING COUNT(*)>1 ORDER BY position_id,process_id"
        ).fetchall():
            issues.append(
                {
                    "entity_type": "position_process",
                    "legacy_id": row[0],
                    "reason_code": "duplicate_position_process",
                    "summary": {
                        "position_id": row[1],
                        "process_id": row[2],
                        "count": row[3],
                    },
                }
            )

    if table_exists(db, "users") and table_exists(db, "positions"):
        for row in db.execute(
            "SELECT user.id,user.position_id FROM users user "
            "LEFT JOIN positions position ON position.id=user.position_id "
            "WHERE user.status='active' AND user.position_id IS NOT NULL "
            "AND position.id IS NULL ORDER BY user.id"
        ).fetchall():
            issues.append(
                {
                    "entity_type": "user",
                    "legacy_id": row[0],
                    "reason_code": "active_user_missing_position",
                    "summary": {"position_id": row[1]},
                }
            )

    if table_exists(db, "performance_assignment_history"):
        for row in db.execute(
            "SELECT MIN(id),user_id,COUNT(*) FROM performance_assignment_history "
            "WHERE COALESCE(valid_to,'')='' GROUP BY user_id HAVING COUNT(*)>1 "
            "ORDER BY user_id"
        ).fetchall():
            issues.append(
                {
                    "entity_type": "performance_assignment_history",
                    "legacy_id": row[0],
                    "reason_code": "overlapping_open_assignment",
                    "summary": {"user_id": row[1], "count": row[2]},
                }
            )
    return issues


def _record_issues(db, issues):
    for issue in issues:
        db.execute(
            "INSERT OR IGNORE INTO position_version_migration_exceptions ("
            "migration_key,entity_type,legacy_id,reason_code,blocking,source_summary_json) "
            "VALUES (?,?,?,?,1,?)",
            (
                MIGRATION_KEY,
                issue["entity_type"],
                issue["legacy_id"],
                issue["reason_code"],
                json.dumps(issue["summary"], ensure_ascii=False, sort_keys=True),
            ),
        )


def _add_position_root_columns(db):
    add_column_if_missing(db, "positions", "position_code", "TEXT DEFAULT ''")
    add_column_if_missing(
        db,
        "positions",
        "lifecycle_status",
        "TEXT NOT NULL DEFAULT 'active' "
        "CHECK(lifecycle_status IN ('active','retired'))",
    )
    add_column_if_missing(
        db,
        "positions",
        "current_effective_version_id",
        "INTEGER REFERENCES position_versions(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(
        db, "positions", "row_version", "INTEGER NOT NULL DEFAULT 0"
    )
    add_column_if_missing(
        db,
        "positions",
        "created_by",
        "INTEGER REFERENCES users(id) ON DELETE SET NULL",
    )
    add_column_if_missing(db, "positions", "retired_at", "TEXT DEFAULT ''")


def _create_position_version_tables(db):
    statements = (
        """
        CREATE TABLE IF NOT EXISTS position_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            version INTEGER NOT NULL CHECK(version>0),
            position_code_snapshot TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft','pending_approval','published','superseded',
                    'rejected','cancelled','retired')),
            effective_from TEXT NOT NULL DEFAULT '',
            effective_to TEXT NOT NULL DEFAULT '',
            supersedes_version_id INTEGER,
            revision_reason TEXT NOT NULL DEFAULT '',
            legacy_baseline INTEGER NOT NULL DEFAULT 0 CHECK(legacy_baseline IN (0,1)),
            prior_revision_unavailable INTEGER NOT NULL DEFAULT 0
                CHECK(prior_revision_unavailable IN (0,1)),
            content_digest TEXT NOT NULL DEFAULT '',
            impact_digest TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            created_by INTEGER,
            created_by_name TEXT NOT NULL DEFAULT '',
            submitted_at TEXT NOT NULL DEFAULT '',
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            approved_at TEXT NOT NULL DEFAULT '',
            published_at TEXT NOT NULL DEFAULT '',
            row_version INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(position_id) REFERENCES positions(id) ON DELETE RESTRICT,
            FOREIGN KEY(supersedes_version_id) REFERENCES position_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS position_version_processes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_version_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            seq_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(position_version_id) REFERENCES position_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(process_id) REFERENCES processes(id) ON DELETE RESTRICT,
            UNIQUE(position_version_id,process_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS position_version_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            position_version_id INTEGER,
            event_type TEXT NOT NULL,
            from_status TEXT NOT NULL DEFAULT '',
            to_status TEXT NOT NULL DEFAULT '',
            actor_id INTEGER,
            actor_name TEXT NOT NULL DEFAULT '',
            actor_role TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            impact_digest TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(position_id) REFERENCES positions(id) ON DELETE RESTRICT,
            FOREIGN KEY(position_version_id) REFERENCES position_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS position_lifecycle_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('retire','reactivate')),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','approved','rejected','cancelled')),
            reason TEXT NOT NULL,
            impact_digest TEXT NOT NULL DEFAULT '',
            requested_by INTEGER,
            requested_by_name TEXT NOT NULL DEFAULT '',
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            row_version INTEGER NOT NULL DEFAULT 0,
            idempotency_key TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            resolved_at TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(position_id) REFERENCES positions(id) ON DELETE RESTRICT,
            FOREIGN KEY(requested_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS position_version_migration_manifests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_key TEXT NOT NULL,
            source_position_count INTEGER NOT NULL CHECK(source_position_count>=0),
            source_position_process_count INTEGER NOT NULL
                CHECK(source_position_process_count>=0),
            migrated_version_count INTEGER NOT NULL CHECK(migrated_version_count>=0),
            migrated_version_process_count INTEGER NOT NULL
                CHECK(migrated_version_process_count>=0),
            cutover_assignment_count INTEGER NOT NULL
                CHECK(cutover_assignment_count>=0),
            manifest_sha256 TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(migration_key),
            UNIQUE(manifest_sha256)
        )
        """,
    )
    for statement in statements:
        db.execute(statement)


def _add_position_fact_columns(db):
    for table, column, definition in FACT_VERSION_COLUMNS:
        add_column_if_missing(db, table, column, definition)


def _create_position_version_indexes(db):
    statements = (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_position_code "
        "ON positions(position_code) WHERE position_code<>''",
        "CREATE INDEX IF NOT EXISTS idx_positions_effective_version "
        "ON positions(current_effective_version_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_position_versions_root_version "
        "ON position_versions(position_id,version)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_position_versions_one_published "
        "ON position_versions(position_id) WHERE status='published'",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_position_versions_one_open "
        "ON position_versions(position_id) WHERE status IN ('draft','pending_approval')",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_position_versions_idempotency "
        "ON position_versions(idempotency_key) WHERE idempotency_key<>''",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_position_version_processes_unique "
        "ON position_version_processes(position_version_id,process_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_position_version_processes_sequence "
        "ON position_version_processes(position_version_id,seq_order)",
        "CREATE INDEX IF NOT EXISTS idx_position_version_processes_process "
        "ON position_version_processes(process_id,position_version_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_position_version_events_idempotency "
        "ON position_version_events(idempotency_key) WHERE idempotency_key<>''",
        "CREATE INDEX IF NOT EXISTS idx_position_version_events_root "
        "ON position_version_events(position_id,created_at,id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_position_lifecycle_one_pending "
        "ON position_lifecycle_requests(position_id) WHERE status='pending'",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_position_lifecycle_idempotency "
        "ON position_lifecycle_requests(idempotency_key) WHERE idempotency_key<>''",
        "CREATE INDEX IF NOT EXISTS idx_position_assignment_version "
        "ON performance_assignment_history(position_version_id)",
        "CREATE INDEX IF NOT EXISTS idx_position_source_fact_version "
        "ON performance_source_facts(position_version_id)",
        "CREATE INDEX IF NOT EXISTS idx_position_score_version "
        "ON performance_score_revisions(position_version_id_snapshot)",
        "CREATE INDEX IF NOT EXISTS idx_position_work_submit_version "
        "ON work_records(submit_position_version_id)",
        "CREATE INDEX IF NOT EXISTS idx_position_target_version "
        "ON performance_position_target_versions(position_version_id_snapshot)",
    )
    for statement in statements:
        db.execute(statement)


def _legacy_process_ids(db, position_id):
    return [
        int(row[0])
        for row in db.execute(
            "SELECT process_id FROM position_processes WHERE position_id=? "
            "ORDER BY process_id,id",
            (position_id,),
        ).fetchall()
    ]


def _create_legacy_v1_baselines(db):
    db.execute(
        "UPDATE positions SET position_code=printf('POS-%04d',id) "
        "WHERE COALESCE(position_code,'')=''"
    )
    db.execute(
        "UPDATE positions SET lifecycle_status="
        "CASE WHEN status='active' THEN 'active' ELSE 'retired' END "
        "WHERE current_effective_version_id IS NULL"
    )

    for root_row in db.execute("SELECT * FROM positions ORDER BY id").fetchall():
        root = dict(root_row)
        process_ids = _legacy_process_ids(db, root["id"])
        existing = db.execute(
            "SELECT * FROM position_versions WHERE position_id=? AND version=1",
            (root["id"],),
        ).fetchone()
        if existing is None:
            status = "published" if root["status"] == "active" else "retired"
            baseline_time = root.get("created_at") or db.execute(
                "SELECT datetime('now','localtime')"
            ).fetchone()[0]
            digest = content_digest(
                {
                    "position_id": root["id"],
                    "version": 1,
                    "position_code_snapshot": root["position_code"],
                    "name": root["name"],
                    "description": root.get("description") or "",
                    "process_ids": process_ids,
                }
            )
            version_id = db.execute(
                "INSERT INTO position_versions ("
                "position_id,version,position_code_snapshot,name,description,status,"
                "effective_from,revision_reason,legacy_baseline,prior_revision_unavailable,"
                "content_digest,idempotency_key,published_at,created_at,row_version) "
                "VALUES (?,1,?,?,?,?,?,'Legacy V1 baseline; prior revision unavailable',"
                "1,1,?,'v070:position:' || ? || ':v1',?,?,0)",
                (
                    root["id"],
                    root["position_code"],
                    root["name"],
                    root.get("description") or "",
                    status,
                    baseline_time,
                    digest,
                    root["id"],
                    baseline_time,
                    baseline_time,
                ),
            ).lastrowid
        else:
            version_id = existing["id"]

        db.execute(
            "UPDATE positions SET current_effective_version_id=? "
            "WHERE id=? AND current_effective_version_id IS NULL",
            (version_id, root["id"]),
        )
        for seq_order, process_id in enumerate(process_ids, start=1):
            db.execute(
                "INSERT INTO position_version_processes "
                "(position_version_id,process_id,seq_order) "
                "SELECT ?,?,? WHERE NOT EXISTS ("
                "SELECT 1 FROM position_version_processes "
                "WHERE position_version_id=? AND process_id=?)",
                (version_id, process_id, seq_order, version_id, process_id),
            )
        db.execute(
            "INSERT OR IGNORE INTO position_version_events ("
            "position_id,position_version_id,event_type,actor_name,actor_role,reason,"
            "idempotency_key,from_status,to_status,payload_json) "
            "VALUES (?,?,'legacy_baseline_created','System migration','system',"
            "'Legacy V1 baseline; prior revision unavailable',"
            "'v070:position:' || ? || ':baseline','',"
            "(SELECT status FROM position_versions WHERE id=?),?)",
            (
                root["id"],
                version_id,
                root["id"],
                version_id,
                json.dumps(
                    {"legacy_baseline": 1, "prior_revision_unavailable": 1},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )


def _split_open_assignments_at_cutover(db):
    if not table_exists(db, "performance_assignment_history"):
        return 0
    cutover_at = db.execute("SELECT datetime('now','localtime')").fetchone()[0]
    rows = db.execute(
        "SELECT assignment.*,position.current_effective_version_id,"
        "position.name AS current_position_name "
        "FROM performance_assignment_history assignment "
        "JOIN users user ON user.id=assignment.user_id AND user.status='active' "
        "JOIN positions position ON position.id=assignment.position_id "
        "AND position.lifecycle_status='active' "
        "WHERE COALESCE(assignment.valid_to,'')='' "
        "AND assignment.position_version_id IS NULL "
        "AND position.current_effective_version_id IS NOT NULL "
        "ORDER BY assignment.id"
    ).fetchall()
    created = 0
    for row_value in rows:
        row = dict(row_value)
        source_key = (
            f"position_v070:{row['id']}:{row['current_effective_version_id']}"
        )
        db.execute(
            "UPDATE performance_assignment_history SET valid_to=? "
            "WHERE id=? AND COALESCE(valid_to,'')='' AND position_version_id IS NULL",
            (cutover_at, row["id"]),
        )
        cursor = db.execute(
            "INSERT OR IGNORE INTO performance_assignment_history ("
            "user_id,employee_name_snapshot,employee_no_snapshot,position_id,"
            "position_version_id,position_name_snapshot,department_id,"
            "department_name_snapshot,valid_from,valid_to,source_type,source_key,created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,'','position_v070_cutover',?,?)",
            (
                row["user_id"],
                row["employee_name_snapshot"],
                row["employee_no_snapshot"],
                row["position_id"],
                row["current_effective_version_id"],
                row["current_position_name"],
                row["department_id"],
                row["department_name_snapshot"],
                cutover_at,
                source_key,
                row["created_by"],
            ),
        )
        created += int(cursor.rowcount == 1)
    return created


def _create_position_immutable_triggers(db):
    terminal = "'" + "','".join(TERMINAL_VERSION_STATUSES) + "'"
    statements = (
        """
        CREATE TRIGGER IF NOT EXISTS protect_position_root_code_update
        BEFORE UPDATE OF position_code ON positions
        WHEN OLD.position_code<>NEW.position_code
        BEGIN SELECT RAISE(ABORT,'stable position code is immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS protect_position_version_identity_update
        BEFORE UPDATE OF position_id,version,position_code_snapshot ON position_versions
        WHEN OLD.position_id<>NEW.position_id OR OLD.version<>NEW.version
            OR OLD.position_code_snapshot<>NEW.position_code_snapshot
        BEGIN SELECT RAISE(ABORT,'position version identity is immutable'); END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS protect_terminal_position_version_content
        BEFORE UPDATE OF position_id,version,position_code_snapshot,name,description,
            revision_reason,legacy_baseline,prior_revision_unavailable,content_digest,
            created_by,created_by_name,created_at,idempotency_key
        ON position_versions
        WHEN OLD.status IN ({terminal})
        BEGIN SELECT RAISE(ABORT,'published position version content is immutable'); END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS prevent_terminal_position_version_delete
        BEFORE DELETE ON position_versions
        WHEN OLD.status IN ({terminal})
        BEGIN SELECT RAISE(ABORT,'published position versions are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_terminal_position_version_reopen
        BEFORE UPDATE OF status ON position_versions
        WHEN (OLD.status='published' AND NEW.status NOT IN ('published','superseded','retired'))
            OR (OLD.status='superseded' AND NEW.status<>'superseded')
            OR (OLD.status='retired' AND NEW.status<>'retired')
        BEGIN SELECT RAISE(ABORT,'terminal position version status is immutable'); END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS prevent_terminal_position_process_insert
        BEFORE INSERT ON position_version_processes
        WHEN EXISTS (SELECT 1 FROM position_versions version
            WHERE version.id=NEW.position_version_id AND version.status IN ({terminal}))
        BEGIN SELECT RAISE(ABORT,'published position version processes are immutable'); END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS prevent_terminal_position_process_update
        BEFORE UPDATE ON position_version_processes
        WHEN EXISTS (SELECT 1 FROM position_versions version
            WHERE version.id=OLD.position_version_id AND version.status IN ({terminal}))
          OR EXISTS (SELECT 1 FROM position_versions version
            WHERE version.id=NEW.position_version_id AND version.status IN ({terminal}))
        BEGIN SELECT RAISE(ABORT,'published position version processes are immutable'); END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS prevent_terminal_position_process_delete
        BEFORE DELETE ON position_version_processes
        WHEN EXISTS (SELECT 1 FROM position_versions version
            WHERE version.id=OLD.position_version_id AND version.status IN ({terminal}))
        BEGIN SELECT RAISE(ABORT,'published position version processes are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_position_version_event_update
        BEFORE UPDATE ON position_version_events
        BEGIN SELECT RAISE(ABORT,'position version events are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_position_version_event_delete
        BEFORE DELETE ON position_version_events
        BEGIN SELECT RAISE(ABORT,'position version events are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_position_version_manifest_update
        BEFORE UPDATE ON position_version_migration_manifests
        BEGIN SELECT RAISE(ABORT,'position version migration manifests are immutable'); END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_position_version_manifest_delete
        BEFORE DELETE ON position_version_migration_manifests
        BEGIN SELECT RAISE(ABORT,'position version migration manifests are immutable'); END
        """,
    )
    for statement in statements:
        db.execute(statement)
    _create_position_root_delete_guard(db, terminal)


def _create_position_root_delete_guard(db, terminal):
    conditions = [
        f"EXISTS (SELECT 1 FROM position_versions version WHERE "
        f"version.position_id=OLD.id AND version.status IN ({terminal}))"
    ]
    candidates = (
        ("users", "position_id"),
        ("user_sessions", "active_position_id"),
        ("position_processes", "position_id"),
        ("performance_assignment_history", "position_id"),
        ("performance_source_facts", "position_id_snapshot"),
        ("performance_score_revisions", "position_id_snapshot"),
        ("performance_position_target_versions", "position_id"),
        ("position_lifecycle_requests", "position_id"),
    )
    for table, column in candidates:
        if table_exists(db, table) and column_exists(db, table, column):
            conditions.append(
                f"EXISTS (SELECT 1 FROM {table} reference_row "
                f"WHERE reference_row.{column}=OLD.id)"
            )
    db.execute("DROP TRIGGER IF EXISTS prevent_referenced_position_root_delete")
    db.execute(
        "CREATE TRIGGER prevent_referenced_position_root_delete "
        "BEFORE DELETE ON positions WHEN "
        + " OR ".join(conditions)
        + " BEGIN SELECT RAISE(ABORT,'referenced position root cannot be deleted'); END"
    )


def _source_manifest(db):
    positions = [
        list(row)
        for row in db.execute(
            "SELECT id,name,COALESCE(description,''),status,created_at "
            "FROM positions ORDER BY id"
        ).fetchall()
    ]
    mappings = [
        list(row)
        for row in db.execute(
            "SELECT position_id,process_id FROM position_processes "
            "ORDER BY position_id,process_id,id"
        ).fetchall()
    ]
    source = {"positions": positions, "position_processes": mappings}
    canonical = json.dumps(
        source, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return source, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_position_baseline(db):
    expected_positions = db.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    actual_versions = db.execute(
        "SELECT COUNT(*) FROM position_versions WHERE version=1 "
        "AND legacy_baseline=1 AND prior_revision_unavailable=1"
    ).fetchone()[0]
    if actual_versions != expected_positions:
        raise MigrationInvariantError(
            f"Migration v70 position V1 count expected {expected_positions}, got {actual_versions}"
        )
    expected_processes = db.execute(
        "SELECT COUNT(*) FROM position_processes"
    ).fetchone()[0]
    actual_processes = db.execute(
        "SELECT COUNT(*) FROM position_version_processes version_process "
        "JOIN position_versions version ON version.id=version_process.position_version_id "
        "WHERE version.version=1"
    ).fetchone()[0]
    if actual_processes != expected_processes:
        raise MigrationInvariantError(
            "Migration v70 position process baseline count mismatch"
        )
    mismatch = db.execute(
        "SELECT position.id FROM positions position "
        "LEFT JOIN position_versions version "
        "ON version.id=position.current_effective_version_id "
        "WHERE version.id IS NULL OR version.position_id<>position.id "
        "OR version.version<>1 OR version.position_code_snapshot<>position.position_code "
        "OR version.name<>position.name "
        "OR version.description<>COALESCE(position.description,'') "
        "OR version.status<>CASE WHEN position.status='active' "
        "THEN 'published' ELSE 'retired' END LIMIT 1"
    ).fetchone()
    if mismatch is not None:
        raise MigrationInvariantError(
            f"Migration v70 position projection mismatch at {mismatch[0]}"
        )
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise MigrationInvariantError("Migration v70 introduced foreign key violations")


def _write_position_manifest(db):
    source, digest = _source_manifest(db)
    counts = {
        "source_position_count": len(source["positions"]),
        "source_position_process_count": len(source["position_processes"]),
        "migrated_version_count": db.execute(
            "SELECT COUNT(*) FROM position_versions WHERE version=1 AND legacy_baseline=1"
        ).fetchone()[0],
        "migrated_version_process_count": db.execute(
            "SELECT COUNT(*) FROM position_version_processes version_process "
            "JOIN position_versions version ON version.id=version_process.position_version_id "
            "WHERE version.version=1"
        ).fetchone()[0],
        "cutover_assignment_count": db.execute(
            "SELECT COUNT(*) FROM performance_assignment_history "
            "WHERE source_type='position_v070_cutover'"
        ).fetchone()[0],
    }
    existing = db.execute(
        "SELECT manifest_sha256 FROM position_version_migration_manifests "
        "WHERE migration_key=?",
        (MIGRATION_KEY,),
    ).fetchone()
    if existing is not None:
        if existing[0] != digest:
            raise MigrationInvariantError(
                "Migration v70 existing manifest differs from Legacy position projection"
            )
        return
    summary = {
        **counts,
        "legacy_baseline": True,
        "prior_revision_unavailable": True,
        "old_fact_versions_preserved_as_null": True,
        "stable_code_policy": "legacy_database_id",
    }
    db.execute(
        "INSERT INTO position_version_migration_manifests ("
        "migration_key,source_position_count,source_position_process_count,"
        "migrated_version_count,migrated_version_process_count,cutover_assignment_count,"
        "manifest_sha256,summary_json) VALUES (?,?,?,?,?,?,?,?)",
        (
            MIGRATION_KEY,
            counts["source_position_count"],
            counts["source_position_process_count"],
            counts["migrated_version_count"],
            counts["migrated_version_process_count"],
            counts["cutover_assignment_count"],
            digest,
            json.dumps(summary, ensure_ascii=False, sort_keys=True),
        ),
    )


def m070_position_versioning(db):
    """Create immutable position V1 baselines without rewriting old facts."""
    _create_exception_table(db)
    issues = _collect_preflight_issues(db)
    if issues:
        _record_issues(db, issues)
        db.commit()
        sample = ", ".join(
            f"{issue['entity_type']}:{issue['legacy_id']}:{issue['reason_code']}"
            for issue in issues[:5]
        )
        raise MigrationInvariantError(
            f"Migration v70 blocked by {len(issues)} position exception(s): {sample}"
        )

    db.execute("SAVEPOINT position_versioning_v070")
    try:
        _add_position_root_columns(db)
        _create_position_version_tables(db)
        _add_position_fact_columns(db)
        _create_position_version_indexes(db)
        _create_legacy_v1_baselines(db)
        _split_open_assignments_at_cutover(db)
        _create_position_immutable_triggers(db)
        _validate_position_baseline(db)
        _write_position_manifest(db)
    except Exception:
        db.execute("ROLLBACK TO position_versioning_v070")
        db.execute("RELEASE position_versioning_v070")
        raise
    db.execute("RELEASE position_versioning_v070")


MIGRATIONS = [
    (70, "Add versioned position master-data baseline", m070_position_versioning),
]
