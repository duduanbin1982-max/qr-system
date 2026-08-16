import io
import os

import bcrypt
import pytest
from werkzeug.datastructures import FileStorage

from factories import ensure_process
from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.services.user_service import UserService


def _admin_id(db):
    return db.execute(
        "SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id "
        "JOIN roles r ON r.id = ur.role_id WHERE r.code = 'admin' LIMIT 1"
    ).fetchone()["id"]


def test_create_worker_assigns_processes_and_worker_list_excludes_admin(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, "员工授权工序")
        user_id, raw_password = UserService.create_user({
            "username": "serviceworker",
            "name": "服务层员工",
            "password": "Worker123",
            "marker": "A班",
            "process_ids": f"{process_id},999999",
        })

        assert raw_password == "Worker123"
        detail = UserService.get_user_detail(user_id)
        assert detail["marker"] == "A班"
        assert [item["id"] for item in detail["assigned_processes"]] == [process_id]
        assignment = db.execute(
            "SELECT * FROM performance_assignment_history WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        assert assignment["employee_name_snapshot"] == "服务层员工"
        assert assignment["source_type"] == "user_created"
        assert assignment["valid_to"] == ""

        workers = UserService.list_users(role_filter="worker", limit=100)["users"]
        assert any(user["id"] == user_id for user in workers)
        assert all(not user["is_admin_user"] for user in workers)


def test_create_admin_requires_existing_administrator(client):
    with client.application.app_context():
        db = get_db()
        with pytest.raises(ValueError, match="Only administrators"):
            UserService.create_user({
                "username": "blockedadmin",
                "name": "无权限管理员",
                "role": "admin",
                "password": "Admin123",
            })

        user_id, _ = UserService.create_user({
            "username": "allowedadmin",
            "name": "授权管理员",
            "role": "admin",
            "password": "Admin123",
            "_caller_user_id": _admin_id(db),
        })
        assert UserService.get_user(user_id)["role"] == "admin"


def test_update_user_syncs_processes_and_protects_role_changes(client):
    with client.application.app_context():
        db = get_db()
        first_process = ensure_process(db, "员工更新工序一")
        second_process = ensure_process(db, "员工更新工序二", 2)
        user_id, _ = UserService.create_user({
            "username": "updateworker",
            "name": "待更新员工",
            "password": "Worker123",
            "process_ids": str(first_process),
        })

        UserService.update_user(
            user_id,
            {"name": "已更新员工", "process_ids": str(second_process)},
            current_user_id=_admin_id(db),
        )
        detail = UserService.get_user_detail(user_id)
        assert detail["name"] == "已更新员工"
        assert [item["id"] for item in detail["assigned_processes"]] == [second_process]

        with pytest.raises(ValueError, match="Only administrators"):
            UserService.update_user(user_id, {"role": "admin"})
        with pytest.raises(ValueError, match="own role"):
            UserService.update_user(
                _admin_id(db), {"role": "worker"}, current_user_id=_admin_id(db)
            )


def test_batch_status_soft_delete_restore_and_permanent_delete(client):
    with client.application.app_context():
        db = get_db()
        first_id, _ = UserService.create_user({
            "username": "batchuser1", "name": "批量员工一", "password": "Worker123"
        })
        second_id, _ = UserService.create_user({
            "username": "batchuser2", "name": "批量员工二", "password": "Worker123"
        })
        db.execute(
            "UPDATE users SET token = 'batch-session-token' WHERE id = ?",
            (first_id,),
        )
        db.execute(
            "INSERT INTO user_sessions (user_id, token) VALUES (?, 'batch-session-token')",
            (first_id,),
        )
        db.commit()

        assert UserService.batch_update_status([first_id, second_id], "inactive") == 2
        assert db.execute(
            "SELECT token FROM users WHERE id = ?", (first_id,)
        ).fetchone()["token"] is None
        assert db.execute(
            "SELECT COUNT(*) FROM user_sessions WHERE user_id = ?", (first_id,)
        ).fetchone()[0] == 0
        with pytest.raises(ValueError, match="Invalid status"):
            UserService.batch_update_status([first_id], "deleted")

        assert UserService.batch_delete_users([first_id, second_id], _admin_id(db)) == 2
        assert UserService.restore_user(first_id) is True
        assert UserService.delete_user(first_id, _admin_id(db)) is True
        admin_id = _admin_id(db)
        db.execute(
            "INSERT INTO audit_logs (user_id, action, target_type, target_id, detail) "
            "VALUES (?, 'historical_action', 'user', ?, 'must remain')",
            (first_id, first_id),
        )
        batch_id = db.execute(
            "INSERT INTO payroll_batches "
            "(payroll_month, version, period_start, period_end, source_cutoff_at) "
            "VALUES ('2099-01', 1, '2099-01-01 07:00:00', "
            "'2099-02-01 07:00:00', '2099-02-02 00:00:00')"
        ).lastrowid
        db.execute(
            "INSERT INTO payroll_employee_lines "
            "(batch_id, employee_id, employee_name_snapshot, employee_no_snapshot) "
            "VALUES (?, ?, '批量员工一', 'HIST-001')",
            (batch_id, first_id),
        )
        db.commit()

        assert UserService.permanent_delete_user(
            first_id, admin_id, "员工已离职并完成归档"
        ) is True
        user = db.execute(
            "SELECT * FROM users WHERE id = ?", (first_id,)
        ).fetchone()
        assert user["status"] == "deleted"
        assert user["username"] == "purged_user_" + str(first_id)
        assert user["name"] == "已删除员工#" + str(first_id)
        assert user["employee_no"] is None
        assert user["purged_at"]
        assert user["purged_by"] == admin_id
        assert user["purge_reason"] == "员工已离职并完成归档"
        assert db.execute(
            "SELECT COUNT(*) FROM audit_logs "
            "WHERE user_id = ? AND action = 'historical_action'",
            (first_id,),
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT employee_id FROM payroll_employee_lines WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()["employee_id"] == first_id
        assert db.execute(
            "SELECT COUNT(*) FROM performance_assignment_history WHERE user_id = ?",
            (first_id,),
        ).fetchone()[0] >= 2
        assert db.execute(
            "SELECT COUNT(*) FROM user_roles WHERE user_id = ?", (first_id,)
        ).fetchone()[0] == 0
        with pytest.raises(ConflictError, match="cannot be restored"):
            UserService.restore_user(first_id)
        assert UserService.permanent_delete_user(
            second_id, admin_id, "第二名员工离职归档"
        ) is True
        assert db.execute(
            "SELECT employee_no FROM users WHERE id = ?", (second_id,)
        ).fetchone()["employee_no"] is None


def test_role_changes_require_admin_and_batch_is_atomic(client):
    with client.application.app_context():
        db = get_db()
        admin_id = _admin_id(db)
        worker_role_id = db.execute(
            "SELECT id FROM roles WHERE code = 'worker'"
        ).fetchone()["id"]
        admin_role_id = db.execute(
            "SELECT id FROM roles WHERE code = 'admin'"
        ).fetchone()["id"]
        first_id, _ = UserService.create_user({
            "username": "roleworker1", "name": "角色员工一", "password": "Worker123"
        })
        second_id, _ = UserService.create_user({
            "username": "roleworker2", "name": "角色员工二", "password": "Worker123"
        })

        with pytest.raises(PermissionError, match="users:admin"):
            UserService.set_user_roles(first_id, [admin_role_id], second_id)
        with pytest.raises(ConflictError, match="own roles"):
            UserService.set_user_roles(admin_id, [worker_role_id], admin_id)
        active_admin_ids = [
            row["id"]
            for row in db.execute(
                "SELECT DISTINCT u.id FROM users u "
                "JOIN user_roles ur ON ur.user_id = u.id "
                "JOIN roles r ON r.id = ur.role_id "
                "WHERE r.code = 'admin' AND u.status = 'active'"
            ).fetchall()
        ]
        with pytest.raises(ConflictError, match="deactivate all administrators"):
            UserService.batch_update_status(active_admin_ids, "inactive")
        with pytest.raises(ValueError, match="User not found"):
            UserService.batch_set_user_roles(
                [first_id, 999999], [admin_role_id], "add", admin_id
            )
        assert db.execute(
            "SELECT COUNT(*) FROM user_roles "
            "WHERE user_id = ? AND role_id = ?",
            (first_id, admin_role_id),
        ).fetchone()[0] == 0


def test_employee_number_is_normalized_unique_and_position_can_be_cleared(client):
    with client.application.app_context():
        db = get_db()
        position_id = db.execute(
            "INSERT INTO positions (name, status) VALUES ('临时岗位', 'active')"
        ).lastrowid
        db.commit()
        first_id, _ = UserService.create_user({
            "username": "employeenumber1",
            "name": "工号员工一",
            "password": "Worker123",
            "employee_no": " Staff-01 ",
            "position_id": position_id,
        })
        with pytest.raises(ConflictError, match="Employee number"):
            UserService.create_user({
                "username": "employeenumber2",
                "name": "工号员工二",
                "password": "Worker123",
                "employee_no": "staff-01",
            })
        UserService.update_user(
            first_id, {"position_id": None}, current_user_id=_admin_id(db)
        )
        row = db.execute(
            "SELECT employee_no, position_id FROM users WHERE id = ?", (first_id,)
        ).fetchone()
        assert tuple(row) == ("Staff-01", None)


def test_privileged_import_requires_admin_and_rolls_back_file(client, tmp_path):
    with client.application.app_context():
        db = get_db()
        from openpyxl import Workbook

        worker_id, _ = UserService.create_user({
            "username": "importcaller",
            "name": "普通导入人",
            "password": "Worker123",
        })
        workbook_path = tmp_path / "privileged-users.xlsx"
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["username", "name", "password", "role"])
        worksheet.append(["rollbackworker", "应回滚员工", "Worker123", "worker"])
        worksheet.append(["blockedimportadmin", "越权管理员", "Admin123", "admin"])
        workbook.save(workbook_path)
        workbook.close()

        with pytest.raises(PermissionError, match="administrators"):
            UserService.import_users(str(workbook_path), caller_id=worker_id)
        assert db.execute(
            "SELECT 1 FROM users WHERE username IN "
            "('rollbackworker', 'blockedimportadmin')"
        ).fetchone() is None


def test_reset_password_validates_strength_and_unlocks_account(client):
    with client.application.app_context():
        db = get_db()
        user_id, _ = UserService.create_user({
            "username": "passworduser", "name": "密码员工", "password": "Worker123"
        })
        db.execute(
            "UPDATE users SET failed_login_count = 5, locked_until = '2099-01-01 00:00:00' "
            "WHERE id = ?",
            (user_id,),
        )
        db.commit()

        with pytest.raises(ValueError, match="at least 8"):
            UserService.reset_password(user_id, "A1short")
        new_password = UserService.reset_password(user_id, "NewPass123")
        assert new_password == "NewPass123"
        row = db.execute(
            "SELECT password, failed_login_count, locked_until FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        assert bcrypt.checkpw(new_password.encode(), row["password"].encode())
        assert row["failed_login_count"] == 0
        assert row["locked_until"] is None
        assert UserService.unlock_user(user_id) == "passworduser"


def test_import_export_and_document_lifecycle(client, tmp_path):
    with client.application.app_context():
        db = get_db()
        from openpyxl import Workbook

        workbook_path = tmp_path / "users.xlsx"
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["username", "name", "password", "role"])
        worksheet.append(["importeduser", "导入员工", "Import123", "worker"])
        worksheet.append(["", "", "", ""])
        workbook.save(workbook_path)
        workbook.close()

        imported = UserService.import_users(str(workbook_path), caller_id=_admin_id(db))
        assert imported["success"] == 1
        assert imported["skipped"] == 1
        user_id = db.execute(
            "SELECT id FROM users WHERE username = 'importeduser'"
        ).fetchone()["id"]
        assignment = db.execute(
            "SELECT source_type, valid_to FROM performance_assignment_history WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        assert tuple(assignment) == ("user_imported", "")
        assert UserService.export_users(role_filter="worker").getbuffer().nbytes > 0

        upload_dir = tmp_path / "documents"
        storage = FileStorage(stream=io.BytesIO(b"certificate"), filename="certificate.txt")
        uploaded = UserService.upload_user_document(
            user_id, storage, "certificate", _admin_id(db), str(upload_dir)
        )
        assert uploaded["size"] == len(b"certificate")
        document = UserService.list_user_documents(user_id)[0]
        metadata, filepath = UserService.get_user_document_file(
            user_id, document["id"], str(upload_dir)
        )
        assert metadata["doc_name"] == "certificate.txt"
        assert os.path.exists(filepath)

        UserService.delete_user_document(user_id, document["id"], str(upload_dir))
        assert not os.path.exists(filepath)
        assert UserService.list_user_documents(user_id) == []
