"""V063 immutable business-fact process and route snapshot migration."""

import hashlib
import json

from modules.migration_helpers import (
    MigrationInvariantError,
    add_column_if_missing,
    column_exists,
)
from modules.migration_process_versioning_common import (
    PROCESS_FACT_BINDINGS,
    PROCESS_FACT_MIGRATION_KEY,
    _create_exception_table,
    _required_columns,
)


PROTECTED_PROCESS_FACT_TABLES = (
    "payroll_detail_lines",
    "performance_quality_events",
    "performance_source_facts",
)


def _fact_binding_columns(spec):
    columns = {
        "route_id",
        "route_version_id",
        "route_name_snapshot",
        "version_binding_source",
    }
    for role in spec["roles"]:
        columns.update(
            {
                f"{role}_version_id",
                f"{role}_code_snapshot",
                f"{role}_name_snapshot",
                f"{role}_category_snapshot",
            }
        )
    return columns


def _fact_business_fingerprints(db):
    fingerprints = {}
    for spec in PROCESS_FACT_BINDINGS:
        table = spec["table"]
        excluded = _fact_binding_columns(spec)
        columns = tuple(
            row[1]
            for row in db.execute(f"PRAGMA table_info({table})").fetchall()
            if row[1] not in excluded
        )
        digest = hashlib.sha256()
        count = 0
        quoted = ",".join(f'"{column}"' for column in columns)
        for row in db.execute(f'SELECT {quoted} FROM "{table}" ORDER BY id'):
            digest.update(repr(tuple(row)).encode("utf-8"))
            digest.update(b"\n")
            count += 1
        fingerprints[table] = (columns, count, digest.hexdigest())
    return fingerprints


def _version_binding_context(db):
    process_versions = {
        row["id"]: row
        for row in db.execute(
            "SELECT id,process_id,version,process_code_snapshot,name,category "
            "FROM process_versions"
        ).fetchall()
    }
    process_v1 = {
        row["process_id"]: row
        for row in process_versions.values()
        if row["version"] == 1
    }
    route_versions = {
        row["id"]: row
        for row in db.execute(
            "SELECT id,process_route_id,version,name FROM process_route_versions"
        ).fetchall()
    }
    route_v1 = {
        row["process_route_id"]: row
        for row in route_versions.values()
        if row["version"] == 1
    }
    orders = {
        row["id"]: (row["route_id"], row["route_version_id"])
        for row in db.execute(
            "SELECT id,route_id,route_version_id FROM orders"
        ).fetchall()
    }
    return {
        "process_versions": process_versions,
        "process_v1": process_v1,
        "route_versions": route_versions,
        "route_v1": route_v1,
        "orders": orders,
        "work_records": _load_work_route_bindings(db, orders, route_v1),
    }


def _load_work_route_bindings(db, orders, route_v1):
    bindings = {}
    columns = {row[1] for row in db.execute("PRAGMA table_info(work_records)")}
    route_select = "route_id" if "route_id" in columns else "NULL"
    version_select = (
        "route_version_id" if "route_version_id" in columns else "NULL"
    )
    for row in db.execute(
        f"SELECT id,order_id,{route_select} AS route_id,"
        f"{version_select} AS route_version_id FROM work_records"
    ).fetchall():
        order_route = orders.get(row["order_id"], (None, None))
        route_id = row["route_id"] or order_route[0]
        route_version_id = row["route_version_id"] or order_route[1]
        if route_id is not None and route_version_id is None:
            v1 = route_v1.get(route_id)
            route_version_id = v1["id"] if v1 is not None else None
        bindings[row["id"]] = (route_id, route_version_id)
    return bindings


def _resolve_fact_route(row, spec, context):
    route_id = row.get("route_id")
    route_version_id = row.get("route_version_id")
    for source_column in spec["work_sources"]:
        source_id = row.get(source_column)
        source_route = context["work_records"].get(source_id)
        if source_route is None:
            continue
        route_id = route_id or source_route[0]
        route_version_id = route_version_id or source_route[1]
        if route_id is not None and route_version_id is not None:
            break
    order_route = context["orders"].get(row.get("order_id"))
    if order_route is not None:
        route_id = route_id or order_route[0]
        route_version_id = route_version_id or order_route[1]
    if route_version_id is not None and route_id is None:
        version = context["route_versions"].get(route_version_id)
        route_id = version["process_route_id"] if version is not None else None
    if route_id is not None and route_version_id is None:
        v1 = context["route_v1"].get(route_id)
        route_version_id = v1["id"] if v1 is not None else None
    return route_id, route_version_id


