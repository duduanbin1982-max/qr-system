"""Sanitized real-order topology replay for the production-node release gate.

The fixtures intentionally contain production-shaped facts without copying
customer names, employee data, credentials, salaries, attachments, or other
personal/business-sensitive payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType

import pytest

from factories import (
    bind_order_process_versions,
    create_order,
    create_process_route,
    ensure_product,
)
from modules import config
from modules.db import get_db
from modules.services.schedule_capacity_service import ScheduleCapacityService


@dataclass(frozen=True)
class ReplayOrderSpec:
    order_no: str
    product_code: str
    quantity: int
    process_names: tuple[str, ...]
    standard_minutes: tuple[int, ...]
    priority_level: int
    deadline: str
    serial_ids: tuple[str, ...] = ()
    completed_first_process: int = 0


BACKGROUND_ORDER = ReplayOrderSpec(
    order_no="REPLAY-CAPACITY-BASELINE",
    product_code="REPLAY-CAPACITY-BASELINE",
    quantity=2,
    process_names=("焊接",),
    standard_minutes=(90,),
    priority_level=3,
    deadline="2026-09-30",
)

REPLAY_ORDERS = (
    ReplayOrderSpec(
        order_no="REPLAY-ORDER-A",
        product_code="REPLAY-PRODUCT-A",
        quantity=4,
        process_names=("下料", "铆接", "焊接", "抛丸", "打磨", "镗孔", "喷漆"),
        standard_minutes=(35, 50, 80, 25, 30, 60, 40),
        priority_level=1,
        deadline="2026-09-25",
        completed_first_process=1,
    ),
    ReplayOrderSpec(
        order_no="REPLAY-ORDER-B",
        product_code="REPLAY-PRODUCT-B",
        quantity=3,
        process_names=("下料", "铆接", "焊接", "喷漆"),
        standard_minutes=(40, 55, 75, 45),
        priority_level=2,
        deadline="2026-09-27",
    ),
    ReplayOrderSpec(
        order_no="REPLAY-ORDER-C",
        product_code="REPLAY-PRODUCT-C",
        quantity=2,
        process_names=("焊接",),
        standard_minutes=(65,),
        priority_level=3,
        deadline="2026-09-29",
        serial_ids=("REPLAY-C-001", "REPLAY-C-002"),
    ),
)


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value):
    if isinstance(value, MappingProxyType):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _digest(value) -> str:
    encoded = json.dumps(
        _plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _enable_node_engine(monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", True)
    monkeypatch.setattr(config, "LEGACY_PROCESS_LINE_WRITE_BLOCKED", False)


def _seed_order(db, spec: ReplayOrderSpec, *, route_suffix: str):
    process_rows = [
        db.execute("SELECT id FROM processes WHERE name=?", (name,)).fetchone()
        for name in spec.process_names
    ]
    assert all(process_rows), spec.process_names
    process_ids = [int(row["id"]) for row in process_rows]
    route_id = create_process_route(
        db,
        process_ids,
        name=f"Replay route {route_suffix}",
        category="sanitized-replay",
    )
    product_id = ensure_product(
        db,
        product_code=spec.product_code,
        product_name=f"Sanitized product {route_suffix}",
    )
    order_id = create_order(
        db,
        process_ids,
        quantity=spec.quantity,
        product_code=spec.product_code,
    )
    db.execute(
        "UPDATE orders SET order_no=?,product_id=?,product_name=?,route_id=?,"
        "plan_start='2026-09-21',deadline=?,priority_level=?,"
        "is_expedited=?,schedule_policy='allow_cross_day',status='producing' "
        "WHERE id=?",
        (
            spec.order_no,
            product_id,
            f"Sanitized product {route_suffix}",
            route_id,
            spec.deadline,
            spec.priority_level,
            int(spec.priority_level == 1),
            order_id,
        ),
    )
    bind_order_process_versions(db, order_id)
    order = db.execute(
        "SELECT route_version_id FROM orders WHERE id=?", (order_id,)
    ).fetchone()
    route_version_id = int(order["route_version_id"])
    operations = db.execute(
        "SELECT id,process_id,process_version_id,seq_order FROM order_processes "
        "WHERE order_id=? ORDER BY seq_order,id",
        (order_id,),
    ).fetchall()
    standard_ids = []
    for operation, minutes in zip(operations, spec.standard_minutes, strict=True):
        standard_id = db.execute(
            "INSERT INTO work_time_standards "
            "(route_id,route_version_id,process_id,process_version_id,product_id,"
            "standard_minutes_per_unit,setup_minutes,difficulty_factor,status,version) "
            "VALUES (?,?,?,?,?,?,10,1,'active',1)",
            (
                route_id,
                route_version_id,
                operation["process_id"],
                operation["process_version_id"],
                product_id,
                minutes,
            ),
        ).lastrowid
        standard_ids.append(standard_id)

    if spec.serial_ids:
        for position, serial_id in enumerate(spec.serial_ids, start=1):
            db.execute(
                "INSERT INTO product_items "
                "(serial_no,order_id,order_no,position_no,status) "
                "VALUES (?,?,?,?, 'pending')",
                (serial_id, order_id, spec.order_no, position),
            )

    if spec.completed_first_process:
        first = operations[0]
        actor_id = db.execute(
            "SELECT id FROM users WHERE username='testrunner'"
        ).fetchone()[0]
        db.execute(
            "UPDATE order_processes SET completed=?,status='in_progress' WHERE id=?",
            (spec.completed_first_process, first["id"]),
        )
        db.execute(
            "INSERT INTO work_records "
            "(order_id,process_id,user_id,type,status,quantity) "
            "VALUES (?,?,?,'normal','approved',?)",
            (
                order_id,
                first["process_id"],
                actor_id,
                spec.completed_first_process,
            ),
        )

    db.commit()
    return {
        "order_id": order_id,
        "order_no": spec.order_no,
        "quantity": spec.quantity,
        "serial_ids": list(spec.serial_ids),
        "route_id": route_id,
        "route_version_id": route_version_id,
        "process_versions": [
            {
                "process_id": int(row["process_id"]),
                "process_version_id": int(row["process_version_id"]),
                "standard_id": int(standard_id),
                "standard_minutes": int(minutes),
            }
            for row, standard_id, minutes in zip(
                operations, standard_ids, spec.standard_minutes, strict=True
            )
        ],
        "priority_level": spec.priority_level,
        "deadline": spec.deadline,
    }


def _completed_facts(db, order_ids):
    placeholders = ",".join("?" for _ in order_ids)
    operations = [
        tuple(row)
        for row in db.execute(
            "SELECT order_id,id,completed,scrapped,rework,status "
            f"FROM order_processes WHERE order_id IN ({placeholders}) "
            "ORDER BY order_id,id",
            order_ids,
        ).fetchall()
    ]
    records = [
        tuple(row)
        for row in db.execute(
            "SELECT order_id,process_id,type,status,quantity "
            f"FROM work_records WHERE order_id IN ({placeholders}) "
            "ORDER BY order_id,id",
            order_ids,
        ).fetchall()
    ]
    return operations, records


def _latest_mismatch_count(db):
    return int(
        db.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT mismatch,ROW_NUMBER() OVER (PARTITION BY scope,source_id "
            "ORDER BY observed_at DESC,id DESC) AS rn "
            "FROM production_node_compatibility_observations) "
            "WHERE rn=1 AND mismatch=1"
        ).fetchone()[0]
    )


class RealOrderReplay:
    def __init__(self, application, order_ids, snapshot, completed_before):
        self.application = application
        self.order_ids = tuple(order_ids)
        self.snapshot = _freeze(snapshot)
        self.fixture_digest = _digest(self.snapshot)
        self.completed_before = completed_before

    def run_shadow(self):
        with self.application.app_context():
            db = get_db()
            results = [
                ScheduleCapacityService.generate_order_schedule(
                    order_id,
                    start_date="2026-09-21",
                    schedule_run_key=f"real-order-replay-{order_id}",
                )
                for order_id in self.order_ids
            ]
            assert all(result["ok"] for result in results)
            assert all(
                operation["status"] == "planned"
                for result in results
                for operation in result["operations"]
            )

            placeholders = ",".join("?" for _ in self.order_ids)
            schedule_rows = db.execute(
                "SELECT id,quantity FROM order_process_schedules "
                f"WHERE order_id IN ({placeholders}) ORDER BY id",
                self.order_ids,
            ).fetchall()
            conserved = 0
            allocated_quantity = 0
            scheduled_quantity = 0
            for schedule in schedule_rows:
                allocated = int(
                    db.execute(
                        "SELECT COALESCE(SUM(quantity),0) "
                        "FROM production_node_schedule_allocations WHERE schedule_id=?",
                        (schedule["id"],),
                    ).fetchone()[0]
                )
                quantity = int(schedule["quantity"] or 0)
                scheduled_quantity += quantity
                allocated_quantity += allocated
                conserved += int(allocated == quantity)

            overlap_count = int(
                db.execute(
                    "SELECT COUNT(*) FROM order_process_schedule_segments a "
                    "JOIN order_process_schedule_segments b "
                    "ON a.id<b.id AND a.production_node_id=b.production_node_id "
                    "AND a.segment_start_at<b.segment_end_at "
                    "AND b.segment_start_at<a.segment_end_at "
                    "JOIN production_nodes n ON n.id=a.production_node_id "
                    "WHERE n.capacity_mode='exclusive'"
                ).fetchone()[0]
            )
            serial_split = int(
                db.execute(
                    "SELECT COUNT(*) FROM ("
                    "SELECT schedule_id,serial_id FROM production_node_schedule_allocations "
                    "WHERE serial_id IS NOT NULL AND TRIM(serial_id)<>'' "
                    "GROUP BY schedule_id,serial_id "
                    "HAVING COUNT(DISTINCT production_node_id)>1)"
                ).fetchone()[0]
            )
            completed_after = _completed_facts(db, self.order_ids)
            unmapped = int(
                db.execute(
                    "SELECT COUNT(*) FROM production_node_migration_differences "
                    "WHERE difference_code IN ('missing_mapping','missing_legacy_reference')"
                ).fetchone()[0]
            )
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = len(db.execute("PRAGMA foreign_key_check").fetchall())
            return {
                "fixture_digest": self.fixture_digest,
                "replay_order_count": len(self.order_ids),
                "replay_operation_count": len(schedule_rows),
                "core_node_count": int(
                    db.execute("SELECT COUNT(*) FROM production_nodes").fetchone()[0]
                ),
                "scheduled_quantity": scheduled_quantity,
                "allocated_quantity": allocated_quantity,
                "quantity_conservation_rate": (
                    conserved / len(schedule_rows) if schedule_rows else 1.0
                ),
                "serial_split_violations": serial_split,
                "exclusive_overlap_count": overlap_count,
                "completed_fact_changes": int(completed_after != self.completed_before),
                "unmapped_fact_count": unmapped,
                "latest_compat_mismatch_count": _latest_mismatch_count(db),
                "database_integrity": integrity,
                "foreign_key_error_count": foreign_keys,
            }


@pytest.fixture
def real_order_replay(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        background = _seed_order(db, BACKGROUND_ORDER, route_suffix="CAPACITY")
        ScheduleCapacityService.generate_order_schedule(
            background["order_id"],
            start_date="2026-09-21",
            schedule_run_key="real-order-replay-capacity-baseline",
        )

        downtime_node = db.execute(
            "SELECT n.id,n.legacy_process_line_id FROM production_nodes n "
            "JOIN processes p ON p.id=n.process_id "
            "WHERE p.name='焊接' ORDER BY n.id DESC LIMIT 1"
        ).fetchone()
        db.execute(
            "INSERT INTO production_node_calendar_overrides "
            "(production_node_id,start_at,end_at,override_type,reason,status) "
            "VALUES (?,?,?,'maintenance','sanitized replay downtime','active')",
            (downtime_node["id"], "2026-09-21 08:00", "2026-09-21 10:00"),
        )
        db.execute(
            "INSERT INTO schedule_downtime_events "
            "(process_line_id,production_node_id,start_at,end_at,reason,status,source_type) "
            "VALUES (?,?,?,?,?,'active','fixture')",
            (
                downtime_node["legacy_process_line_id"],
                downtime_node["id"],
                "2026-09-21 08:00",
                "2026-09-21 10:00",
                "sanitized replay downtime",
            ),
        )

        seeded = [
            _seed_order(db, spec, route_suffix=chr(ord("A") + index))
            for index, spec in enumerate(REPLAY_ORDERS)
        ]
        paint_process_version = seeded[0]["process_versions"][-1]
        paint_node = db.execute(
            "SELECT n.id FROM production_nodes n JOIN processes p ON p.id=n.process_id "
            "WHERE p.name='喷漆' ORDER BY n.id LIMIT 1"
        ).fetchone()
        db.execute(
            "INSERT INTO production_node_capabilities "
            "(production_node_id,product_id,route_version_id,process_version_id,"
            "changeover_minutes,status) VALUES (?,?,?,?,15,'active')",
            (
                paint_node["id"],
                db.execute(
                    "SELECT product_id FROM orders WHERE id=?", (seeded[0]["order_id"],)
                ).fetchone()[0],
                seeded[0]["route_version_id"],
                paint_process_version["process_version_id"],
            ),
        )
        db.commit()

        occupancy = [
            dict(row)
            for row in db.execute(
                "SELECT ss.production_node_id,ss.segment_start_at AS start_at,"
                "ss.segment_end_at AS end_at,ss.quantity "
                "FROM order_process_schedule_segments ss "
                "JOIN order_process_schedules s ON s.id=ss.schedule_id "
                "WHERE s.order_id=? ORDER BY ss.id",
                (background["order_id"],),
            ).fetchall()
        ]
        calendars = [
            {
                **dict(row),
                "shifts": [
                    dict(shift)
                    for shift in db.execute(
                        "SELECT shift_code,start_minute,end_minute,status "
                        "FROM schedule_shifts WHERE calendar_id=? "
                        "ORDER BY start_minute,id",
                        (row["id"],),
                    ).fetchall()
                ],
            }
            for row in db.execute(
                "SELECT id,calendar_code,weekly_workdays,status "
                "FROM schedule_calendars ORDER BY id"
            ).fetchall()
        ]
        snapshot = {
            "schema": "sanitized-production-node-replay/v1",
            "as_of": "2026-09-19",
            "orders": seeded,
            "node_capabilities": [
                dict(row)
                for row in db.execute(
                    "SELECT production_node_id,product_id,route_version_id,"
                    "process_version_id,changeover_minutes,status "
                    "FROM production_node_capabilities ORDER BY id"
                ).fetchall()
            ],
            "calendars": calendars,
            "occupancy": occupancy,
            "downtime": [
                {
                    "production_node_id": int(downtime_node["id"]),
                    "start_at": "2026-09-21 08:00",
                    "end_at": "2026-09-21 10:00",
                    "type": "maintenance",
                }
            ],
        }
        order_ids = [item["order_id"] for item in seeded]
        completed_before = _completed_facts(db, order_ids)
    return RealOrderReplay(client.application, order_ids, snapshot, completed_before)


def test_real_order_replay_meets_node_release_gate(real_order_replay):
    report = real_order_replay.run_shadow()

    assert report["core_node_count"] == 21
    assert report["quantity_conservation_rate"] == 1.0
    assert report["serial_split_violations"] == 0
    assert report["exclusive_overlap_count"] == 0
    assert report["completed_fact_changes"] == 0
    assert report["unmapped_fact_count"] == 0
    assert report["latest_compat_mismatch_count"] == 0
    assert report["database_integrity"] == "ok"
    assert report["foreign_key_error_count"] == 0


def test_real_order_replay_fixture_is_sanitized_versioned_and_idempotent(
    real_order_replay,
):
    snapshot = _plain(real_order_replay.snapshot)
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "customer",
        "username",
        "password",
        "salary",
        "attachment",
        "phone",
        "address",
    ):
        assert forbidden not in encoded.casefold()
    assert snapshot["occupancy"]
    assert snapshot["downtime"]
    assert snapshot["node_capabilities"]
    assert all(order["route_version_id"] for order in snapshot["orders"])
    assert all(
        operation["process_version_id"] and operation["standard_id"]
        for order in snapshot["orders"]
        for operation in order["process_versions"]
    )

    first = real_order_replay.run_shadow()
    replay = real_order_replay.run_shadow()
    assert replay == first
    assert replay["fixture_digest"] == real_order_replay.fixture_digest
