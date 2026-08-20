import uuid

import pytest

from factories import ensure_route_version
from modules.db import get_db
from modules.domain.position_versioning import (
    PositionActiveEmployeesError,
    PositionActiveSessionsError,
    PositionNotFoundError,
    PositionReferenceConflictError,
)
from modules.services.position_impact_service import PositionImpactService


def _seed_position_impact_graph(db):
    suffix = uuid.uuid4().hex[:10]
    position_id = db.execute(
        "INSERT INTO positions(name,description,status) VALUES (?, '', 'active')",
        (f"影响岗位-{suffix}",),
    ).lastrowid
    process_id = db.execute(
        "INSERT INTO processes(name,description,category,seq_order,status,updated_at) "
        "VALUES (?, '', '结构件', 1, 'active', datetime('now','localtime'))",
        (f"影响工序-{suffix}",),
    ).lastrowid
    version_id = db.execute(
        "INSERT INTO position_versions("
        "position_id,version,position_code_snapshot,name,status,content_digest) "
        "VALUES (?,1,?,?,'draft',?)",
        (position_id, f"POS-{position_id:04d}", f"影响岗位-{suffix}", suffix),
    ).lastrowid
    db.execute(
        "INSERT INTO position_processes(position_id,process_id) VALUES (?,?)",
        (position_id, process_id),
    )
    db.execute(
        "INSERT INTO position_version_processes("
        "position_version_id,process_id,seq_order) VALUES (?,?,1)",
        (version_id, process_id),
    )
    db.execute(
        "UPDATE position_versions SET status='published' WHERE id=?",
        (version_id,),
    )
    db.execute(
        "UPDATE positions SET lifecycle_status='active',"
        "current_effective_version_id=? WHERE id=?",
        (version_id, position_id),
    )

    users = {}
    for state, status, deleted_at in (
        ("active", "active", None),
        ("inactive", "inactive", None),
        ("deleted", "inactive", "2026-08-20 09:00:00"),
    ):
        users[state] = db.execute(
            "INSERT INTO users(username,password,name,role,employee_no,status,"
            "position_id,deleted_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                f"impact-{state}-{suffix}",
                "hash",
                f"影响员工-{state}",
                "worker",
                f"IMPACT-{state}-{suffix}",
                status,
                position_id,
                deleted_at,
            ),
        ).lastrowid
    db.execute(
        "INSERT INTO user_sessions(user_id,token,is_active,active_position_id) "
        "VALUES (?,?,1,?)",
        (users["active"], f"impact-session-{suffix}", position_id),
    )
    db.execute(
        "INSERT INTO performance_assignment_history("
        "user_id,position_id,position_name_snapshot,valid_from,source_key,"
        "position_version_id) VALUES (?,?,?,'2026-08-01 07:00:00',?,?)",
        (
            users["active"],
            position_id,
            f"影响岗位-{suffix}",
            f"impact-assignment-{suffix}",
            version_id,
        ),
    )
    target_id = db.execute(
        "INSERT INTO performance_position_target_versions("
        "position_id,position_name_snapshot,target_output_qty,"
        "minimum_effective_work_days,effective_from_month,status,"
        "position_version_id_snapshot) VALUES (?,?,100,15,'2026-08','draft',?)",
        (position_id, f"影响岗位-{suffix}", version_id),
    ).lastrowid
    batch_id = db.execute(
        "INSERT INTO performance_batches("
        "production_month,version,period_start,period_end,idempotency_key) "
        "VALUES ('2026-08',1,'2026-08-01 07:00:00','2026-09-01 07:00:00',?)",
        (f"impact-batch-{suffix}",),
    ).lastrowid
    db.execute(
        "INSERT INTO performance_source_facts("
        "batch_id,fact_type,source_type,source_id,user_id,position_id_snapshot,"
        "position_name_snapshot,source_digest,position_version_id) "
        "VALUES (?,'work','work_record',?,?,?,? ,?,?)",
        (
            batch_id,
            800000 + position_id,
            users["active"],
            position_id,
            f"影响岗位-{suffix}",
            f"fact-{suffix}",
            version_id,
        ),
    )
    db.execute(
        "INSERT INTO performance_score_revisions("
        "batch_id,user_id,revision,position_id_snapshot,position_name_snapshot,"
        "position_target_version_id,position_version_id_snapshot) "
        "VALUES (?,?,1,?,?,?,?)",
        (
            batch_id,
            users["active"],
            position_id,
            f"影响岗位-{suffix}",
            target_id,
            version_id,
        ),
    )

    order_id = db.execute(
        "INSERT INTO orders(order_no,product_name,quantity,status) "
        "VALUES (?, '影响产品', 1, 'producing')",
        (f"IMPACT-ORDER-{suffix}",),
    ).lastrowid
    db.execute(
        "INSERT INTO order_processes(order_id,process_id,seq_order,status) "
        "VALUES (?,?,1,'pending')",
        (order_id, process_id),
    )
    db.execute(
        "INSERT INTO work_records("
        "order_id,process_id,user_id,status,quantity,submit_position_id,"
        "submit_position_version_id) VALUES (?,?,?,'approved',1,?,?)",
        (order_id, process_id, users["active"], position_id, version_id),
    )

    route_id = db.execute(
        "INSERT INTO process_routes(name,description,category,status) "
        "VALUES (?, '', '结构件', 'active')",
        (f"影响路线-{suffix}",),
    ).lastrowid
    db.execute(
        "INSERT INTO process_route_items(route_id,process_id,seq_order) "
        "VALUES (?,?,1)",
        (route_id, process_id),
    )
    ensure_route_version(db, route_id)
    db.commit()
    return {
        "position_id": position_id,
        "version_id": version_id,
        "users": users,
    }


