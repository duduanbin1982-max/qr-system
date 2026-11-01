"""Order management specific tests — covers all 12 endpoints"""
import json, time, pytest, uuid
from factories import (
    TEST_HASH,
    TEST_PASS,
    add_product_bom,
    create_material,
    bind_order_process_versions,
    ensure_process,
    ensure_process_version,
    ensure_product,
    ensure_user,
)


def _set_order_status(client, order_id, status):
    with client.application.app_context():
        from modules.db import get_db

        db = get_db()
        db.execute(
            "UPDATE orders SET status = ?, deleted_at = NULL WHERE id = ?",
            (status, order_id),
        )
        db.commit()


def _order_no(client, order_id):
    with client.application.app_context():
        from modules.db import get_db

        row = get_db().execute(
            "SELECT order_no FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        return row["order_no"]


def _audit_detail(client, action, order_id):
    with client.application.app_context():
        from modules.db import get_db

        row = get_db().execute(
            "SELECT detail FROM audit_logs WHERE action = ? AND target_type = 'order' "
            "AND target_id = ? ORDER BY id DESC LIMIT 1",
            (action, order_id),
        ).fetchone()
        assert row is not None, f"missing audit log: {action} order={order_id}"
        return row["detail"]


def _order_status(client, order_id):
    with client.application.app_context():
        from modules.db import get_db

        row = get_db().execute(
            "SELECT status FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        return row["status"]


def _first_process_id(client, order_id):
    with client.application.app_context():
        from modules.db import get_db

        row = get_db().execute(
            "SELECT process_id FROM order_processes WHERE order_id = ? ORDER BY seq_order LIMIT 1",
            (order_id,),
        ).fetchone()
        return row["process_id"]


def _listed_order_ids(response):
    return {order["id"] for order in response.get_json()["orders"]}

def _focus_event_count(client, event_type, order_id=None):
    with client.application.app_context():
        from modules.db import get_db

        params = [event_type]
        where = "event_type = ?"
        if order_id is not None:
            where += " AND order_id = ?"
            params.append(order_id)
        row = get_db().execute(
            f"SELECT COUNT(*) AS cnt FROM order_completion_focus_events WHERE {where}",
            params,
        ).fetchone()
        return row["cnt"]


def _login_headers(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.get_json()
    data = response.get_json() or {}
    token = data.get("user", {}).get("token", "") if "user" in data else data.get("token", "")
    assert token
    return {"Authorization": f"Bearer {token}"}


def _seed_completion_focus_pair(client, lead_username=None):
    suffix = uuid.uuid4().hex[:6].upper()
    with client.application.app_context():
        from modules.db import get_db

        db = get_db()
        cursor = db.execute(
            "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
            "VALUES (?, 'pytest fixture process', 'fixture', 1, 'active', datetime('now','localtime'))",
            (f"Fixture Focus Process {suffix}",),
        )
        process_id = cursor.lastrowid
        ensure_process_version(db, process_id)
        product_code = f"XMOD-FOCUS-{suffix}"
        earlier_order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode, created_at) "
            "VALUES (?, 'Test Customer', 'Cross Module Product', ?, 5, 'producing', '', '2026-01-01 08:00:00')",
            (f"TEST-FOCUS-EARLY-{suffix}", product_code),
        ).lastrowid
        later_order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode, created_at) "
            "VALUES (?, 'Test Customer', 'Cross Module Product', ?, 5, 'producing', '', '2026-01-02 08:00:00')",
            (f"TEST-FOCUS-LATE-{suffix}", product_code),
        ).lastrowid
        for order_id in (earlier_order_id, later_order_id):
            db.execute(
                "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
                "VALUES (?, ?, 1, 'pending', 0, 0, 0)",
                (order_id, process_id),
            )
            bind_order_process_versions(db, order_id)
        worker = db.execute("SELECT id FROM users WHERE username = 'testworker'").fetchone()
        assert worker is not None
        db.execute(
            "INSERT OR IGNORE INTO user_processes (user_id, process_id) VALUES (?, ?)",
            (worker["id"], process_id),
        )
        if lead_username:
            lead_user_id = ensure_user(
                db,
                lead_username,
                TEST_HASH,
                "Focus Lead",
                "production_manager",
                f"TEST-FOCUS-LEAD-{suffix}",
                "manager-group",
            )
            db.execute(
                "INSERT OR IGNORE INTO user_processes (user_id, process_id) VALUES (?, ?)",
                (lead_user_id, process_id),
            )
        db.commit()
    return later_order_id, process_id


def _seed_scoped_order_pair(client):
    suffix = uuid.uuid4().hex[:6].upper()
    username = f"order_scope_{suffix.lower()}"
    with client.application.app_context():
        from modules.db import get_db

        db = get_db()
        process_ids = []
        for seq_order in (1, 2):
            process_ids.append(db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES (?, 'order scope fixture', 'fixture', ?, 'active', datetime('now','localtime'))",
                (f"Order Scope Process {suffix}-{seq_order}", 8000 + seq_order),
            ).lastrowid)

        order_ids = []
        for index, process_id in enumerate(process_ids, start=1):
            order_id = db.execute(
                "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status) "
                "VALUES (?, 'Scope Customer', 'Scope Product', ?, 2, 'producing')",
                (f"TEST-ORDER-SCOPE-{suffix}-{index}", f"SCOPE-{suffix}-{index}"),
            ).lastrowid
            db.execute(
                "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed) "
                "VALUES (?, ?, 1, 'pending', 0)",
                (order_id, process_id),
            )
            order_ids.append(order_id)

        user_id = ensure_user(
            db,
            username,
            TEST_HASH,
            "Order Scope Manager",
            "production_manager",
            f"TEST-ORDER-SCOPE-{suffix}",
        )
        db.execute("DELETE FROM user_processes WHERE user_id = ?", (user_id,))
        db.execute(
            "INSERT INTO user_processes (user_id, process_id) VALUES (?, ?)",
            (user_id, process_ids[0]),
        )
        db.commit()
    return username, order_ids, process_ids



