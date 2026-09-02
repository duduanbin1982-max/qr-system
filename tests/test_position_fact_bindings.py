"""Exact position-version bindings for work and performance facts."""

import uuid

import pytest

from modules.db import get_db
from modules.services.performance_configuration_service import (
    PerformanceConfigurationService,
)
from modules.services.performance_fact_collector import PerformanceFactCollector
from tests.test_performance_configuration import _prepare_actor
from tests.test_performance_fact_collector import _batch, _order, _worker
from tests.test_performance_ledger import _create, _setup
from tests.test_scan_flow import _seed_order_mode_two_step_order


def _position_root(db, name):
    position_id = db.execute(
        "INSERT INTO positions(name,description,status,lifecycle_status) "
        "VALUES (?,'','inactive','active')",
        (name,),
    ).lastrowid
    return position_id


def _position_version(
    db,
    position_id,
    name,
    *,
    version=1,
    status="published",
    effective_from="2026-01-01 07:00:00",
    effective_to="",
    process_ids=(),
    supersedes_version_id=None,
):
    position_code = db.execute(
        "SELECT position_code FROM positions WHERE id=?", (position_id,)
    ).fetchone()["position_code"]
    version_id = db.execute(
        "INSERT INTO position_versions("
        "position_id,version,position_code_snapshot,name,status,effective_from,"
        "effective_to,supersedes_version_id,content_digest,published_at) "
        "VALUES (?,?,?,?,'draft',?,?,?,?,?)",
        (
            position_id,
            version,
            position_code,
            name,
            effective_from,
            effective_to,
            supersedes_version_id,
            f"position-fact-{position_id}-{version}-{uuid.uuid4().hex}",
            effective_from,
        ),
    ).lastrowid
    for sequence, process_id in enumerate(process_ids, start=1):
        db.execute(
            "INSERT INTO position_version_processes("
            "position_version_id,process_id,seq_order) VALUES (?,?,?)",
            (version_id, process_id, sequence),
        )
        db.execute(
            "INSERT OR IGNORE INTO position_processes(position_id,process_id) "
            "VALUES (?,?)",
            (position_id, process_id),
        )
    db.execute(
        "UPDATE position_versions SET status=? WHERE id=?", (status, version_id)
    )
    root_status = "inactive" if status == "retired" else "active"
    lifecycle_status = "retired" if status == "retired" else "active"
    db.execute(
        "UPDATE positions SET name=?,status=?,lifecycle_status=?,"
        "current_effective_version_id=? WHERE id=?",
        (name, root_status, lifecycle_status, version_id, position_id),
    )
    return version_id


@pytest.mark.parametrize("endpoint", ["/api/mobile/report", "/api/report"])
def test_work_report_binds_authenticated_position_version_and_rejects_spoofing(
    client, worker_auth_headers, endpoint
):
    order_id, _, process_ids = _seed_order_mode_two_step_order(client)
    with client.application.app_context():
        db = get_db()
        worker = db.execute(
            "SELECT id FROM users WHERE username='testworker'"
        ).fetchone()
        position_name = "认证岗位-" + uuid.uuid4().hex[:8]
        position_id = _position_root(db, position_name)
        version_id = _position_version(
            db,
            position_id,
            position_name,
            process_ids=(process_ids[0],),
        )
        spoofed_position_id = db.execute(
            "INSERT INTO positions(name,status) VALUES ('伪造岗位','active')"
        ).lastrowid
        db.execute(
            "UPDATE users SET position_id=? WHERE id=?", (position_id, worker["id"])
        )
        db.commit()

    response = client.post(
        endpoint,
        headers=worker_auth_headers,
        json={
            "order_id": order_id,
            "process_id": process_ids[0],
            "quantity": 1,
            "report_type": "normal",
            "actual_completed_at": "2026-08-20 12:00:00",
            "submit_position_id": spoofed_position_id,
            "submit_position_name": "伪造岗位名称",
        },
    )

    assert response.status_code == 200, response.get_json()
    with client.application.app_context():
        row = get_db().execute(
            "SELECT submit_position_id,submit_position_version_id,"
            "submit_position_name FROM work_records WHERE order_id=? "
            "ORDER BY id DESC LIMIT 1",
            (order_id,),
        ).fetchone()
    assert row["submit_position_id"] == position_id
    assert row["submit_position_version_id"] == version_id
    assert row["submit_position_name"] == position_name


