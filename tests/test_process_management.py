import json
import sqlite3
import uuid

import pytest

from factories import TEST_HASH, ensure_route_version
from modules.db import get_db
from modules.services.position_service import PositionService


def _insert_process(db, name, *, category="结构件", status="active", seq_order=1):
    return db.execute(
        "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
        "VALUES (?, 'process management fixture', ?, ?, ?, datetime('now','localtime'))",
        (name, category, seq_order, status),
    ).lastrowid


def _insert_route(db, process_ids, *, category="结构件", status="active"):
    route_id = db.execute(
        "INSERT INTO process_routes (name, description, status, category) VALUES (?, '', ?, ?)",
        (f"Process Route {uuid.uuid4().hex[:8]}", status, category),
    ).lastrowid
    for seq_order, process_id in enumerate(process_ids, start=1):
        db.execute(
            "INSERT INTO process_route_items (route_id, process_id, seq_order, required_audit) "
            "VALUES (?, ?, ?, 0)",
            (route_id, process_id, seq_order),
        )
    return route_id


def _insert_order(db, process_ids):
    order_id = db.execute(
        "INSERT INTO orders (order_no, customer, product_name, quantity, status) "
        "VALUES (?, 'Process Customer', 'Process Product', 1, 'pending')",
        (f"PROC-{uuid.uuid4().hex[:10].upper()}",),
    ).lastrowid
    for seq_order, process_id in enumerate(process_ids, start=1):
        db.execute(
            "INSERT INTO order_processes (order_id, process_id, seq_order) VALUES (?, ?, ?)",
            (order_id, process_id, seq_order),
        )
    return order_id


def _login_with_permissions(client, permissions, process_ids=()):
    suffix = uuid.uuid4().hex[:8]
    username = f"process-user-{suffix}"
    with client.application.app_context():
        db = get_db()
        role_id = db.execute(
            "INSERT INTO roles (name, code, description, permissions, status, level) "
            "VALUES (?, ?, '', ?, 'active', 1)",
            (f"Process Role {suffix}", f"process_role_{suffix}", json.dumps(permissions)),
        ).lastrowid
        user_id = db.execute(
            "INSERT INTO users (username, password, name, role, employee_no, status, "
            "password_version, must_change_password) VALUES (?, ?, ?, 'worker', ?, 'active', 2, 0)",
            (username, TEST_HASH, f"Process User {suffix}", f"PROC-{suffix}"),
        ).lastrowid
        db.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, role_id))
        for process_id in process_ids:
            db.execute(
                "INSERT INTO user_processes (user_id, process_id) VALUES (?, ?)",
                (user_id, process_id),
            )
        db.commit()

    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "Test@1234"},
    )
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    token = data.get("token") or data["user"]["token"]
    return {"Authorization": f"Bearer {token}"}


def test_delete_rejects_work_time_reference_and_preserves_rows(client, auth_headers):
    with client.application.app_context():
        db = get_db()
        process_id = _insert_process(db, "工时删除保护")
        standard_id = db.execute(
            "INSERT INTO work_time_standards (process_id, standard_minutes_per_unit) "
            "VALUES (?, 12)",
            (process_id,),
        ).lastrowid
        db.commit()

    impact = client.get(f"/api/processes/{process_id}/impact", headers=auth_headers)
    assert impact.status_code == 200, impact.get_json()
    assert impact.get_json()["impact"]["work_time_standards"] == 1

    response = client.delete(f"/api/processes/{process_id}", headers=auth_headers)
    assert response.status_code == 409, response.get_json()
    assert "只能停用" in response.get_json()["error"]

    with client.application.app_context():
        db = get_db()
        assert db.execute("SELECT id FROM processes WHERE id = ?", (process_id,)).fetchone()
        assert db.execute(
            "SELECT id FROM work_time_standards WHERE id = ?", (standard_id,)
        ).fetchone()


def test_process_impact_includes_price_payroll_and_performance_references(
    client, auth_headers
):
    with client.application.app_context():
        db = get_db()
        process_id = _insert_process(db, "跨模块影响目录")
        route_id = _insert_route(db, [process_id])
        route_version_id = ensure_route_version(db, route_id)
        process_version_id = db.execute(
            "SELECT process_version_id FROM process_route_version_items "
            "WHERE route_version_id=? AND process_id=?",
            (route_version_id, process_id),
        ).fetchone()["process_version_id"]
        db.execute(
            "INSERT INTO route_price_versions ("
            "route_id, route_version_id, process_id, process_version_id, "
            "normal_unit_price_micros, valid_from, status) "
            "VALUES (?, ?, ?, ?, 12000, '2026-08-01 07:00:00', 'draft')",
            (route_id, route_version_id, process_id, process_version_id),
        )
        db.execute(
            "INSERT INTO performance_quality_events "
            "(event_type, quantity, process_id, business_at) "
            "VALUES ('quality_inspection', 1, ?, '2026-08-12 08:00:00')",
            (process_id,),
        )
        batch_id = db.execute(
            "INSERT INTO payroll_batches ("
            "payroll_month, version, period_start, period_end, source_cutoff_at) "
            "VALUES ('2026-08', 99, '2026-08-01 07:00:00', "
            "'2026-09-01 07:00:00', '2026-09-01 07:00:00')"
        ).lastrowid
        employee_line_id = db.execute(
            "INSERT INTO payroll_employee_lines ("
            "batch_id, employee_name_snapshot, employee_no_snapshot) "
            "VALUES (?, '影响测试员工', 'IMPACT-001')",
            (batch_id,),
        ).lastrowid
        db.execute(
            "INSERT INTO payroll_detail_lines ("
            "batch_id, employee_line_id, source_type, source_id, route_id, process_id) "
            "VALUES (?, ?, 'legacy_snapshot', 990001, ?, ?)",
            (batch_id, employee_line_id, route_id, process_id),
        )
        db.commit()

    response = client.get(f"/api/processes/{process_id}/impact", headers=auth_headers)
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["impact"]["route_price_versions"] == 1
    assert payload["impact"]["performance_quality_events"] == 1
    assert payload["impact"]["payroll_detail_lines"] == 1
    references = {item["key"]: item for item in payload["references"]}
    assert references["price_versions"]["label"] == "工价版本"
    assert references["performance_quality_events"]["label"] == "绩效质量事件"
    assert references["payroll_details"]["label"] == "工资明细台账"
    assert payload["is_locked"] is True


