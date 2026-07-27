"""Order management specific tests — covers all 12 endpoints"""
import json, time, pytest, uuid
from factories import TEST_HASH, TEST_PASS, ensure_user


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

    def test_update_order(self, client, auth_headers, test_order_id):
        resp = client.put(f"/api/orders/{test_order_id}", headers=auth_headers, json={
            "remark": "Updated by test"
        })
        assert resp.status_code == 200, f"update_order response: {resp.get_json()}"
        data = resp.get_json()
        assert data["message"]

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