def test_new_legacy_work_report_uses_authenticated_root_name(client, worker_auth_headers):
    order_id, _, process_ids = _seed_order_mode_two_step_order(client)
    with client.application.app_context():
        db = get_db()
        worker = db.execute(
            "SELECT id FROM users WHERE username='testworker'"
        ).fetchone()
        position_name = "Legacy 认证岗位"
        position_id = db.execute(
            "INSERT INTO positions(name,status) VALUES (?,'active')", (position_name,)
        ).lastrowid
        db.execute(
            "INSERT INTO position_processes(position_id,process_id) VALUES (?,?)",
            (position_id, process_ids[0]),
        )
        db.execute(
            "UPDATE users SET position_id=? WHERE id=?", (position_id, worker["id"])
        )
        db.commit()

    response = client.post(
        "/api/report",
        headers=worker_auth_headers,
        json={
            "order_id": order_id,
            "process_id": process_ids[0],
            "quantity": 1,
            "report_type": "normal",
            "actual_completed_at": "2026-08-20 12:00:00",
            "submit_position_name": "伪造岗位名称",
        },
    )

    assert response.status_code == 200, response.get_json()
    with client.application.app_context():
        row = get_db().execute(
            "SELECT submit_position_id,submit_position_version_id,"
            "submit_position_name FROM work_records WHERE order_id=? "
            "ORDER BY id DESC LIMIT 1",
            (order_id,),
        ).fetchone()
    assert row["submit_position_id"] == position_id
    assert row["submit_position_version_id"] is None
    assert row["submit_position_name"] == position_name


def test_retired_historical_wip_binds_current_retired_position_version(
    client, worker_auth_headers
):
    order_id, _, process_ids = _seed_order_mode_two_step_order(client)
    with client.application.app_context():
        db = get_db()
        worker = db.execute(
            "SELECT id FROM users WHERE username='testworker'"
        ).fetchone()
        position_name = "退休历史在制岗位-" + uuid.uuid4().hex[:8]
        position_id = _position_root(db, position_name)
        version_id = _position_version(
            db,
            position_id,
            position_name,
            status="retired",
            effective_from="2026-01-01 07:00:00",
            effective_to="2026-08-01 07:00:00",
            process_ids=(process_ids[0],),
        )
        db.execute(
            "UPDATE users SET position_id=? WHERE id=?", (position_id, worker["id"])
        )
        db.commit()

    response = client.post(
        "/api/mobile/report",
        headers=worker_auth_headers,
        json={
            "order_id": order_id,
            "process_id": process_ids[0],
            "quantity": 1,
            "report_type": "normal",
            "actual_completed_at": "2026-08-20 12:00:00",
        },
    )

    assert response.status_code == 200, response.get_json()
    with client.application.app_context():
        row = get_db().execute(
            "SELECT submit_position_id,submit_position_version_id,"
            "submit_position_name FROM work_records WHERE order_id=? "
            "ORDER BY id DESC LIMIT 1",
            (order_id,),
        ).fetchone()
    assert row["submit_position_id"] == position_id
    assert row["submit_position_version_id"] == version_id
    assert row["submit_position_name"] == position_name


def test_performance_work_fact_keeps_exact_position_version(client):
    with client.application.app_context():
        db = get_db()
        user_id, position_id, _ = _worker(db, "position-version")
        order_id, _ = _order(db, "position-version")
        process_id = db.execute(
            "INSERT INTO processes(name,status) VALUES ('绩效精确岗位工序','active')"
        ).lastrowid
        version_name = "绩效精确岗位 V1"
        version_id = _position_version(db, position_id, version_name)
        work_id = db.execute(
            "INSERT INTO work_records("
            "order_id,process_id,user_id,type,status,quantity,actual_completed_at,"
            "created_at,submit_position_id,submit_position_version_id,submit_position_name) "
            "VALUES (?,?,?,'normal','approved',1,?,?,?,?,?)",
            (
                order_id,
                process_id,
                user_id,
                "2026-08-10 08:00:00",
                "2026-08-10 08:01:00",
                position_id,
                version_id,
                version_name,
            ),
        ).lastrowid
        batch_id = _batch(db, "position-version")

        result = PerformanceFactCollector.collect(batch_id, db=db)

        fact = next(
            item
            for item in result["facts"]
            if item["source_type"] == "work_record" and item["source_id"] == work_id
        )
        assert fact["position_id_snapshot"] == position_id
        assert fact["position_version_id"] == version_id
        assert fact["position_name_snapshot"] == version_name


