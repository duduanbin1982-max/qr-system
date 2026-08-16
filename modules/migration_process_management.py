"""Process-management integrity migrations."""

from modules.master_data_references import (
    DELETE_BLOCK,
    PROCESS_REFERENCES,
    ROUTE_REFERENCES,
)
from modules.migration_helpers import column_exists, table_exists


def _reference_conditions(db, references, column_group, old_id="OLD.id"):
    conditions = []
    for reference in references:
        if reference.delete_policy != DELETE_BLOCK:
            continue
        if not table_exists(db, reference.table):
            continue
        columns = getattr(reference, column_group)
        scalar_columns = [
            column for column in columns
            if column_exists(db, reference.table, column)
        ]
        csv_columns = []
        if column_group == "root_columns":
            csv_columns = [
                column for column in reference.csv_columns
                if column_exists(db, reference.table, column)
            ]
        predicates = [f'"{column}" = {old_id}' for column in scalar_columns]
        predicates.extend(
            "(',' || REPLACE(COALESCE(\"" + column
            + "\", ''), ' ', '') || ',') LIKE ('%,' || " + old_id + " || ',%')"
            for column in csv_columns
        )
        if predicates:
            conditions.append(
                f'EXISTS (SELECT 1 FROM "{reference.table}" WHERE '
                + " OR ".join(predicates)
                + ")"
            )
    return conditions


def _replace_delete_guard(db, trigger, table, conditions, message):
    db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    if conditions:
        db.execute(
            f"CREATE TRIGGER {trigger} "
            f"BEFORE DELETE ON {table} "
            "WHEN " + " OR ".join(conditions) + " "
            "BEGIN "
            f"SELECT RAISE(ABORT, '{message}'); "
            "END"
        )


def rebuild_master_data_reference_guards(db):
    """Rebuild root/version delete guards from the shared reference catalog."""
    _replace_delete_guard(
        db,
        "prevent_referenced_process_delete",
        "processes",
        _reference_conditions(db, PROCESS_REFERENCES, "root_columns"),
        "process is referenced; deactivate it instead",
    )
    _replace_delete_guard(
        db,
        "prevent_referenced_route_delete",
        "process_routes",
        _reference_conditions(db, ROUTE_REFERENCES, "root_columns"),
        "route is referenced; create a revision instead",
    )
    if table_exists(db, "process_versions"):
        _replace_delete_guard(
            db,
            "prevent_referenced_process_version_delete",
            "process_versions",
            _reference_conditions(db, PROCESS_REFERENCES, "version_columns"),
            "process version is referenced and immutable; preserve the revision",
        )
    if table_exists(db, "process_route_versions"):
        _replace_delete_guard(
            db,
            "prevent_referenced_route_version_delete",
            "process_route_versions",
            _reference_conditions(db, ROUTE_REFERENCES, "version_columns"),
            "route version is referenced and immutable; preserve the revision",
        )


def m049_protect_referenced_processes(db):
    rebuild_master_data_reference_guards(db)


MIGRATIONS = [
    (49, "Protect referenced processes from physical deletion", m049_protect_referenced_processes),
]