def _append_fact_binding_issue(issues, table, role, legacy_id, reason_code, **summary):
    issues.append(
        {
            "entity_type": f"{table}.{role}",
            "legacy_id": legacy_id,
            "reason_code": reason_code,
            "summary": summary,
        }
    )


def _collect_fact_binding_issues(db):
    issues = []
    required = (
        ("process_versions", ("id", "process_id", "version")),
        ("process_route_versions", ("id", "process_route_id", "version")),
        ("orders", ("id", "route_id", "route_version_id")),
        ("work_records", ("id", "order_id")),
    )
    if not all(
        _required_columns(db, table, columns, issues)
        for table, columns in required
    ):
        return issues
    for spec in PROCESS_FACT_BINDINGS:
        required_columns = ["id"]
        required_columns.extend(f"{role}_id" for role in spec["roles"])
        required_columns.extend(spec["work_sources"])
        if not _required_columns(db, spec["table"], required_columns, issues):
            return issues

    context = _version_binding_context(db)
    for spec in PROCESS_FACT_BINDINGS:
        table = spec["table"]
        rows = [dict(row) for row in db.execute(f'SELECT * FROM "{table}"')]
        table_columns = set(rows[0]) if rows else {
            row[1] for row in db.execute(f"PRAGMA table_info({table})")
        }
        for row in rows:
            for role in spec["roles"]:
                root_id = row.get(f"{role}_id")
                version_column = f"{role}_version_id"
                version_id = row.get(version_column) if version_column in table_columns else None
                if root_id is None and version_id is not None:
                    _append_fact_binding_issue(
                        issues,
                        table,
                        role,
                        row["id"],
                        "process_version_without_root",
                        process_version_id=version_id,
                    )
                    continue
                if root_id is None:
                    continue
                if version_id is None:
                    if root_id not in context["process_v1"]:
                        _append_fact_binding_issue(
                            issues,
                            table,
                            role,
                            row["id"],
                            "missing_process_v1",
                            process_id=root_id,
                        )
                    continue
                version = context["process_versions"].get(version_id)
                if version is None or version["process_id"] != root_id:
                    _append_fact_binding_issue(
                        issues,
                        table,
                        role,
                        row["id"],
                        "invalid_exact_process_version",
                        process_id=root_id,
                        process_version_id=version_id,
                    )

            route_id, route_version_id = _resolve_fact_route(row, spec, context)
            if route_id is None and route_version_id is None:
                continue
            if route_id is None:
                _append_fact_binding_issue(
                    issues,
                    table,
                    "route",
                    row["id"],
                    "route_version_without_root",
                    route_version_id=route_version_id,
                )
                continue
            if route_version_id is None:
                _append_fact_binding_issue(
                    issues,
                    table,
                    "route",
                    row["id"],
                    "missing_route_v1",
                    route_id=route_id,
                )
                continue
            route_version = context["route_versions"].get(route_version_id)
            if (
                route_version is None
                or route_version["process_route_id"] != route_id
            ):
                _append_fact_binding_issue(
                    issues,
                    table,
                    "route",
                    row["id"],
                    "invalid_exact_route_version",
                    route_id=route_id,
                    route_version_id=route_version_id,
                )
    return issues


def _record_fact_binding_issues(db, issues):
    for issue in issues:
        db.execute(
            "INSERT OR IGNORE INTO process_version_migration_exceptions "
            "(migration_key,entity_type,legacy_id,reason_code,blocking,source_summary_json) "
            "VALUES (?,?,?,?,1,?)",
            (
                PROCESS_FACT_MIGRATION_KEY,
                issue["entity_type"],
                issue["legacy_id"],
                issue["reason_code"],
                json.dumps(issue["summary"], ensure_ascii=False, sort_keys=True),
            ),
        )