def test_impact_includes_direct_and_scoped_indirect_references(client):
    with client.application.app_context():
        db = get_db()
        seeded = _seed_position_impact_graph(db)
        result = PositionImpactService.summarize(seeded["position_id"], db=db)
        replay = PositionImpactService.summarize(seeded["position_id"], db=db)

    categories = {item["key"]: item for item in result["categories"]}
    assert set(categories) >= {
        "active_employees",
        "inactive_employees",
        "deleted_employees",
        "active_sessions",
        "current_position_processes",
        "historical_position_processes",
        "assignment_history",
        "source_facts",
        "score_revisions",
        "target_versions",
        "work_records",
        "open_orders",
        "current_routes",
    }
    assert all(categories[key]["count"] == 1 for key in categories)
    assert result["total"] == 13
    assert result["impact_digest"] == replay["impact_digest"]
    assert {item["key"] for item in result["blockers"]} == {
        "active_employees",
        "active_sessions",
        "inactive_employees",
        "deleted_employees",
        "historical_position_processes",
        "assignment_history",
        "source_facts",
        "score_revisions",
        "target_versions",
        "work_records",
    }


def test_retirement_and_delete_assertions_fail_closed(client):
    with client.application.app_context():
        db = get_db()
        seeded = _seed_position_impact_graph(db)
        position_id = seeded["position_id"]

        with pytest.raises(PositionActiveEmployeesError):
            PositionImpactService.assert_retirable(position_id, db=db)
        db.execute(
            "UPDATE users SET status='inactive' WHERE id=?",
            (seeded["users"]["active"],),
        )
        with pytest.raises(PositionActiveSessionsError):
            PositionImpactService.assert_retirable(position_id, db=db)
        db.execute(
            "UPDATE user_sessions SET is_active=0 WHERE active_position_id=?",
            (position_id,),
        )
        assert PositionImpactService.assert_retirable(position_id, db=db)[
            "position_id"
        ] == position_id
        with pytest.raises(PositionReferenceConflictError):
            PositionImpactService.assert_deletable(position_id, db=db)


def test_position_impact_rejects_missing_position(client):
    with client.application.app_context(), pytest.raises(PositionNotFoundError):
        PositionImpactService.summarize(987654321, db=get_db())