def test_legacy_work_fact_with_null_version_preserves_saved_position_name(client):
    with client.application.app_context():
        db = get_db()
        user_id, position_id, _ = _worker(db, "legacy-position")
        order_id, _ = _order(db, "legacy-position")
        process_id = db.execute(
            "INSERT INTO processes(name,status) VALUES ('Legacy 岗位工序','active')"
        ).lastrowid
        work_id = db.execute(
            "INSERT INTO work_records("
            "order_id,process_id,user_id,type,status,quantity,actual_completed_at,"
            "created_at,submit_position_id,submit_position_name) "
            "VALUES (?,?,?,'normal','approved',1,?,?,?,?)",
            (
                order_id,
                process_id,
                user_id,
                "2026-08-10 08:00:00",
                "2026-08-10 08:01:00",
                position_id,
                "历史旧岗位名",
            ),
        ).lastrowid
        db.execute(
            "UPDATE positions SET name='当前新岗位名' WHERE id=?", (position_id,)
        )
        batch_id = _batch(db, "legacy-position")

        result = PerformanceFactCollector.collect(batch_id, db=db)

        fact = next(
            item
            for item in result["facts"]
            if item["source_type"] == "work_record" and item["source_id"] == work_id
        )
        assert fact["position_version_id"] is None
        assert fact["position_name_snapshot"] == "历史旧岗位名"


def test_position_target_binds_current_published_version_for_retrospective_month(
    client,
):
    with client.application.app_context():
        db = get_db()
        preparer = _prepare_actor(db, "position-version-target")
        position_id = _position_root(db, "岗位目标根")
        version_id = _position_version(
            db,
            position_id,
            "岗位目标当前发布版",
            effective_from="2026-08-01 07:00:00",
        )
        db.commit()

        target = PerformanceConfigurationService.create_position_target_version(
            {
                "position_id": position_id,
                "target_output_qty": 500,
                "minimum_effective_work_days": 15,
                "effective_from_month": "2026-06",
                "effective_to_month": "2026-09",
            },
            preparer,
            db=db,
        )

        assert target["position_version_id_snapshot"] == version_id
        assert target["position_name_snapshot"] == "岗位目标当前发布版"


def test_monthly_score_uses_position_version_at_month_end(client):
    with client.application.app_context():
        db = get_db()
        actor, _, position_id, _, user_ids = _setup(db, "month-end-version")
        first_version_id = _position_version(
            db,
            position_id,
            "月中旧岗位版本",
            status="superseded",
            effective_from="2026-01-01 07:00:00",
            effective_to="2026-07-20 07:00:00",
        )
        second_version_id = _position_version(
            db,
            position_id,
            "月末新岗位版本",
            version=2,
            effective_from="2026-07-20 07:00:00",
            supersedes_version_id=first_version_id,
        )
        db.commit()

        created = _create(actor, "position-fact:month-end-version")
        fact = db.execute(
            "SELECT position_version_id,position_name_snapshot "
            "FROM performance_source_facts WHERE batch_id=? AND user_id=? "
            "AND fact_type='work' ORDER BY id LIMIT 1",
            (created["batch_id"], user_ids[0]),
        ).fetchone()
        score = db.execute(
            "SELECT position_version_id_snapshot,position_name_snapshot "
            "FROM performance_score_revisions WHERE batch_id=? AND user_id=?",
            (created["batch_id"], user_ids[0]),
        ).fetchone()

        assert fact["position_version_id"] == first_version_id
        assert fact["position_name_snapshot"] == "月中旧岗位版本"
        assert score["position_version_id_snapshot"] == second_version_id
        assert score["position_name_snapshot"] == "月末新岗位版本"


def test_legacy_score_inputs_preserve_saved_position_snapshot(client):
    with client.application.app_context():
        db = get_db()
        actor, _, position_id, _, user_ids = _setup(db, "legacy-score-position")
        saved_name = db.execute(
            "SELECT position_name_snapshot FROM performance_assignment_history "
            "WHERE user_id=?",
            (user_ids[0],),
        ).fetchone()["position_name_snapshot"]
        db.execute(
            "UPDATE positions SET name='当前已改名岗位' WHERE id=?", (position_id,)
        )
        db.commit()

        created = _create(actor, "position-fact:legacy-score-position")
        score = db.execute(
            "SELECT position_version_id_snapshot,position_name_snapshot "
            "FROM performance_score_revisions WHERE batch_id=? AND user_id=?",
            (created["batch_id"], user_ids[0]),
        ).fetchone()

        assert score["position_version_id_snapshot"] is None
        assert score["position_name_snapshot"] == saved_name