def _add_fact_binding_columns(db):
    for spec in PROCESS_FACT_BINDINGS:
        table = spec["table"]
        for role in spec["roles"]:
            add_column_if_missing(
                db,
                table,
                f"{role}_version_id",
                "INTEGER REFERENCES process_versions(id) ON DELETE RESTRICT",
            )
            add_column_if_missing(
                db,
                table,
                f"{role}_code_snapshot",
                "TEXT NOT NULL DEFAULT ''",
            )
            add_column_if_missing(
                db,
                table,
                f"{role}_name_snapshot",
                "TEXT NOT NULL DEFAULT ''",
            )
            add_column_if_missing(
                db,
                table,
                f"{role}_category_snapshot",
                "TEXT NOT NULL DEFAULT ''",
            )
        add_column_if_missing(
            db,
            table,
            "route_id",
            "INTEGER REFERENCES process_routes(id) ON DELETE RESTRICT",
        )
        add_column_if_missing(
            db,
            table,
            "route_version_id",
            "INTEGER REFERENCES process_route_versions(id) ON DELETE RESTRICT",
        )
        add_column_if_missing(
            db,
            table,
            "route_name_snapshot",
            "TEXT NOT NULL DEFAULT ''",
        )
        add_column_if_missing(
            db,
            table,
            "version_binding_source",
            "TEXT NOT NULL DEFAULT '' "
            "CHECK(version_binding_source IN ('','legacy_v1','captured'))",
        )


def _saved_fact_mutation_triggers(db):
    placeholders = ",".join("?" for _ in PROTECTED_PROCESS_FACT_TABLES)
    return [
        (row["name"], row["sql"])
        for row in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' "
            f"AND tbl_name IN ({placeholders}) ORDER BY name",
            PROTECTED_PROCESS_FACT_TABLES,
        ).fetchall()
        if row["sql"]
    ]


def _drop_saved_triggers(db, triggers):
    for name, _ in triggers:
        quoted_name = name.replace('"', '""')
        db.execute(f'DROP TRIGGER "{quoted_name}"')


def _restore_saved_triggers(db, triggers):
    for _, sql in triggers:
        db.execute(sql)


def _backfill_fact_bindings(db):
    context = _version_binding_context(db)
    for spec in PROCESS_FACT_BINDINGS:
        table = spec["table"]
        for source_row in db.execute(f'SELECT * FROM "{table}" ORDER BY id').fetchall():
            row = dict(source_row)
            updates = {}
            had_exact_binding = any(
                row.get(f"{role}_version_id") is not None
                for role in spec["roles"]
            ) or row.get("route_version_id") is not None
            has_binding = False
            for role in spec["roles"]:
                root_id = row.get(f"{role}_id")
                if root_id is None:
                    continue
                has_binding = True
                version_id = row.get(f"{role}_version_id")
                version = context["process_versions"].get(version_id)
                if version is None:
                    version = context["process_v1"][root_id]
                    updates[f"{role}_version_id"] = version["id"]
                snapshot_values = {
                    f"{role}_code_snapshot": version["process_code_snapshot"],
                    f"{role}_name_snapshot": version["name"],
                    f"{role}_category_snapshot": version["category"],
                }
                for column, value in snapshot_values.items():
                    if not row.get(column):
                        updates[column] = value or ""

            route_id, route_version_id = _resolve_fact_route(row, spec, context)
            if route_id is not None:
                has_binding = True
                if row.get("route_id") is None:
                    updates["route_id"] = route_id
                if row.get("route_version_id") is None:
                    updates["route_version_id"] = route_version_id
                route_version = context["route_versions"][route_version_id]
                if not row.get("route_name_snapshot"):
                    updates["route_name_snapshot"] = route_version["name"] or ""
            if has_binding and not row.get("version_binding_source"):
                updates["version_binding_source"] = (
                    "captured" if had_exact_binding else "legacy_v1"
                )
            if updates:
                assignments = ",".join(f'"{column}"=?' for column in updates)
                db.execute(
                    f'UPDATE "{table}" SET {assignments} WHERE id=?',
                    (*updates.values(), row["id"]),
                )
        if table == "work_records":
            context["work_records"] = _load_work_route_bindings(
                db, context["orders"], context["route_v1"]
            )


