from io import BytesIO
import uuid

import openpyxl

from modules.app import app
from modules.db import get_db


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