def test_database_trigger_blocks_non_fk_process_reference(client):
    with client.application.app_context():
        db = get_db()
        process_id = _insert_process(db, "在制品删除保护")
        order_id = _insert_order(db, [])
        db.execute(
            "INSERT INTO product_items (serial_no, order_id, current_process_id) VALUES (?, ?, ?)",
            (f"SERIAL-{uuid.uuid4().hex[:8]}", order_id, process_id),
        )
        db.commit()

        with pytest.raises(sqlite3.IntegrityError, match="deactivate"):
            db.execute("DELETE FROM processes WHERE id = ?", (process_id,))
        db.rollback()
        assert db.execute("SELECT id FROM processes WHERE id = ?", (process_id,)).fetchone()


def test_inactive_process_cannot_be_added_to_route_position_or_order(client, auth_headers):
    with client.application.app_context():
        db = get_db()
        process_id = _insert_process(db, "停用工序", status="inactive")
        db.commit()

        with pytest.raises(ValueError, match="已停用"):
            PositionService.create_position({
                "name": f"停用岗位-{uuid.uuid4().hex[:6]}",
                "process_ids": [process_id],
            })

    route_response = client.post(
        "/api/process-routes",
        headers=auth_headers,
        json={
            "name": f"停用路线-{uuid.uuid4().hex[:6]}",
            "category": "结构件",
            "processes": [{"process_id": process_id, "required_audit": 0}],
        },
    )
    assert route_response.status_code == 400, route_response.get_json()
    assert "停用工序" in route_response.get_json()["error"]

    order_response = client.post(
        "/api/orders",
        headers=auth_headers,
        json={
            "order_no": f"INACTIVE-{uuid.uuid4().hex[:8].upper()}",
            "customer": "Process Customer",
            "product_name": "Process Product",
            "quantity": 1,
            "process_ids": [process_id],
        },
    )
    assert order_response.status_code == 400, order_response.get_json()
    assert "停用工序" in order_response.get_json()["error"]


def test_route_rejects_process_from_another_category(client, auth_headers):
    with client.application.app_context():
        db = get_db()
        process_id = _insert_process(db, "机加工分类校验", category="机加工")
        db.commit()

    response = client.post(
        "/api/process-routes",
        headers=auth_headers,
        json={
            "name": f"分类错配-{uuid.uuid4().hex[:6]}",
            "category": "结构件",
            "processes": [{"process_id": process_id, "required_audit": 0}],
        },
    )
    assert response.status_code == 400, response.get_json()
    assert "分类不一致" in response.get_json()["error"]


def test_route_apply_requires_order_edit_permission(client):
    with client.application.app_context():
        db = get_db()
        process_id = _insert_process(db, "路线权限工序")
        route_id = _insert_route(db, [process_id])
        order_id = _insert_order(db, [])
        db.commit()
    headers = _login_with_permissions(client, ["routes:edit"])

    response = client.post(
        f"/api/process-routes/{route_id}/apply",
        headers=headers,
        json={"order_id": order_id},
    )
    assert response.status_code == 403, response.get_json()


def test_route_apply_enforces_order_process_data_scope(client):
    with client.application.app_context():
        db = get_db()
        allowed_process_id = _insert_process(db, "数据范围允许工序")
        target_process_id = _insert_process(db, "数据范围目标工序", seq_order=2)
        route_id = _insert_route(db, [target_process_id])
        order_id = _insert_order(db, [target_process_id])
        db.commit()
    headers = _login_with_permissions(
        client,
        ["routes:edit", "orders:edit"],
        process_ids=[allowed_process_id],
    )

    response = client.post(
        f"/api/process-routes/{route_id}/apply",
        headers=headers,
        json={"order_id": order_id},
    )
    assert response.status_code == 403, response.get_json()
    assert "无权限访问此订单" in response.get_json()["error"]


def test_route_apply_uses_order_sync_service(client, auth_headers):
    with client.application.app_context():
        db = get_db()
        old_process_id = _insert_process(db, "原订单工序")
        new_process_id = _insert_process(db, "新路线工序", seq_order=2)
        route_id = _insert_route(db, [new_process_id])
        order_id = _insert_order(db, [old_process_id])
        ensure_route_version(db, route_id)
        db.commit()

    response = client.post(
        f"/api/process-routes/{route_id}/apply",
        headers=auth_headers,
        json={"order_id": order_id},
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["processes_count"] == 1

    with client.application.app_context():
        db = get_db()
        order = db.execute("SELECT route_id FROM orders WHERE id = ?", (order_id,)).fetchone()
        process_ids = [
            row["process_id"]
            for row in db.execute(
                "SELECT process_id FROM order_processes WHERE order_id = ?", (order_id,)
            ).fetchall()
        ]
    assert order["route_id"] == route_id
    assert process_ids == [new_process_id]