def _create_fact_binding_indexes(db):
    for spec in PROCESS_FACT_BINDINGS:
        table = spec["table"]
        key = spec["index_key"]
        for role in spec["roles"]:
            db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_v63_{key}_{role}_version "
                f'ON "{table}"("{role}_version_id")'
            )
        db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_v63_{key}_route_version "
            f'ON "{table}"(route_version_id)'
        )
        if column_exists(db, table, "order_id"):
            db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_v63_{key}_order_route "
                f'ON "{table}"(order_id,route_version_id)'
            )
        user_column = spec["user_column"]
        time_column = spec["time_column"]
        if user_column and column_exists(db, table, user_column):
            db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_v63_{key}_user_time "
                f'ON "{table}"("{user_column}","{time_column}")'
            )
        elif time_column and column_exists(db, table, time_column):
            db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_v63_{key}_time "
                f'ON "{table}"("{time_column}")'
            )


def _validate_fact_bindings(db, before, saved_triggers):
    after = _fact_business_fingerprints(db)
    if after != before:
        changed = sorted(
            table for table in before if before[table] != after.get(table)
        )
        raise MigrationInvariantError(
            "Migration v63 changed protected business facts: " + ", ".join(changed)
        )
    issues = _collect_fact_binding_issues(db)
    if issues:
        issue = issues[0]
        raise MigrationInvariantError(
            "Migration v63 left an invalid fact binding at "
            f"{issue['entity_type']}:{issue['legacy_id']}:{issue['reason_code']}"
        )
    for spec in PROCESS_FACT_BINDINGS:
        table = spec["table"]
        binding_predicates = [
            f'"{role}_id" IS NOT NULL' for role in spec["roles"]
        ]
        binding_predicates.append("route_id IS NOT NULL")
        invalid_source = db.execute(
            f'SELECT id FROM "{table}" WHERE ('
            + " OR ".join(binding_predicates)
            + ") AND version_binding_source NOT IN ('legacy_v1','captured') LIMIT 1"
        ).fetchone()
        if invalid_source is not None:
            raise MigrationInvariantError(
                f"Migration v63 left {table}:{invalid_source[0]} without a binding source"
            )
        for role in spec["roles"]:
            incomplete = db.execute(
                f'SELECT id FROM "{table}" WHERE "{role}_id" IS NOT NULL AND ('
                f'"{role}_version_id" IS NULL OR COALESCE("{role}_code_snapshot",\'\')=\'\' '
                f'OR COALESCE("{role}_name_snapshot",\'\')=\'\') LIMIT 1'
            ).fetchone()
            if incomplete is not None:
                raise MigrationInvariantError(
                    f"Migration v63 left incomplete {table}.{role} snapshot "
                    f"at legacy id {incomplete[0]}"
                )
    restored = _saved_fact_mutation_triggers(db)
    if restored != saved_triggers:
        raise MigrationInvariantError(
            "Migration v63 failed to restore immutable payroll/performance guards"
        )


def m063_version_process_facts(db):
    """Bind process-bearing business facts to immutable master-data versions."""
    _create_exception_table(db)
    issues = _collect_fact_binding_issues(db)
    if issues:
        _record_fact_binding_issues(db, issues)
        db.commit()
        sample = ", ".join(
            f"{issue['entity_type']}:{issue['legacy_id']}:{issue['reason_code']}"
            for issue in issues[:5]
        )
        raise MigrationInvariantError(
            f"Migration v63 blocked by {len(issues)} fact binding exception(s): {sample}"
        )

    before = _fact_business_fingerprints(db)
    saved_triggers = _saved_fact_mutation_triggers(db)
    db.execute("SAVEPOINT process_facts_v063")
    try:
        _drop_saved_triggers(db, saved_triggers)
        _add_fact_binding_columns(db)
        _backfill_fact_bindings(db)
        _create_fact_binding_indexes(db)
        _restore_saved_triggers(db, saved_triggers)
        from modules.migration_process_management import (
            rebuild_master_data_reference_guards,
        )

        rebuild_master_data_reference_guards(db)
        _validate_fact_bindings(db, before, saved_triggers)
    except Exception:
        db.execute("ROLLBACK TO process_facts_v063")
        db.execute("RELEASE process_facts_v063")
        raise
    db.execute("RELEASE process_facts_v063")
