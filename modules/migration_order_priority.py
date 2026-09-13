"""V084 order priority, scheduling policy and immutable change history."""

import hashlib
import json

from modules.migration_helpers import add_column_if_missing


MIGRATION_KEY = "v084:order-priority"


def _snapshot_digest(snapshot):
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _history_snapshot(row):
    """Return the values that make an order's scheduling intent auditable."""
    return {
        "order_id": row["id"],
        "order_no": row["order_no"] or "",
        "priority_level": int(row["priority_level"] or 3),
        "is_expedited": int(row["is_expedited"] or 0),
        "deadline": row["deadline"] or "",
        "priority_effective_at": row["priority_effective_at"] or "",
        "schedule_policy": row["schedule_policy"] or "auto",
        "priority_reason": row["priority_reason"] or "",
        "priority_version": int(row["priority_version"] or 1),
    }


def _create_history_table(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS order_priority_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            order_no_snapshot TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL CHECK(event_type IN ('baseline','created','updated')),
            old_priority_level INTEGER,
            new_priority_level INTEGER NOT NULL CHECK(new_priority_level BETWEEN 1 AND 5),
            old_is_expedited INTEGER,
            new_is_expedited INTEGER NOT NULL CHECK(new_is_expedited IN (0,1)),
            old_deadline TEXT NOT NULL DEFAULT '',
            new_deadline TEXT NOT NULL DEFAULT '',
            old_priority_effective_at TEXT NOT NULL DEFAULT '',
            new_priority_effective_at TEXT NOT NULL DEFAULT '',
            old_schedule_policy TEXT NOT NULL DEFAULT 'auto',
            new_schedule_policy TEXT NOT NULL DEFAULT 'auto',
            old_priority_reason TEXT NOT NULL DEFAULT '',
            new_priority_reason TEXT NOT NULL DEFAULT '',
            change_reason TEXT NOT NULL DEFAULT '',
            changed_by INTEGER,
            changed_by_name TEXT NOT NULL DEFAULT '',
            changed_at TEXT NOT NULL,
            priority_version INTEGER NOT NULL CHECK(priority_version >= 1),
            snapshot_digest TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE SET NULL,
            CHECK(length(trim(order_no_snapshot)) > 0),
            CHECK(length(trim(changed_at)) > 0),
            CHECK(length(trim(snapshot_digest)) = 64),
            CHECK(old_priority_level IS NULL OR old_priority_level BETWEEN 1 AND 5),
            CHECK(old_is_expedited IS NULL OR old_is_expedited IN (0,1)),
            CHECK(new_schedule_policy IN ('auto','no_split','allow_split','allow_cross_day')),
            CHECK(old_schedule_policy IN ('auto','no_split','allow_split','allow_cross_day'))
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_priority_history_order "
        "ON order_priority_history(order_id, id DESC)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_priority_history_effective "
        "ON order_priority_history(new_priority_level, new_is_expedited, new_deadline)"
    )
    # ``ON DELETE SET NULL`` must be able to detach a purged order while
    # preserving the immutable audit row. All other updates remain blocked.
    db.execute("DROP TRIGGER IF EXISTS protect_order_priority_history_update")
    db.execute("DROP TRIGGER IF EXISTS protect_order_priority_history_delete")
    db.executescript(
        """
        CREATE TRIGGER protect_order_priority_history_update
        BEFORE UPDATE ON order_priority_history
        WHEN NOT (
            OLD.order_id IS NOT NULL AND NEW.order_id IS NULL
            AND OLD.order_no_snapshot = NEW.order_no_snapshot
            AND OLD.snapshot_digest = NEW.snapshot_digest
            AND OLD.event_type = NEW.event_type
            AND OLD.priority_version = NEW.priority_version
            AND OLD.old_priority_level IS NEW.old_priority_level
            AND OLD.new_priority_level = NEW.new_priority_level
            AND OLD.old_is_expedited IS NEW.old_is_expedited
            AND OLD.new_is_expedited = NEW.new_is_expedited
            AND OLD.old_deadline = NEW.old_deadline
            AND OLD.new_deadline = NEW.new_deadline
            AND OLD.old_priority_effective_at = NEW.old_priority_effective_at
            AND OLD.new_priority_effective_at = NEW.new_priority_effective_at
            AND OLD.old_schedule_policy = NEW.old_schedule_policy
            AND OLD.new_schedule_policy = NEW.new_schedule_policy
            AND OLD.old_priority_reason = NEW.old_priority_reason
            AND OLD.new_priority_reason = NEW.new_priority_reason
            AND OLD.change_reason = NEW.change_reason
            AND OLD.changed_by IS NEW.changed_by
            AND OLD.changed_by_name = NEW.changed_by_name
            AND OLD.changed_at = NEW.changed_at
            AND OLD.created_at = NEW.created_at
        )
        BEGIN
            SELECT RAISE(ABORT, 'order priority history is immutable');
        END;

        CREATE TRIGGER protect_order_priority_history_delete
        BEFORE DELETE ON order_priority_history
        BEGIN
            SELECT RAISE(ABORT, 'order priority history cannot be deleted');
        END;
        """
    )


