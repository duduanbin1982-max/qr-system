from io import BytesIO
import uuid

import openpyxl

from modules.app import app
from modules.db import get_db
from modules.services.access_policy_service import get_user_process_ids
from factories import ensure_user, WORKER_HASH


def _create_product(client, auth_headers, product_name=None):
    product_name = product_name or f"Restore Product {uuid.uuid4().hex[:8]}"
    response = client.post(
        "/api/products",
        headers=auth_headers,
        json={"product_name": product_name},
    )
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    return data["id"]


class TestOrderAttachmentContracts:
    def test_attachment_download_and_delete_contracts(self, client, auth_headers, test_order_id):
        upload_response = client.post(
            f"/api/orders/{test_order_id}/attachments",
            headers=auth_headers,
            data={"file": (BytesIO(b"attachment-contract"), "contract.txt")},
            content_type="multipart/form-data",
        )
        assert upload_response.status_code == 200, upload_response.get_json()
        attachment_id = upload_response.get_json()["id"]

        download_response = client.get(
            f"/api/order-attachments/{attachment_id}/download",
            headers=auth_headers,
        )
        assert download_response.status_code == 200
        assert download_response.data == b"attachment-contract"

        legacy_download_response = client.get(
            f"/api/attachments/{attachment_id}/download",
            headers=auth_headers,
        )
        assert legacy_download_response.status_code == 200
        assert legacy_download_response.data == b"attachment-contract"

        legacy_delete_response = client.delete(
            f"/api/attachments/{attachment_id}",
            headers=auth_headers,
        )
        assert legacy_delete_response.status_code == 200, legacy_delete_response.get_json()

        missing_response = client.get(
            f"/api/order-attachments/{attachment_id}/download",
            headers=auth_headers,
        )
        assert missing_response.status_code == 404


class TestProductRestoreContracts:
    def test_restore_product_accepts_put(self, client, auth_headers):
        product_id = _create_product(client, auth_headers, f"Put Restore {uuid.uuid4().hex[:8]}")

        delete_response = client.delete(f"/api/products/{product_id}", headers=auth_headers)
        assert delete_response.status_code == 200, delete_response.get_json()

        restore_response = client.put(f"/api/products/{product_id}/restore", headers=auth_headers)
        assert restore_response.status_code == 200, restore_response.get_json()

    def test_restore_product_accepts_post_for_compatibility(self, client, auth_headers):
        product_id = _create_product(client, auth_headers, f"Post Restore {uuid.uuid4().hex[:8]}")

        delete_response = client.delete(f"/api/products/{product_id}", headers=auth_headers)
        assert delete_response.status_code == 200, delete_response.get_json()

        restore_response = client.post(f"/api/products/{product_id}/restore", headers=auth_headers)
        assert restore_response.status_code == 200, restore_response.get_json()


class TestUserImportContracts:
    def test_user_import_creates_worker_with_default_group(self, client, auth_headers):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["username", "name", "employee_no", "role", "password"])
        username = f"import_worker_{uuid.uuid4().hex[:8]}"
        employee_no = f"TEST-IMPORT-{uuid.uuid4().hex[:8]}"
        sheet.append([username, "导入员工", employee_no, "worker", "Test@1234"])

        payload = BytesIO()
        workbook.save(payload)
        workbook.close()
        payload.seek(0)

        response = client.post(
            "/api/users/import",
            headers=auth_headers,
            data={"file": (payload, "users.xlsx")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 200, response.get_json()
        data = response.get_json()
        assert data["success"] == 1
        assert data["skipped"] == 0

        with app.app_context():
            db = get_db()
            row = db.execute(
                "SELECT username, group_name, department_id FROM users WHERE username = ?",
                (username,),
            ).fetchone()

        assert row is not None
        assert row["group_name"] == "员工组"
        assert row["department_id"] is None


class TestUserProcessDisplayContracts:
    def test_worker_list_returns_explicit_and_position_work_processes(self, client, auth_headers):
        with app.app_context():
            db = get_db()
            position_process_id = db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES ('Fixture User Position Process', 'pytest fixture process', 'fixture', 901, 'active', datetime('now','localtime'))"
            ).lastrowid
            explicit_process_id = db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES ('Fixture User Explicit Process', 'pytest fixture process', 'fixture', 902, 'active', datetime('now','localtime'))"
            ).lastrowid
            position_id = db.execute(
                "INSERT INTO positions (name, description, status) VALUES ('Fixture User Position', 'pytest fixture position', 'active')"
            ).lastrowid
            db.execute(
                "INSERT INTO position_processes (position_id, process_id) VALUES (?, ?)",
                (position_id, position_process_id),
            )
            user_id = ensure_user(
                db,
                "test_process_display_worker",
                WORKER_HASH,
                "员工工序展示测试",
                "worker",
                "TEST-PROCESS-DISPLAY",
            )
            db.execute("UPDATE users SET position_id = ? WHERE id = ?", (position_id, user_id))
            db.execute(
                "INSERT INTO user_processes (user_id, process_id) VALUES (?, ?)",
                (user_id, explicit_process_id),
            )
            db.commit()

        response = client.get("/api/users?role=worker&limit=200", headers=auth_headers)
        assert response.status_code == 200, response.get_json()
        row = next(item for item in response.get_json()["users"] if item["id"] == user_id)

        assert row["process_ids"] == str(explicit_process_id)
        assert row["process_ids_junction"] == str(explicit_process_id)
        assert {item["name"] for item in row["explicit_processes"]} == {"Fixture User Explicit Process"}
        assert {item["name"] for item in row["position_processes"]} == {"Fixture User Position Process"}
        assert {item["name"] for item in row["work_processes"]} == {
            "Fixture User Position Process",
            "Fixture User Explicit Process",
        }
        assert "Fixture User Position Process" in row["work_process_names"]
        assert "Fixture User Explicit Process" in row["work_process_names"]

    def test_runtime_process_scope_includes_user_processes_junction(self, client):
        with app.app_context():
            db = get_db()
            position_process_id = db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES ('Fixture Runtime Position Process', 'pytest fixture process', 'fixture', 903, 'active', datetime('now','localtime'))"
            ).lastrowid
            explicit_process_id = db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES ('Fixture Runtime Explicit Process', 'pytest fixture process', 'fixture', 904, 'active', datetime('now','localtime'))"
            ).lastrowid
            position_id = db.execute(
                "INSERT INTO positions (name, description, status) VALUES ('Fixture Runtime Position', 'pytest fixture position', 'active')"
            ).lastrowid
            db.execute(
                "INSERT INTO position_processes (position_id, process_id) VALUES (?, ?)",
                (position_id, position_process_id),
            )
            user_id = ensure_user(
                db,
                "test_process_runtime_worker",
                WORKER_HASH,
                "运行时工序权限测试",
                "worker",
                "TEST-PROCESS-RUNTIME",
            )
            db.execute("UPDATE users SET position_id = ?, process_ids = '' WHERE id = ?", (position_id, user_id))
            db.execute(
                "INSERT INTO user_processes (user_id, process_id) VALUES (?, ?)",
                (user_id, explicit_process_id),
            )
            db.commit()

            user = dict(db.execute(
                "SELECT id, username, role, process_ids, position_id FROM users WHERE id = ?",
                (user_id,),
            ).fetchone())
            process_scope = get_user_process_ids(user)

        assert process_scope == sorted([position_process_id, explicit_process_id])
