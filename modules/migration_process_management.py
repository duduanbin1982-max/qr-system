"""Process-management integrity migrations."""

from modules.migration_helpers import column_exists, table_exists
from modules.process_references import PROCESS_REFERENCES


def _reference_conditions(db, old_id="OLD.id"):
    conditions = []
    for reference in PROCESS_REFERENCES:
        if not table_exists(db, reference.table):
            continue
        scalar_columns = [
            column for column in reference.columns
            if column_exists(db, reference.table, column)
        ]
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


def m049_protect_referenced_processes(db):
    db.execute("DROP TRIGGER IF EXISTS prevent_referenced_process_delete")
    conditions = _reference_conditions(db)
    if conditions:
        db.execute(
            "CREATE TRIGGER prevent_referenced_process_delete "
            "BEFORE DELETE ON processes "
            "WHEN " + " OR ".join(conditions) + " "
            "BEGIN "
            "SELECT RAISE(ABORT, 'process is referenced; deactivate it instead'); "
            "END"
        )


MIGRATIONS = [
    (49, "Protect referenced processes from physical deletion", m049_protect_referenced_processes),
]