def m084_order_priority(db):
    """Add scheduling intent fields and seed one immutable baseline per order."""
    for column, definition in {
        "priority_level": "INTEGER NOT NULL DEFAULT 3 CHECK(priority_level BETWEEN 1 AND 5)",
        "is_expedited": "INTEGER NOT NULL DEFAULT 0 CHECK(is_expedited IN (0,1))",
        "priority_reason": "TEXT NOT NULL DEFAULT ''",
        "priority_changed_by": "INTEGER",
        "priority_changed_by_name": "TEXT NOT NULL DEFAULT ''",
        "priority_changed_at": "TEXT NOT NULL DEFAULT ''",
        "priority_effective_at": "TEXT NOT NULL DEFAULT ''",
        # The previous intent is kept separately so a future-dated change can
        # be scheduled without making the new value effective prematurely.
        # V084 is not deployed yet, therefore these columns can be introduced
        # here and seeded from the current values below.
        "previous_priority_level": "INTEGER NOT NULL DEFAULT 3 CHECK(previous_priority_level BETWEEN 1 AND 5)",
        "previous_is_expedited": "INTEGER NOT NULL DEFAULT 0 CHECK(previous_is_expedited IN (0,1))",
        "schedule_policy": "TEXT NOT NULL DEFAULT 'auto' CHECK(schedule_policy IN ('auto','no_split','allow_split','allow_cross_day'))",
        "priority_version": "INTEGER NOT NULL DEFAULT 1 CHECK(priority_version >= 1)",
        "schedule_replan_required": "INTEGER NOT NULL DEFAULT 0 CHECK(schedule_replan_required IN (0,1))",
        "schedule_replan_reason": "TEXT NOT NULL DEFAULT ''",
    }.items():
        add_column_if_missing(db, "orders", column, definition)

    # Preserve the pre-change scheduling intent for already-existing orders.
    # This also makes the migration safe for databases where the newly-added
    # columns were materialized with their SQL defaults (P3 / non-expedited).
    db.execute(
        "UPDATE orders SET previous_priority_level=priority_level, "
        "previous_is_expedited=is_expedited "
        "WHERE previous_priority_level=3 AND previous_is_expedited=0 "
        "AND (priority_level<>3 OR is_expedited<>0)"
    )

    db.execute("CREATE INDEX IF NOT EXISTS idx_orders_priority ON orders(priority_level, is_expedited, deadline)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_orders_schedule_policy ON orders(schedule_policy, status)")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_schedule_replan_queue "
        "ON orders(schedule_replan_required,priority_level,is_expedited,deadline)"
    )
    _create_history_table(db)

    for column, definition in {
        "priority_level_snapshot": "INTEGER NOT NULL DEFAULT 3 CHECK(priority_level_snapshot BETWEEN 1 AND 5)",
        "is_expedited_snapshot": "INTEGER NOT NULL DEFAULT 0 CHECK(is_expedited_snapshot IN (0,1))",
        "priority_version_snapshot": "INTEGER NOT NULL DEFAULT 1 CHECK(priority_version_snapshot >= 1)",
        "priority_effective_at_snapshot": "TEXT NOT NULL DEFAULT ''",
        "schedule_policy_snapshot": "TEXT NOT NULL DEFAULT 'auto' CHECK(schedule_policy_snapshot IN ('auto','no_split','allow_split','allow_cross_day'))",
    }.items():
        add_column_if_missing(db, "schedule_revisions", column, definition)

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_auto_plan_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            auto_plan_key TEXT NOT NULL UNIQUE,
            requested_start_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'started'
                CHECK(status IN ('started','completed','failed')),
            input_digest TEXT NOT NULL,
            input_json TEXT NOT NULL,
            result_digest TEXT NOT NULL DEFAULT '',
            result_json TEXT NOT NULL DEFAULT '{}',
            created_by INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            completed_at TEXT NOT NULL DEFAULT '',
            CHECK(length(trim(auto_plan_key)) > 0),
            CHECK(length(trim(input_digest)) = 64)
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_schedule_auto_plan_runs_status "
        "ON schedule_auto_plan_runs(status,created_at)"
    )
    # Keep a durable failure reason for an automatic-plan attempt.  The table
    # was introduced together with V084, but this additive guard also upgrades
    # databases that materialized an early V084 draft without the column.
    add_column_if_missing(
        db, "schedule_auto_plan_runs", "error_message",
        "TEXT NOT NULL DEFAULT ''",
    )

    rows = db.execute(
        "SELECT id,order_no,created_at,priority_level,is_expedited,deadline,"
        "priority_effective_at,schedule_policy,priority_reason,priority_version "
        "FROM orders ORDER BY id"
    ).fetchall()
    for row in rows:
        snapshot = _history_snapshot(row)
        digest = _snapshot_digest({"event": "baseline", **snapshot})
        db.execute(
            """
            INSERT OR IGNORE INTO order_priority_history (
                order_id,order_no_snapshot,event_type,
                old_priority_level,new_priority_level,old_is_expedited,new_is_expedited,
                old_deadline,new_deadline,old_priority_effective_at,new_priority_effective_at,
                old_schedule_policy,new_schedule_policy,old_priority_reason,new_priority_reason,
                change_reason,changed_by,changed_by_name,changed_at,priority_version,snapshot_digest
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["id"], row["order_no"] or "", "baseline",
                None, snapshot["priority_level"], None, snapshot["is_expedited"],
                "", snapshot["deadline"], "", snapshot["priority_effective_at"],
                "auto", snapshot["schedule_policy"], "", snapshot["priority_reason"],
                "V084 baseline snapshot", None, "system",
                row["created_at"] or "1970-01-01 00:00:00", snapshot["priority_version"], digest,
            ),
        )


MIGRATIONS = [
    (84, "Add order priority and scheduling change history", m084_order_priority),
]