class TestOrderCRUD:
    def test_list_orders(self, client, auth_headers):
        resp = client.get("/api/orders", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "orders" in data and "total" in data

    def test_next_order_no(self, client, auth_headers):
        resp = client.get("/api/orders/next-no", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "order_no" in data and len(data["order_no"]) >= 8

    def test_create_and_get_order(self, client, auth_headers):
        order_no = "TEST-ORD-" + str(int(time.time()))
        resp = client.post("/api/orders", headers=auth_headers, json={
            "order_no": order_no,
            "customer": "Test Customer",
            "product_name": "Test Product",
            "quantity": 10
        })
        assert resp.status_code == 200

    def test_duplicate_order_number_is_reallocated(self, client, auth_headers):
        order_no = f"TEST-DUPLICATE-{uuid.uuid4().hex[:8].upper()}"
        payload = {
            "order_no": order_no,
            "customer": "Duplicate Customer",
            "product_name": "Duplicate Product",
            "quantity": 1,
        }

        first = client.post("/api/orders", headers=auth_headers, json=payload)
        second = client.post("/api/orders", headers=auth_headers, json=payload)

        assert first.status_code == 200, first.get_json()
        assert second.status_code == 200, second.get_json()
        first_id = first.get_json()["id"]
        second_id = second.get_json()["id"]
        with client.application.app_context():
            from modules.db import get_db

            rows = get_db().execute(
                "SELECT order_no FROM orders WHERE id IN (?, ?)",
                (first_id, second_id),
            ).fetchall()
        order_numbers = {row["order_no"] for row in rows}
        assert len(order_numbers) == 2
        assert order_no in order_numbers

    def test_create_order_copies_product_bom_snapshot(self, client):
        from modules.db import get_db
        from modules.services.order_service import OrderService

        suffix = uuid.uuid4().hex[:8].upper()
        product_code = f"ORDER-BOM-{suffix}"
        with client.application.app_context():
            db = get_db()
            process_id = ensure_process(db, name=f"Order BOM Process {suffix}")
            product_id = ensure_product(
                db,
                product_code=product_code,
                product_name=f"Order BOM Product {suffix}",
            )
            material_id = create_material(db, name=f"Order BOM Material {suffix}")
            add_product_bom(
                db,
                product_id,
                material_id,
                process_id,
                quantity_per_unit=2.5,
            )
            db.commit()

            order_id, _order_no = OrderService.create_order(
                {
                    "order_no": f"ORDER-BOM-{suffix}",
                    "product_id": product_id,
                    "product_code": product_code,
                    "quantity": 4,
                    "process_ids": [process_id],
                }
            )
            snapshot = db.execute(
                "SELECT material_id, process_id, quantity_per_unit, source "
                "FROM order_materials WHERE order_id = ?",
                (order_id,),
            ).fetchone()

        assert tuple(snapshot) == (material_id, process_id, 2.5, "auto")

    def test_create_order_rolls_back_when_process_assignment_fails(
        self, client, monkeypatch
    ):
        from modules.db import get_db
        from modules.services.order_service import OrderService

        order_no = f"TEST-ROLLBACK-{uuid.uuid4().hex[:8].upper()}"

        def fail_assignment(*_args, **_kwargs):
            raise RuntimeError("process assignment failed")

        monkeypatch.setattr(
            OrderService,
            "_assign_processes",
            staticmethod(fail_assignment),
        )

        with client.application.app_context():
            with pytest.raises(RuntimeError, match="process assignment failed"):
                OrderService.create_order(
                    {
                        "order_no": order_no,
                        "product_name": "Rollback Product",
                        "quantity": 1,
                    }
                )
            row = get_db().execute(
                "SELECT id FROM orders WHERE order_no = ?",
                (order_no,),
            ).fetchone()

        assert row is None

    def test_update_order(self, client, auth_headers, test_order_id):
        resp = client.put(f"/api/orders/{test_order_id}", headers=auth_headers, json={
            "remark": "Updated by test"
        })
        assert resp.status_code == 200, f"update_order response: {resp.get_json()}"
        data = resp.get_json()
        assert data["message"]

    def test_record_qr_print_marks_order_and_counts_reprints(
        self,
        client,
        auth_headers,
        test_order_id,
    ):
        first_response = client.post(
            f"/api/orders/{test_order_id}/qr-print",
            headers=auth_headers,
            json={"mode": "order", "copies": 1, "label_count": 1},
        )

        assert first_response.status_code == 200, first_response.get_json()
        first_status = first_response.get_json()["print_status"]
        assert first_status["qr_print_count"] == 1
        assert first_status["qr_printed_at"]
        assert first_status["qr_printed_by"]
        assert first_status["qr_printed_by_name"]

        second_response = client.post(
            f"/api/orders/{test_order_id}/qr-print",
            headers=auth_headers,
            json={"mode": "order", "copies": 2, "label_count": 2},
        )

        assert second_response.status_code == 200, second_response.get_json()
        second_status = second_response.get_json()["print_status"]
        assert second_status["qr_print_count"] == 2
        assert second_status["copies"] == 2
        assert second_status["label_count"] == 2

        list_response = client.get(
            f"/api/orders?archive=all&keyword={_order_no(client, test_order_id)}",
            headers=auth_headers,
        )
        listed_order = next(
            order for order in list_response.get_json()["orders"]
            if order["id"] == test_order_id
        )
        assert listed_order["qr_print_count"] == 2
        assert listed_order["qr_printed_at"]
        assert "print_count=2" in _audit_detail(
            client,
            "print_order_qr",
            test_order_id,
        )

    def test_order_lifecycle_audits_use_actual_order_number(self, client, auth_headers):
        create_response = client.post(
            "/api/orders",
            headers=auth_headers,
            json={"product_name": "Audit Product", "quantity": 1},
        )
        assert create_response.status_code == 200, create_response.get_json()
        order_id = create_response.get_json()["id"]
        order_no = _order_no(client, order_id)
        assert _audit_detail(client, "create_order", order_id) == f"order_no={order_no}"

        update_response = client.put(
            f"/api/orders/{order_id}",
            headers=auth_headers,
            json={"remark": "audit update"},
        )
        assert update_response.status_code == 200, update_response.get_json()
        update_detail = _audit_detail(client, "update_order", order_id)
        assert f"order_no={order_no}" in update_detail
        assert "fields=remark" in update_detail

        _set_order_status(client, order_id, "completed")
        reopen_response = client.post(
            f"/api/orders/{order_id}/reopen",
            headers=auth_headers,
            json={"reason": "audit reopen", "status": "producing"},
        )
        assert reopen_response.status_code == 200, reopen_response.get_json()
        reopen_detail = _audit_detail(client, "reopen_order", order_id)
        assert f"order_no={order_no}" in reopen_detail
        assert "reason=audit reopen" in reopen_detail

        delete_response = client.delete(f"/api/orders/{order_id}", headers=auth_headers)
        assert delete_response.status_code == 200, delete_response.get_json()
        assert _audit_detail(client, "delete_order", order_id) == f"order_no={order_no}"

        restore_response = client.post(
            f"/api/orders/{order_id}/restore",
            headers=auth_headers,
        )
        assert restore_response.status_code == 200, restore_response.get_json()
        assert _audit_detail(client, "restore_order", order_id) == f"order_no={order_no}"

        delete_response = client.delete(f"/api/orders/{order_id}", headers=auth_headers)
        assert delete_response.status_code == 200, delete_response.get_json()
        purge_response = client.delete(
            f"/api/orders/{order_id}/purge",
            headers=auth_headers,
        )
        assert purge_response.status_code == 200, purge_response.get_json()
        assert _audit_detail(client, "purge_order", order_id) == f"order_no={order_no}"

    def test_update_order_cannot_manually_complete(self, client, auth_headers, test_order_id):
        _set_order_status(client, test_order_id, "producing")

        response = client.put(
            f"/api/orders/{test_order_id}",
            headers=auth_headers,
            json={"status": "completed"},
        )

        assert response.status_code == 400
        assert "参数校验失败" in response.get_json()["error"]
        assert _order_status(client, test_order_id) == "producing"

    def test_completed_orders_are_archived_by_default(self, client, auth_headers, test_order_id):
        _set_order_status(client, test_order_id, "completed")
        order_no = _order_no(client, test_order_id)

        active_resp = client.get(f"/api/orders?keyword={order_no}&limit=200", headers=auth_headers)
        assert active_resp.status_code == 200
        assert test_order_id not in _listed_order_ids(active_resp)

        completed_resp = client.get(
            f"/api/orders?archive=completed&keyword={order_no}&limit=200",
            headers=auth_headers,
        )
        assert completed_resp.status_code == 200
        assert test_order_id in _listed_order_ids(completed_resp)

        all_resp = client.get(
            f"/api/orders?archive=all&keyword={order_no}&limit=200",
            headers=auth_headers,
        )
        assert all_resp.status_code == 200
        assert test_order_id in _listed_order_ids(all_resp)

        status_resp = client.get(
            f"/api/orders?status=completed&keyword={order_no}&limit=200",
            headers=auth_headers,
        )
        assert status_resp.status_code == 200
        assert test_order_id in _listed_order_ids(status_resp)


    def test_completed_order_is_readonly_until_reopened(self, client, auth_headers, test_order_id):
        _set_order_status(client, test_order_id, "completed")

        update_resp = client.put(
            f"/api/orders/{test_order_id}",
            headers=auth_headers,
            json={"remark": "should be blocked"},
        )
        assert update_resp.status_code == 400
        assert "已完成订单已归档" in update_resp.get_json()["error"]

        delete_resp = client.delete(f"/api/orders/{test_order_id}", headers=auth_headers)
        assert delete_resp.status_code == 400
        assert "已完成订单已归档" in delete_resp.get_json()["error"]

        reopen_resp = client.post(
            f"/api/orders/{test_order_id}/reopen",
            headers=auth_headers,
            json={"reason": "fixture reopen"},
        )
        assert reopen_resp.status_code == 200, reopen_resp.get_json()
        assert reopen_resp.get_json()["status"] == "producing"

        order_no = _order_no(client, test_order_id)
        active_resp = client.get(f"/api/orders?keyword={order_no}", headers=auth_headers)
        assert test_order_id in _listed_order_ids(active_resp)

    def test_completed_order_blocks_mobile_scan_and_report(self, client, auth_headers, worker_auth_headers, test_order_id):
        _set_order_status(client, test_order_id, "completed")
        order_no = _order_no(client, test_order_id)
        process_id = _first_process_id(client, test_order_id)

        scan_resp = client.post(
            "/api/mobile/scan",
            headers=auth_headers,
            json={"code": order_no},
        )
        assert scan_resp.status_code == 400
        assert "已完成并归档" in scan_resp.get_json()["error"]

        report_resp = client.post(
            "/api/mobile/report",
            headers=worker_auth_headers,
            json={
                "order_id": test_order_id,
                "process_id": process_id,
                "quantity": 1,
                "report_type": "normal",
            },
        )
        assert report_resp.status_code == 409
        assert "已完成并归档" in report_resp.get_json()["error"]


class TestOrderDataScope:
    def test_order_subresources_enforce_process_scope(self, client):
        username, order_ids, _ = _seed_scoped_order_pair(client)
        headers = _login_headers(client, username, TEST_PASS)
        allowed_order_id, forbidden_order_id = order_ids

        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            forbidden_attachment_id = db.execute(
                "INSERT INTO order_attachments "
                "(order_id, file_name, file_type, file_size, file_path, uploaded_by) "
                "VALUES (?, 'forbidden.txt', 'text/plain', 0, '', 'scope fixture')",
                (forbidden_order_id,),
            ).lastrowid
            db.commit()

        allowed = client.get(
            f"/api/orders/{allowed_order_id}/materials",
            headers=headers,
        )
        assert allowed.status_code == 200, allowed.get_json()

        for endpoint in (
            f"/api/orders/{forbidden_order_id}/materials",
            f"/api/orders/{forbidden_order_id}/attachments",
            f"/api/orders/{forbidden_order_id}/remarks",
            f"/api/order-attachments/{forbidden_attachment_id}/download",
        ):
            response = client.get(endpoint, headers=headers)
            assert response.status_code == 403, (endpoint, response.get_json())

        delete_response = client.delete(
            f"/api/order-attachments/{forbidden_attachment_id}",
            headers=headers,
        )
        assert delete_response.status_code == 403, delete_response.get_json()

        with client.application.app_context():
            from modules.db import get_db

            row = get_db().execute(
                "SELECT id FROM order_attachments WHERE id = ?",
                (forbidden_attachment_id,),
            ).fetchone()
            assert row is not None

    def test_trash_and_focus_queries_filter_process_scope(self, client):
        username, order_ids, process_ids = _seed_scoped_order_pair(client)
        headers = _login_headers(client, username, TEST_PASS)

        with client.application.app_context():
            from modules.db import get_db
            from modules.repositories.completion_focus_repository import CompletionFocusRepository

            scoped_rows = CompletionFocusRepository.list_orders(
                limit=200,
                data_scope_pids=[process_ids[0]],
            )
            scoped_ids = {row["id"] for row in scoped_rows}
            assert order_ids[0] in scoped_ids
            assert order_ids[1] not in scoped_ids

            forbidden_exception_id = CompletionFocusRepository.insert_exception(
                order_ids[1],
                "scope fixture",
                "must remain inaccessible",
                "2099-01-01 00:00:00",
                None,
                "scope fixture",
            )
            db = get_db()
            db.commit()

        board_response = client.get(
            "/api/orders/completion-focus?limit=200",
            headers=headers,
        )
        assert board_response.status_code == 200, board_response.get_json()
        board_ids = {item["order_id"] for item in board_response.get_json()["items"]}
        assert order_ids[0] in board_ids
        assert order_ids[1] not in board_ids

        cancel_response = client.delete(
            f"/api/orders/completion-focus-exceptions/{forbidden_exception_id}",
            headers=headers,
        )
        assert cancel_response.status_code == 403, cancel_response.get_json()

        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            exception = db.execute(
                "SELECT status FROM order_completion_focus_exceptions WHERE id = ?",
                (forbidden_exception_id,),
            ).fetchone()
            assert exception["status"] == "active"
            db = get_db()
            db.execute(
                "UPDATE orders SET deleted_at = datetime('now','localtime'), "
                "pre_delete_status = status, status = 'cancelled' WHERE id IN (?, ?)",
                order_ids,
            )
            db.commit()

        response = client.get("/api/orders/trash?limit=200", headers=headers)
        assert response.status_code == 200, response.get_json()
        trash_ids = {order["id"] for order in response.get_json()["orders"]}
        assert order_ids[0] in trash_ids
        assert order_ids[1] not in trash_ids


class TestOrderDeleteFlow:
    def test_soft_delete_and_restore(self, client, auth_headers, test_order_id):
        # Soft delete
        del_resp = client.delete(f"/api/orders/{test_order_id}", headers=auth_headers)
        assert del_resp.status_code == 200
        # Restore
        restore_resp = client.post(f"/api/orders/{test_order_id}/restore", headers=auth_headers)
        assert restore_resp.status_code == 200

    def test_purge_preserves_inventory_and_shipment_history(self, client, auth_headers):
        suffix = uuid.uuid4().hex[:8].upper()
        order_no = f"TEST-PURGE-{suffix}"
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            order_id = db.execute(
                "INSERT INTO orders "
                "(order_no, customer, product_name, product_code, quantity, status, deleted_at) "
                "VALUES (?, 'Purge Customer', 'Purge Product', ?, 7, 'cancelled', "
                "datetime('now','localtime'))",
                (order_no, f"PURGE-{suffix}"),
            ).lastrowid
            inventory_id = db.execute(
                "INSERT INTO inventory "
                "(product_model, product_name, quantity, unit, order_id, remark) "
                "VALUES (?, 'Purge Product', 7, '件', ?, '保留原备注')",
                (f"PURGE-INV-{suffix}", order_id),
            ).lastrowid
            shipment_id = db.execute(
                "INSERT INTO shipments "
                "(shipment_no, customer, status, total_quantity, created_by) "
                "VALUES (?, 'Purge Customer', 'completed', 2, 'pytest')",
                (f"PURGE-SHIP-{suffix}",),
            ).lastrowid
            shipment_item_id = db.execute(
                "INSERT INTO shipment_items "
                "(shipment_id, inventory_id, product_model, product_name, quantity, unit, "
                "order_id, product_code, order_no) VALUES (?, ?, ?, 'Purge Product', 2, "
                "'件', ?, ?, '')",
                (shipment_id, inventory_id, f"PURGE-INV-{suffix}", order_id,
                 f"PURGE-{suffix}"),
            ).lastrowid
            db.commit()

        response = client.delete(f"/api/orders/{order_id}/purge", headers=auth_headers)
        assert response.status_code == 200, response.get_json()

        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            assert db.execute(
                "SELECT id FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone() is None
            inventory = db.execute(
                "SELECT order_id, quantity, remark FROM inventory WHERE id = ?",
                (inventory_id,),
            ).fetchone()
            assert inventory["order_id"] is None
            assert inventory["quantity"] == 7
            assert "保留原备注" in inventory["remark"]
            assert order_no in inventory["remark"]
            shipment_item = db.execute(
                "SELECT order_id, order_no, quantity FROM shipment_items WHERE id = ?",
                (shipment_item_id,),
            ).fetchone()
            assert shipment_item["order_id"] is None
            assert shipment_item["order_no"] == order_no
            assert shipment_item["quantity"] == 2
            assert db.execute(
                "SELECT id FROM shipments WHERE id = ?",
                (shipment_id,),
            ).fetchone() is not None

    def test_purge_removes_runtime_exception_but_keeps_event_history(
        self, client, auth_headers, test_order_id
    ):
        exception_response = client.post(
            f"/api/orders/{test_order_id}/completion-focus-exception",
            headers=auth_headers,
            json={"reason": "缺料", "detail": "purge fixture", "expires_at": "2099-01-01 00:00"},
        )
        assert exception_response.status_code == 200, exception_response.get_json()
        exception_id = exception_response.get_json()["exception"]["id"]
        before_events = _focus_event_count(client, "exception_created", test_order_id)

        assert client.delete(f"/api/orders/{test_order_id}", headers=auth_headers).status_code == 200
        purge_response = client.delete(
            f"/api/orders/{test_order_id}/purge",
            headers=auth_headers,
        )
        assert purge_response.status_code == 200, purge_response.get_json()
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            assert db.execute(
                "SELECT id FROM order_completion_focus_exceptions WHERE id = ?",
                (exception_id,),
            ).fetchone() is None
            assert db.execute(
                "SELECT COUNT(*) FROM order_completion_focus_events "
                "WHERE order_id = ? AND event_type = 'exception_created'",
                (test_order_id,),
            ).fetchone()[0] == before_events

    def test_purge_rejects_orders_with_protected_production_facts(
        self, client, auth_headers, test_order_id
    ):
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            process_id = db.execute(
                "SELECT process_id FROM order_processes WHERE order_id = ? LIMIT 1",
                (test_order_id,),
            ).fetchone()["process_id"]
            user_id = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()["id"]
            db.execute(
                "INSERT INTO work_records "
                "(order_id, process_id, user_id, type, quantity, status, serial_no) "
                "VALUES (?, ?, ?, 'normal', 1, 'approved', ?)",
                (test_order_id, process_id, user_id, f"PURGE-PROTECTED-{uuid.uuid4().hex}"),
            )
            db.commit()

        assert client.delete(f"/api/orders/{test_order_id}", headers=auth_headers).status_code == 200
        purge_response = client.delete(
            f"/api/orders/{test_order_id}/purge",
            headers=auth_headers,
        )
        assert purge_response.status_code == 409, purge_response.get_json()
        assert "只能保留软删除状态" in purge_response.get_json()["error"]
        with client.application.app_context():
            from modules.db import get_db

            assert get_db().execute(
                "SELECT id FROM orders WHERE id = ?", (test_order_id,)
            ).fetchone() is not None

    def test_trash_list(self, client, auth_headers):
        resp = client.get("/api/orders/trash", headers=auth_headers)
        assert resp.status_code == 200

    def test_work_records(self, client, auth_headers, test_order_id):
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            process = db.execute(
                "SELECT process_id FROM order_processes WHERE order_id = ? ORDER BY seq_order LIMIT 1",
                (test_order_id,),
            ).fetchone()
            user = db.execute(
                "SELECT id FROM users ORDER BY id LIMIT 1",
            ).fetchone()
            record_id = db.execute(
                "INSERT INTO work_records "
                "(order_id, process_id, user_id, type, quantity, status, serial_no) "
                "VALUES (?, ?, ?, 'normal', 3, 'approved', ?)",
                (test_order_id, process["process_id"], user["id"], f"ORDER-API-{uuid.uuid4().hex}"),
            ).lastrowid
            db.commit()

        resp = client.get(f"/api/orders/{test_order_id}/work-records", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert any(record["id"] == record_id for record in data["work_records"])
        assert any(record["id"] == record_id for record in data["records"])
        assert data["summary"]["normal_count"] >= 1

    def test_shipments(self, client, auth_headers, test_order_id):
        suffix = uuid.uuid4().hex[:8].upper()
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            order = db.execute(
                "SELECT order_no, product_code FROM orders WHERE id = ?",
                (test_order_id,),
            ).fetchone()
            other_order_id = db.execute(
                "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status) "
                "VALUES (?, 'Other Customer', 'Same Code Product', ?, 1, 'producing')",
                (f"TEST-OTHER-SHIP-{suffix}", order["product_code"]),
            ).lastrowid
            inventory_id = db.execute(
                "INSERT INTO inventory (product_model, product_name, quantity, unit, order_id) "
                "VALUES (?, 'Order Shipment Product', 10, '件', ?)",
                (f"ORDER-SHIP-{suffix}", test_order_id),
            ).lastrowid
            other_inventory_id = db.execute(
                "INSERT INTO inventory (product_model, product_name, quantity, unit, order_id) "
                "VALUES (?, 'Other Shipment Product', 10, '件', ?)",
                (f"OTHER-SHIP-{suffix}", other_order_id),
            ).lastrowid
            shipment_id = db.execute(
                "INSERT INTO shipments (shipment_no, customer, status, total_quantity, created_by) "
                "VALUES (?, 'Order Customer', 'completed', 2, 'pytest')",
                (f"TEST-ORDER-SHIP-{suffix}",),
            ).lastrowid
            other_shipment_id = db.execute(
                "INSERT INTO shipments (shipment_no, customer, status, total_quantity, created_by) "
                "VALUES (?, 'Other Customer', 'completed', 1, 'pytest')",
                (f"TEST-OTHER-SHIP-{suffix}",),
            ).lastrowid
            db.execute(
                "INSERT INTO shipment_items "
                "(shipment_id, inventory_id, product_model, product_name, quantity, unit, "
                "order_id, product_code, order_no) VALUES (?, ?, ?, 'Order Shipment Product', "
                "2, '件', ?, ?, ?)",
                (shipment_id, inventory_id, f"ORDER-SHIP-{suffix}", test_order_id,
                 order["product_code"], order["order_no"]),
            )
            db.execute(
                "INSERT INTO shipment_items "
                "(shipment_id, inventory_id, product_model, product_name, quantity, unit, "
                "order_id, product_code, order_no) VALUES (?, ?, ?, 'Other Shipment Product', "
                "1, '件', ?, ?, ?)",
                (other_shipment_id, other_inventory_id, f"OTHER-SHIP-{suffix}", other_order_id,
                 order["product_code"], f"TEST-OTHER-SHIP-{suffix}"),
            )
            db.commit()

        resp = client.get(f"/api/orders/{test_order_id}/shipments", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        shipment_ids = {shipment["id"] for shipment in data["shipments"]}
        assert shipment_id in shipment_ids
        assert other_shipment_id not in shipment_ids
        shipment = next(item for item in data["shipments"] if item["id"] == shipment_id)
        assert shipment["order_quantity"] == 2


class TestOrderEdgeCases:
    def test_delete_nonexistent(self, client, auth_headers):
        resp = client.delete("/api/orders/99999", headers=auth_headers)
        assert resp.status_code in (400, 404)  # nonexistent

    def test_restore_nonexistent(self, client, auth_headers):
        resp = client.post("/api/orders/99999/restore", headers=auth_headers)
        assert resp.status_code in (200, 400)  # restore nonexistent

    def test_purge_nonexistent(self, client, auth_headers):
        resp = client.delete("/api/orders/99999/purge", headers=auth_headers)
        assert resp.status_code in (400, 404)  # nonexistent

    def test_workpiece_progress(self, client, auth_headers, test_order_id):
        resp = client.get(f"/api/orders/{test_order_id}/workpiece-progress", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "summary" in data
        assert "analysis" in data
        assert "deadline_risk" in data["analysis"]
        assert "recommendations" in data["analysis"]
        assert "process_stats" in data["summary"]

    def test_completion_focus_board_contract(self, client, auth_headers, test_order_id):
        resp = client.get("/api/orders/completion-focus", headers=auth_headers)
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()
        assert data["enabled"] is True
        assert "summary" in data
        assert "items" in data
        if data["items"]:
            item = data["items"][0]
            assert "order_no" in item
            assert "focus_label" in item
            assert "priority_process_name" in item

    def test_completion_focus_hard_blocks_worker_mobile_report(self, client, auth_headers, worker_auth_headers):
        order_id, process_id = _seed_completion_focus_pair(client)
        save_resp = client.post(
            "/api/orders/completion-focus/config",
            headers=auth_headers,
            json={"mode": "hard", "tail_percent": 70},
        )
        assert save_resp.status_code == 200, save_resp.get_json()

        report_resp = client.post(
            "/api/mobile/report",
            headers=worker_auth_headers,
            json={
                "order_id": order_id,
                "process_id": process_id,
                "quantity": 1,
                "report_type": "normal",
            },
        )
        assert report_resp.status_code == 409, report_resp.get_json()
        data = report_resp.get_json()
        warning = data["completion_focus_warning"]
        assert warning["blocking"] is True
        assert warning["recommended_order_no"].startswith("TEST-FOCUS-EARLY-")
        assert _focus_event_count(client, "scan_blocked", order_id) == 1

    def test_completion_focus_hard_allows_bypass_user_mobile_report(self, client, auth_headers, worker_auth_headers):
        lead_username = f"focuslead_{uuid.uuid4().hex[:6]}"
        order_id, process_id = _seed_completion_focus_pair(client, lead_username=lead_username)
        lead_headers = _login_headers(client, lead_username, TEST_PASS)
        save_resp = client.post(
            "/api/orders/completion-focus/config",
            headers=auth_headers,
            json={"mode": "hard", "tail_percent": 70},
        )
        assert save_resp.status_code == 200, save_resp.get_json()

        report_resp = client.post(
            "/api/mobile/report",
            headers=lead_headers,
            json={
                "order_id": order_id,
                "process_id": process_id,
                "quantity": 1,
                "report_type": "normal",
            },
        )
        assert report_resp.status_code == 200, report_resp.get_json()
        assert _focus_event_count(client, "scan_bypassed", order_id) == 1

    def test_completion_focus_config_and_exception(self, client, auth_headers, test_order_id):
        cfg_resp = client.get("/api/orders/completion-focus/config", headers=auth_headers)
        assert cfg_resp.status_code == 200, cfg_resp.get_json()
        cfg = cfg_resp.get_json()
        assert cfg["mode"] in ("off", "soft", "hard")
        assert {item["value"] for item in cfg["mode_options"]} == {"off", "soft", "hard"}

        save_resp = client.post(
            "/api/orders/completion-focus/config",
            headers=auth_headers,
            json={"mode": "hard", "tail_percent": 75},
        )
        assert save_resp.status_code == 200, save_resp.get_json()
        assert save_resp.get_json()["config"]["mode"] == "hard"

        ex_resp = client.post(
            f"/api/orders/{test_order_id}/completion-focus-exception",
            headers=auth_headers,
            json={"reason": "缺料", "detail": "fixture", "expires_at": "2099-01-01 00:00"},
        )
        assert ex_resp.status_code == 200, ex_resp.get_json()
        exception_id = ex_resp.get_json()["exception"]["id"]
        assert _focus_event_count(client, "exception_created", test_order_id) == 1

        board_resp = client.get("/api/orders/completion-focus", headers=auth_headers)
        assert board_resp.status_code == 200, board_resp.get_json()
        board = board_resp.get_json()
        assert board["summary"]["exception"] >= 1
        assert any(item["order_id"] == test_order_id and item["is_exception"] for item in board["items"])

        cancel_resp = client.delete(
            f"/api/orders/completion-focus-exceptions/{exception_id}",
            headers=auth_headers,
            json={"reason": "fixture cancel"},
        )
        assert cancel_resp.status_code == 200, cancel_resp.get_json()
        assert _focus_event_count(client, "exception_cancelled", test_order_id) == 1

    def test_duplicate_completion_focus_cancel_is_idempotent(self, client, auth_headers, test_order_id):
        create_resp = client.post(
            f"/api/orders/{test_order_id}/completion-focus-exception",
            headers=auth_headers,
            json={"reason": "缺料", "detail": "first detail", "expires_at": "2099-01-01 00:00"},
        )
        assert create_resp.status_code == 200, create_resp.get_json()
        exception_id = create_resp.get_json()["exception"]["id"]

        first = client.delete(
            f"/api/orders/completion-focus-exceptions/{exception_id}",
            headers=auth_headers,
            json={"reason": "first cancel"},
        )
        assert first.status_code == 200, first.get_json()
        with client.application.app_context():
            from modules.db import get_db

            first_cancellation = tuple(get_db().execute(
                "SELECT cancel_reason, cancelled_by, cancelled_at "
                "FROM order_completion_focus_exceptions WHERE id = ?",
                (exception_id,),
            ).fetchone())
        second = client.delete(
            f"/api/orders/completion-focus-exceptions/{exception_id}",
            headers=auth_headers,
            json={"reason": "replayed cancel"},
        )
        assert second.status_code == 200, second.get_json()
        assert _focus_event_count(client, "exception_cancelled", test_order_id) == 1
        with client.application.app_context():
            from modules.db import get_db

            row = get_db().execute(
                "SELECT cancel_reason, cancelled_by, cancelled_at "
                "FROM order_completion_focus_exceptions WHERE id = ?",
                (exception_id,),
            ).fetchone()
            audit_count = get_db().execute(
                "SELECT COUNT(*) FROM audit_logs "
                "WHERE action = 'completion_focus_exception_cancel' "
                "AND target_id = ?",
                (exception_id,),
            ).fetchone()[0]
        assert row["cancel_reason"] == "first cancel"
        assert row["cancelled_by"] is not None
        assert tuple(row) == first_cancellation
        assert audit_count == 1

    def test_completion_focus_cancel_event_failure_rolls_back(
        self, client, auth_headers, test_order_id, monkeypatch
    ):
        create_resp = client.post(
            f"/api/orders/{test_order_id}/completion-focus-exception",
            headers=auth_headers,
            json={"reason": "缺料", "detail": "rollback fixture", "expires_at": "2099-01-01 00:00"},
        )
        assert create_resp.status_code == 200, create_resp.get_json()
        exception_id = create_resp.get_json()["exception"]["id"]

        from modules.repositories.completion_focus_repository import CompletionFocusRepository
        from modules.services.order_focus_service import OrderFocusService

        def fail_event(*_args, **_kwargs):
            raise RuntimeError("event sink unavailable")

        monkeypatch.setattr(CompletionFocusRepository, "insert_event", staticmethod(fail_event))
        with client.application.app_context():
            with pytest.raises(RuntimeError, match="event sink unavailable"):
                OrderFocusService.cancel_exception(
                    exception_id,
                    {"id": 1, "name": "Test Runner"},
                    "rollback cancel",
                )
            from modules.db import get_db

            row = get_db().execute(
                "SELECT status, cancel_reason FROM order_completion_focus_exceptions WHERE id = ?",
                (exception_id,),
            ).fetchone()
        assert row["status"] == "active"
        assert row["cancel_reason"] in (None, "")

    def test_batch_create_reports_row_context_and_actor(self, client, auth_headers):
        order_no = f"BATCH-VALID-{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/orders/batch",
            headers=auth_headers,
            json={
                "orders": [
                    {
                        "order_no": order_no,
                        "product_name": "Batch Product",
                        "quantity": 2,
                    },
                    {
                        "order_no": f"BATCH-INVALID-{uuid.uuid4().hex[:8]}",
                        "product_name": "",
                        "quantity": 0,
                    },
                ]
            },
        )
        assert response.status_code == 200, response.get_json()
        payload = response.get_json()
        assert payload["created"] == 1
        assert payload["partial_success"] is True
        assert payload["error_rows"][0]["row"] == 2
        assert payload["error_rows"][0]["order_no"].startswith("BATCH-INVALID-")
        assert payload["detail"] == payload["errors"][:20]
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            actor = db.execute(
                "SELECT id, name FROM users WHERE username = 'testrunner'"
            ).fetchone()
            order = db.execute(
                "SELECT id, priority_changed_by, priority_changed_by_name "
                "FROM orders WHERE order_no = ?", (order_no,)
            ).fetchone()
            history = db.execute(
                "SELECT changed_by, changed_by_name FROM order_priority_history "
                "WHERE order_id = ? AND event_type = 'created'", (order['id'],)
            ).fetchone()
            row_audit = db.execute(
                "SELECT user_id, detail FROM audit_logs "
                "WHERE action = 'batch_create_order_row' AND target_id = ?",
                (order['id'],),
            ).fetchone()
            failure_audit = db.execute(
                "SELECT user_id, detail FROM audit_logs "
                "WHERE action = 'batch_create_order_row_error' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            batch_audit = db.execute(
                "SELECT user_id, detail FROM audit_logs "
                "WHERE action = 'batch_create_orders' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert tuple(order)[1:] == (actor['id'], actor['name'])
        assert tuple(history) == (actor['id'], actor['name'])
        assert row_audit['user_id'] == actor['id']
        assert f"batch_created_by={actor['id']}" in row_audit['detail']
        assert failure_audit['user_id'] == actor['id']
        assert 'row=2' in failure_audit['detail']
        assert payload['error_rows'][0]['order_no'] in failure_audit['detail']
        assert batch_audit['user_id'] == actor['id']
        assert 'created=1; errors=1; partial_success=True' in batch_audit['detail']

    def test_create_order_rejects_non_production_defaults(self, client, auth_headers):
        missing_name = client.post(
            "/api/orders",
            headers=auth_headers,
            json={"order_no": f"NO-NAME-{uuid.uuid4().hex[:8]}", "quantity": 1},
        )
        assert missing_name.status_code == 400, missing_name.get_json()

        zero_quantity = client.post(
            "/api/orders",
            headers=auth_headers,
            json={
                "order_no": f"ZERO-QTY-{uuid.uuid4().hex[:8]}",
                "product_name": "Invalid Quantity",
                "quantity": 0,
            },
        )
        assert zero_quantity.status_code == 400, zero_quantity.get_json()


class TestOrderAuditRegression:
    @pytest.mark.parametrize('invalid_assignment', [
        {'process_ids': [999999]},
        {'route_id': 999999},
    ])
    def test_batch_assignment_validation_keeps_later_valid_row(
        self, client, auth_headers, invalid_assignment
    ):
        prefix = f"BATCH-ASSIGN-{uuid.uuid4().hex[:8]}"
        response = client.post(
            '/api/orders/batch', headers=auth_headers,
            json={'orders': [
                {'order_no': f'{prefix}-BAD', 'product_name': 'Invalid assignment',
                 'quantity': 1, **invalid_assignment},
                {'order_no': f'{prefix}-GOOD', 'product_name': 'Valid later row',
                 'quantity': 1},
            ]},
        )
        assert response.status_code == 200, response.get_json()
        payload = response.get_json()
        assert payload['created'] == 1
        assert len(payload['errors']) == 1
        assert payload['detail'] == payload['errors']
        assert payload['error_rows'][0]['row'] == 1
        assert payload['error_rows'][0]['index'] == 0
        assert payload['error_rows'][0]['order_no'] == f'{prefix}-BAD'
        with client.application.app_context():
            from modules.db import get_db

            rows = get_db().execute(
                'SELECT order_no FROM orders WHERE order_no LIKE ?', (prefix + '%',)
            ).fetchall()
        assert [row['order_no'] for row in rows] == [f'{prefix}-GOOD']

    @pytest.mark.parametrize('adapter', ['http', 'legacy_service'])
    def test_batch_infrastructure_failure_stops_and_rolls_back_only_failed_row(
        self, client, auth_headers, monkeypatch, adapter
    ):
        from modules.services.order_service import BatchOrderImportError, OrderService

        prefix = f'BATCH-STOP-{uuid.uuid4().hex[:8]}'
        orders = [
            {'order_no': f'{prefix}-{index}', 'product_name': 'Interrupted import',
             'quantity': 1}
            for index in range(1, 4)
        ]
        original_assignment = OrderService._assign_processes
        attempted = []

        def assignment_with_failure(db, order_id, *args, **kwargs):
            order_no = db.execute(
                'SELECT order_no FROM orders WHERE id = ?', (order_id,)
            ).fetchone()['order_no']
            attempted.append(order_no)
            original_assignment(db, order_id, *args, **kwargs)
            if order_no == orders[1]['order_no']:
                raise RuntimeError('sensitive-db-path-and-password-must-not-leak')

        monkeypatch.setattr(OrderService, '_assign_processes', staticmethod(assignment_with_failure))
        if adapter == 'http':
            response = client.post(
                '/api/orders/batch', headers=auth_headers, json={'orders': orders}
            )
            assert response.status_code == 500, response.get_json()
            payload = response.get_json()
            assert payload['error'] == '批量导入因内部错误中止'
            assert 'sensitive-db-path-and-password' not in response.get_data(as_text=True)
        else:
            with client.application.app_context():
                with pytest.raises(BatchOrderImportError, match='批量导入因内部错误中止') as raised:
                    OrderService.batch_create(orders)
            payload = raised.value.result
            assert 'sensitive-db-path-and-password' not in str(raised.value)
            assert payload['infrastructure_error'] is True
        assert payload['created'] == 1
        assert payload['partial_success'] is True
        assert payload['error_rows'] == [{
            'row': 2, 'index': 1, 'order_no': orders[1]['order_no'],
            'error': '内部错误，批量导入已中止',
        }]
        assert attempted == [orders[0]['order_no'], orders[1]['order_no']]
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            surviving_orders = db.execute(
                'SELECT id, order_no FROM orders WHERE order_no LIKE ?', (prefix + '%',)
            ).fetchall()
            assert [row['order_no'] for row in surviving_orders] == [orders[0]['order_no']]
            assert db.execute(
                'SELECT COUNT(*) FROM order_processes WHERE order_id = ?',
                (surviving_orders[0]['id'],),
            ).fetchone()[0] > 0
            assert db.execute(
                'SELECT COUNT(*) FROM order_priority_history WHERE order_no_snapshot LIKE ?',
                (prefix + '%',),
            ).fetchone()[0] == 1

    @pytest.mark.parametrize('selection', ['product_id', 'product_code'])
    def test_create_resolves_blank_name_from_selected_product(
        self, client, auth_headers, selection
    ):
        suffix = uuid.uuid4().hex[:8]
        product_code = f'NORMALIZE-{suffix}'
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            product_id = ensure_product(db, product_code, f'Canonical product {suffix}')
            db.commit()
        response = client.post(
            '/api/orders', headers=auth_headers,
            json={
                'order_no': f'NORMALIZE-ORDER-{suffix}', 'product_name': '',
                'quantity': 2, selection: product_id if selection == 'product_id' else product_code,
            },
        )
        assert response.status_code == 200, response.get_json()
        with client.application.app_context():
            from modules.db import get_db

            order = get_db().execute(
                'SELECT product_id, product_code, product_name, quantity FROM orders WHERE id = ?',
                (response.get_json()['id'],),
            ).fetchone()
        assert tuple(order) == (product_id, product_code, f'Canonical product {suffix}', 2)

    @pytest.mark.parametrize('invalid_fields', [
        {'quantity': 1},
        {'product_name': '   ', 'quantity': 1},
        {'product_name': 9, 'quantity': 1},
        {'product_name': 'Missing quantity'},
        {'product_name': 'Invalid quantity', 'quantity': True},
        {'product_name': 'Invalid quantity', 'quantity': False},
        {'product_name': 'Invalid quantity', 'quantity': 1.5},
        {'product_name': 'Invalid quantity', 'quantity': '2'},
        {'product_name': 'Invalid quantity', 'quantity': 0},
    ])
    def test_direct_create_rejects_invalid_required_values(self, client, invalid_fields):
        from modules.domain.errors import ValidationError
        from modules.services.order_service import OrderService

        order_no = f'INVALID-DIRECT-{uuid.uuid4().hex[:8]}'
        with client.application.app_context():
            with pytest.raises(ValidationError):
                OrderService.create_order({'order_no': order_no, **invalid_fields})
            from modules.db import get_db

            assert get_db().execute(
                'SELECT id FROM orders WHERE order_no = ?', (order_no,)
            ).fetchone() is None

    @pytest.mark.parametrize('missing_fields', [
        {'quantity': 1}, {'product_name': 'Missing quantity'},
    ])
    def test_batch_missing_required_values_are_row_errors(
        self, client, auth_headers, missing_fields
    ):
        suffix = uuid.uuid4().hex[:8]
        response = client.post(
            '/api/orders/batch', headers=auth_headers,
            json={'orders': [
                {'order_no': f'MISSING-{suffix}', **missing_fields},
                {'order_no': f'VALID-{suffix}', 'product_name': 'Valid after missing', 'quantity': 1},
            ]},
        )
        assert response.status_code == 200, response.get_json()
        payload = response.get_json()
        assert payload['created'] == 1
        assert payload['error_rows'][0]['row'] == 1
        assert len(payload['errors']) == 1

    def test_recycled_order_materials_reject_add_and_delete(
        self, client, auth_headers, test_order_id
    ):
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            material_id = create_material(db, name=f'Trash recipe {uuid.uuid4().hex[:8]}')
            db.commit()
        created = client.post(
            f'/api/orders/{test_order_id}/materials', headers=auth_headers,
            json={'material_id': material_id, 'quantity_per_unit': 1},
        )
        assert created.status_code == 201, created.get_json()
        item_id = created.get_json()['material']['id']
        assert client.delete(f'/api/orders/{test_order_id}', headers=auth_headers).status_code == 200
        added = client.post(
            f'/api/orders/{test_order_id}/materials', headers=auth_headers,
            json={'material_id': material_id, 'quantity_per_unit': 2},
        )
        removed = client.delete(
            f'/api/orders/{test_order_id}/materials/{item_id}', headers=auth_headers,
        )
        assert added.status_code == 404, added.get_json()
        assert removed.status_code == 404, removed.get_json()
        with client.application.app_context():
            from modules.db import get_db

            row = get_db().execute(
                'SELECT quantity_per_unit FROM order_materials WHERE id = ?', (item_id,)
            ).fetchone()
        assert row['quantity_per_unit'] == 1

    def test_manual_nonconformance_blocks_purge_without_other_facts(
        self, client, auth_headers, test_order_id
    ):
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            ncr_id = db.execute(
                'INSERT INTO quality_nonconformances '
                '(ncr_no, order_id, source_type, description) VALUES (?, ?, ?, ?)',
                (f'MANUAL-NCR-{uuid.uuid4().hex[:8]}', test_order_id, 'manual', 'Retain manual fact'),
            ).lastrowid
            db.commit()
        assert client.delete(f'/api/orders/{test_order_id}', headers=auth_headers).status_code == 200
        response = client.delete(f'/api/orders/{test_order_id}/purge', headers=auth_headers)
        assert response.status_code == 409, response.get_json()
        assert '只能保留软删除状态' in response.get_json()['error']
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            assert db.execute('SELECT id FROM orders WHERE id = ?', (test_order_id,)).fetchone()
            assert db.execute(
                'SELECT order_id FROM quality_nonconformances WHERE id = ?', (ncr_id,)
            ).fetchone()['order_id'] == test_order_id

    @pytest.mark.parametrize('adapter', ['http', 'legacy_service'])
    def test_real_sqlite_integrity_error_is_safe_import_interruption(
        self, client, auth_headers, monkeypatch, adapter
    ):
        from modules.services.order_service import BatchOrderImportError, OrderService

        prefix = f'BATCH-SQLITE-{uuid.uuid4().hex[:8]}'
        orders = [
            {'order_no': f'{prefix}-{index}', 'product_name': 'SQLite rollback product',
             'quantity': 1}
            for index in range(1, 4)
        ]
        attempts = []
        original_create = OrderService.create_order

        def trace_create(data, *args, **kwargs):
            attempts.append(data['order_no'])
            return original_create(data, *args, **kwargs)

        monkeypatch.setattr(OrderService, 'create_order', staticmethod(trace_create))
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            before_process_count = db.execute('SELECT COUNT(*) FROM order_processes').fetchone()[0]
            db.execute(
                "CREATE TRIGGER test_fail_second_import_history "
                "BEFORE INSERT ON order_priority_history "
                f"WHEN NEW.order_no_snapshot = '{orders[1]['order_no']}' "
                "BEGIN SELECT RAISE(ABORT, 'secret-internal-database-location'); END"
            )
            db.commit()

        if adapter == 'http':
            response = client.post(
                '/api/orders/batch', headers=auth_headers, json={'orders': orders}
            )
            assert response.status_code == 500, response.get_json()
            payload = response.get_json()
            assert payload['error'] == '批量导入因内部错误中止'
            assert 'secret-internal-database-location' not in response.get_data(as_text=True)
            assert '数据完整性约束违反' not in response.get_data(as_text=True)
        else:
            with client.application.app_context():
                with pytest.raises(BatchOrderImportError) as raised:
                    OrderService.batch_create(orders)
            payload = raised.value.result
            assert 'secret-internal-database-location' not in str(raised.value)
            assert payload['infrastructure_error'] is True

        assert attempts == [orders[0]['order_no'], orders[1]['order_no']]
        assert payload['created'] == 1
        assert payload['partial_success'] is True
        assert payload['error_rows'] == [{
            'row': 2, 'index': 1, 'order_no': orders[1]['order_no'],
            'error': '内部错误，批量导入已中止',
        }]
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            surviving = db.execute(
                'SELECT id, order_no FROM orders WHERE order_no LIKE ?', (prefix + '%',)
            ).fetchall()
            assert [row['order_no'] for row in surviving] == [orders[0]['order_no']]
            surviving_process_count = db.execute(
                'SELECT COUNT(*) FROM order_processes WHERE order_id = ?', (surviving[0]['id'],)
            ).fetchone()[0]
            assert surviving_process_count > 0
            assert db.execute('SELECT COUNT(*) FROM order_processes').fetchone()[0] == (
                before_process_count + surviving_process_count
            )
            assert db.execute(
                'SELECT COUNT(*) FROM order_priority_history WHERE order_no_snapshot LIKE ?',
                (prefix + '%',),
            ).fetchone()[0] == 1

    @pytest.mark.parametrize('fact_table', [
        'work_records', 'scrap_records', 'rework_records', 'quality_inspections',
        'process_quality_evaluations', 'quality_inspection_tasks',
    ])
    def test_each_independent_fact_prevents_purge(
        self, client, auth_headers, test_order_id, fact_table
    ):
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            process_id = db.execute(
                'SELECT process_id FROM order_processes WHERE order_id = ? LIMIT 1',
                (test_order_id,),
            ).fetchone()['process_id']
            actor_id = db.execute('SELECT id FROM users ORDER BY id LIMIT 1').fetchone()['id']
            if fact_table in ('work_records', 'scrap_records', 'rework_records'):
                fact_id = db.execute(
                    f'INSERT INTO {fact_table} (order_id, process_id, user_id, quantity) '
                    'VALUES (?, ?, ?, 1)', (test_order_id, process_id, actor_id),
                ).lastrowid
            elif fact_table == 'quality_inspections':
                fact_id = db.execute(
                    'INSERT INTO quality_inspections (order_id, process_id, inspector_id) '
                    'VALUES (?, ?, ?)', (test_order_id, process_id, actor_id),
                ).lastrowid
            elif fact_table == 'process_quality_evaluations':
                fact_id = db.execute(
                    'INSERT INTO process_quality_evaluations '
                    '(order_id,target_process_id,evaluator_process_id,evaluator_user_id,'
                    'processing_quality,dimensional_accuracy,appearance_quality,'
                    'process_continuity,cleanliness_protection,total_score,grade) '
                    'VALUES (?, ?, ?, ?, 5, 5, 5, 5, 5, 100, ?)',
                    (test_order_id, process_id, process_id, actor_id, 'A'),
                ).lastrowid
            else:
                suffix = uuid.uuid4().hex[:8]
                fact_id = db.execute(
                    'INSERT INTO quality_inspection_tasks '
                    '(task_no,trigger_key,order_id,inspection_type,trigger_type) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (f'MANUAL-TASK-{suffix}', f'manual-test-{suffix}',
                     test_order_id, 'process', 'manual'),
                ).lastrowid
            db.commit()
            before_fact = tuple(db.execute(
                f'SELECT * FROM {fact_table} WHERE id = ?', (fact_id,)
            ).fetchone())
        assert client.delete(f'/api/orders/{test_order_id}', headers=auth_headers).status_code == 200
        response = client.delete(f'/api/orders/{test_order_id}/purge', headers=auth_headers)
        assert response.status_code == 409, response.get_json()
        assert '只能保留软删除状态' in response.get_json()['error']
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            assert tuple(db.execute(
                f'SELECT * FROM {fact_table} WHERE id = ?', (fact_id,)
            ).fetchone()) == before_fact
            assert db.execute(
                'SELECT deleted_at FROM orders WHERE id = ?', (test_order_id,)
            ).fetchone()['deleted_at']

    @pytest.mark.parametrize('storage', ['blob', 'file'])
    def test_attachments_block_purge_and_preserve_bytes_and_metadata(
        self, client, auth_headers, test_order_id, tmp_path, storage
    ):
        payload = b'protected attachment\x00\xff\r\noriginal bytes'
        file_path = tmp_path / 'protected-attachment.bin'
        if storage == 'file':
            file_path.write_bytes(payload)
        with client.application.app_context():
            from modules.db import get_db

            db = get_db()
            attachment_id = db.execute(
                'INSERT INTO order_attachments '
                '(order_id,file_name,file_type,file_size,file_data,file_path,uploaded_by) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (test_order_id, file_path.name, 'application/octet-stream', len(payload),
                 payload if storage == 'blob' else None,
                 str(file_path) if storage == 'file' else '', 'evidence owner'),
            ).lastrowid
            db.commit()
            before_attachment = tuple(db.execute(
                'SELECT * FROM order_attachments WHERE id = ?', (attachment_id,)
            ).fetchone())
        assert client.delete(f'/api/orders/{test_order_id}', headers=auth_headers).status_code == 200
        response = client.delete(f'/api/orders/{test_order_id}/purge', headers=auth_headers)
        assert response.status_code == 409, response.get_json()
        with client.application.app_context():
            from modules.db import get_db

            row = get_db().execute(
                'SELECT * FROM order_attachments WHERE id = ?', (attachment_id,)
            ).fetchone()
        assert tuple(row) == before_attachment
        if storage == 'file':
            assert row['file_path'] == str(file_path)
            assert file_path.read_bytes() == payload
        else:
            assert row['file_data'] == payload

    def test_purge_rechecks_restored_order_inside_transaction(
        self, client, auth_headers, test_order_id, monkeypatch
    ):
        from contextlib import contextmanager
        from modules.db import get_db
        from modules.services import BaseService
        from modules.services.order_service import OrderService

        assert client.delete(f'/api/orders/{test_order_id}', headers=auth_headers).status_code == 200

        class RestoreBeforePurgeUnitOfWork:
            @staticmethod
            @contextmanager
            def transaction():
                db = get_db()
                db.execute(
                    "UPDATE orders SET deleted_at = NULL, status = 'pending' WHERE id = ?",
                    (test_order_id,),
                )
                db.commit()
                with BaseService.transaction() as txn:
                    yield txn

        monkeypatch.setattr(OrderService, 'unit_of_work', RestoreBeforePurgeUnitOfWork)
        with client.application.app_context():
            with pytest.raises(ValueError, match='只能彻底删除回收站中的订单'):
                OrderService.purge_order(test_order_id)
            order = get_db().execute(
                'SELECT id, deleted_at FROM orders WHERE id = ?', (test_order_id,)
            ).fetchone()
            assert order is not None
            assert order['deleted_at'] is None

    def test_purge_failure_rolls_back_runtime_exception_and_preserved_references(
        self, client, auth_headers, test_order_id, monkeypatch
    ):
        from modules.db import get_db
        from modules.repositories.order_repository import OrderRepository
        from modules.services.order_service import OrderService

        exception_response = client.post(
            f'/api/orders/{test_order_id}/completion-focus-exception',
            headers=auth_headers,
            json={'reason': '缺料', 'detail': 'rollback evidence'},
        )
        assert exception_response.status_code == 200, exception_response.get_json()
        exception_id = exception_response.get_json()['exception']['id']
        with client.application.app_context():
            db = get_db()
            inventory_id = db.execute(
                'INSERT INTO inventory (product_model,product_name,quantity,order_id,remark) '
                'VALUES (?, ?, 3, ?, ?)',
                (f'PURGE-ROLLBACK-{uuid.uuid4().hex[:8]}', 'Preserved stock', test_order_id, 'original remark'),
            ).lastrowid
            db.commit()
        assert client.delete(f'/api/orders/{test_order_id}', headers=auth_headers).status_code == 200
        original_purge = OrderRepository.purge_with_children

        def fail_after_delete(order_id, child_tables, db=None):
            original_purge(order_id, child_tables, db=db)
            raise RuntimeError('forced final purge failure')

        monkeypatch.setattr(OrderRepository, 'purge_with_children', staticmethod(fail_after_delete))
        with client.application.app_context():
            with pytest.raises(RuntimeError, match='forced final purge failure'):
                OrderService.purge_order(test_order_id)
            db = get_db()
            assert db.execute(
                'SELECT deleted_at FROM orders WHERE id = ?', (test_order_id,)
            ).fetchone()['deleted_at']
            assert db.execute(
                'SELECT status FROM order_completion_focus_exceptions WHERE id = ?', (exception_id,)
            ).fetchone()['status'] == 'active'
            assert tuple(db.execute(
                'SELECT order_id,quantity,remark FROM inventory WHERE id = ?', (inventory_id,)
            ).fetchone()) == (test_order_id, 3, 'original remark')
            assert db.execute(
                'SELECT COUNT(*) FROM order_processes WHERE order_id = ?', (test_order_id,)
            ).fetchone()[0] > 0
