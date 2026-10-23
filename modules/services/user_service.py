"""qr-system - stable UserService facade.

Account, role, import, and employee-document use cases are implemented behind
this compatibility facade. SQL remains delegated to repositories.
"""
from modules.domain.errors import NotFoundError
import os
from io import BytesIO

from openpyxl import Workbook
from modules.services import BaseService
from modules.services.employee_document_storage import EmployeeDocumentStorage
from modules.services.user_account_use_cases import UserAccountUseCases
from modules.services.user_performance_assignment_coordinator import (
    UserPerformanceAssignmentCoordinator,
)
from modules.services.user_role_use_cases import UserRoleUseCases
from modules.services.user_import_adapter import (
    USER_IMPORT_EN_MAP,
    USER_IMPORT_FIELD_MAP,
    USER_IMPORT_FIELDS,
    UserImportWorkbookAdapter,
)
from modules.repositories.user_repository import UserRepository
from modules.config import (
    EMPLOYEE_DOCUMENT_ALLOWED_EXTENSIONS,
    EMPLOYEE_DOCUMENT_MAX_BYTES,
)

class UserService:
    """User management business logic. All methods are static."""

    @staticmethod
    def _validate_process_ids(data):
        return UserAccountUseCases.validate_process_ids(data)

    @staticmethod
    def _validate_username(username, name):
        return UserRoleUseCases.validate_username(username, name)

    @staticmethod
    def _resolve_role(data, db):
        return UserRoleUseCases.resolve_create_role(data, db)

    @staticmethod
    def _ensure_admin_creator(role_code, caller_id, db):
        return UserRoleUseCases.ensure_admin_creator(role_code, caller_id, db)

    @staticmethod
    def _next_employee_no(data, db):
        return UserAccountUseCases.next_employee_no(data, db)

    @staticmethod
    def _hash_or_generate_password(data):
        return UserAccountUseCases.hash_or_generate_password(data)

    @staticmethod
    def _resolve_update_role(uid, data, old_role, current_user_id, db):
        return UserRoleUseCases.resolve_update_role(
            uid, data, old_role, current_user_id, db
        )

    @staticmethod
    def _build_update_fields(data):
        return UserAccountUseCases.build_update_fields(data)

    @staticmethod
    def _sync_user_processes(uid, data, txn):
        return UserAccountUseCases.sync_user_processes(uid, data, txn)

    @staticmethod
    def _apply_role_update(uid, old_role, new_role_id, new_role_code, txn):
        return UserRoleUseCases.apply_role_update(
            uid, old_role, new_role_id, new_role_code, txn
        )

    @staticmethod
    def _audit_user_update(uid, data, existing, current_user_id, db):
        return UserAccountUseCases.audit_user_update(
            uid, data, existing, current_user_id, db
        )

    # ============================================================
    # Query
    # ============================================================

    @staticmethod
    def list_users(page=1, limit=20, role_filter="", role_not="", keyword="", status=""):
        """Paginated user list."""
        return UserRepository.list_users(
            page=page, limit=limit, role_filter=role_filter,
            role_not=role_not, keyword=keyword, status=status
        )

    # ============================================================
    # Role administration
    # ============================================================

    @staticmethod
    def _normalize_ids(values, label):
        return UserRoleUseCases.normalize_ids(values, label)

    @staticmethod
    def _require_role_administrator(actor_id, db):
        return UserRoleUseCases.require_role_administrator(actor_id, db)

    @staticmethod
    def _prepare_role_change(user_id, role_ids, action, db):
        return UserRoleUseCases.prepare_role_change(user_id, role_ids, action, db)

    @staticmethod
    def _apply_role_change(user_id, requested_ids, proposed_ids, proposed_codes, action, actor_id, db):
        return UserRoleUseCases.apply_role_change(
            user_id, requested_ids, proposed_ids, proposed_codes, action, actor_id, db
        )

    @staticmethod
    def set_user_roles(user_id, role_ids, actor_id):
        return UserRoleUseCases.set_user_roles(user_id, role_ids, actor_id)

    @staticmethod
    def batch_set_user_roles(user_ids, role_ids, action, actor_id):
        return UserRoleUseCases.batch_set_user_roles(
            user_ids, role_ids, action, actor_id
        )

    # ============================================================
    # Create
    # ============================================================

    @staticmethod
    def create_user(data):
        return UserAccountUseCases.create_user(data)

    # ============================================================
    # Update
    # ============================================================

    @staticmethod
    def update_user(uid, data, current_user_id=None):
        return UserAccountUseCases.update_user(uid, data, current_user_id)

    # ============================================================
    # Soft Delete / Restore / Permanent Delete
    # ============================================================

    @staticmethod
    def restore_user(uid, actor_id=None):
        return UserAccountUseCases.restore_user(uid, actor_id)

    @staticmethod
    def permanent_delete_user(uid, actor_id, reason):
        return UserAccountUseCases.permanent_delete_user(uid, actor_id, reason)

    @staticmethod
    def delete_user(uid, current_user_id):
        return UserAccountUseCases.delete_user(uid, current_user_id)

    @staticmethod
    def batch_update_status(ids, status, current_user_id=None):
        return UserAccountUseCases.batch_update_status(ids, status, current_user_id)

    @staticmethod
    def batch_delete_users(ids, current_user_id):
        return UserAccountUseCases.batch_delete_users(ids, current_user_id)

    # ============================================================
    # Password Reset & Unlock
    # ============================================================

    @staticmethod
    def reset_password(uid, password=None, actor_id=None):
        return UserAccountUseCases.reset_password(uid, password, actor_id)

    @staticmethod
    def unlock_user(uid, actor_id=None):
        return UserAccountUseCases.unlock_user(uid, actor_id)

    # ============================================================
    # Batch Import
    # ============================================================

    @staticmethod
    def _open_user_import_workbook(filepath):
        return UserImportWorkbookAdapter.open_workbook(filepath)

    @staticmethod
    def _map_user_import_columns(headers):
        return UserImportWorkbookAdapter.map_columns(headers)

    @staticmethod
    def _user_import_row_data(row, col_map):
        return UserImportWorkbookAdapter.row_data(row, col_map)

    @staticmethod
    def _normalize_user_import_identity(row_idx, row_data):
        return UserImportWorkbookAdapter.normalize_identity(row_idx, row_data)

    @staticmethod
    def _resolve_user_import_position(row_data, pos_map):
        pos_name = row_data.get("position_name", "")
        return pos_map.get(pos_name) if pos_name else None

    @staticmethod
    def _resolve_user_import_role(row_data, caller_id, db):
        role = (row_data.get("role") or "worker").strip()
        role_row = UserRepository.find_active_role_by_code(role, db=db)
        if not role_row:
            raise ValueError("Unknown or inactive role: " + role)
        if role != "worker" and not UserRepository.check_admin_role(caller_id, db=db):
            raise PermissionError("Only administrators can import privileged roles")
        return role, role_row["id"]

    @staticmethod
    def _next_import_employee_no(row_data, db):
        return UserService._next_employee_no(row_data, db)

    @staticmethod
    def _insert_import_user(row_data, username, name, position_id, role, role_id, caller_id, db):
        _, pw_hash = UserService._hash_or_generate_password(row_data)
        uid = UserRepository.insert_user_import_txn(
            username=username, pw_hash=pw_hash, name=name,
            nickname=row_data.get("nickname", ""),
            email=row_data.get("email", ""),
            role="admin" if role == "admin" else "worker",
            employee_no=row_data.get("employee_no", ""),
            phone=row_data.get("phone", ""),
            position_id=position_id, db=db
        )
        UserRepository.insert_user_role_txn(uid, role_id, db=db)
        UserPerformanceAssignmentCoordinator.record_initial(
            uid, created_by=caller_id, source_type="user_imported", db=db
        )
        return uid

    @staticmethod
    def _import_user_row(row_idx, row, col_map, pos_map, caller_id, db):
        row_data = UserService._user_import_row_data(row, col_map)
        username, name, identity_error = UserService._normalize_user_import_identity(row_idx, row_data)
        if identity_error:
            return False, identity_error
        UserService._validate_username(username, name)
        if UserRepository.find_user_by_username(username, db=db):
            return False, "Row " + str(row_idx) + ": username " + username + " already exists"

        position_id = UserService._resolve_user_import_position(row_data, pos_map)
        if row_data.get("position_name") and not position_id:
            return False, "Row " + str(row_idx) + ": unknown position " + row_data["position_name"]
        role, role_id = UserService._resolve_user_import_role(row_data, caller_id, db)
        row_data["employee_no"] = UserService._next_import_employee_no(row_data, db)
        UserService._insert_import_user(
            row_data, username, name, position_id, role, role_id, caller_id, db
        )
        return True, None

    @staticmethod
    def import_users(filepath, caller_id=None):
        """Import users from .xlsx file. Returns {success, skipped, errors}."""
        wb, ws = UserService._open_user_import_workbook(filepath)
        try:
            headers = [cell.value for cell in ws[1]]
            col_map = UserService._map_user_import_columns(headers)
            db = BaseService.db()
            pos_rows = UserRepository.get_active_positions(db=db)
            pos_map = {r["name"]: r["id"] for r in pos_rows}

            success = 0
            skipped = 0
            errors = []
            with BaseService.transaction() as txn:
                for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                    try:
                        created, error = UserService._import_user_row(
                            row_idx, row, col_map, pos_map, caller_id, txn
                        )
                        if created:
                            success += 1
                        else:
                            skipped += 1
                            errors.append(error)
                    except PermissionError:
                        raise
                    except Exception as e:
                        skipped += 1
                        errors.append("Row " + str(row_idx) + ": " + str(e)[:80])
                UserRepository.insert_audit_log_txn(
                    caller_id,
                    "import_users",
                    "user",
                    0,
                    "created=" + str(success) + "; skipped=" + str(skipped),
                    db=txn,
                )
        finally:
            wb.close()

        return {
            "success": success,
            "skipped": skipped,
            "total": success + skipped,
            "errors": errors[:20],
            "error_summary": "; ".join(errors[:5]) if errors else "",
        }

    # ============================================================
    # Helpers
    # ============================================================

    @staticmethod
    def get_user(uid):
        """Get single user (without password)."""
        row = UserRepository.find_user_by_id_full(uid)
        if not row:
            raise NotFoundError("User not found")
        u = dict(row)
        u.pop("password", None)
        u.pop("token", None)
        return u

    @staticmethod
    def export_users(role_filter="", keyword="", status=""):
        data = UserService.list_users(1, 9999, role_filter=role_filter, keyword=keyword, status=status)
        users = data.get("users", [])
        wb = Workbook()
        ws = wb.active
        ws.title = "Users"
        ws.append(["用户名", "姓名", "员工编号", "电话", "邮箱", "岗位", "角色", "状态"])
        for user in users:
            ws.append([
                user.get("username", ""),
                user.get("name", ""),
                user.get("employee_no", ""),
                user.get("phone", ""),
                user.get("email", ""),
                user.get("position_name", ""),
                "管理员" if user.get("role") == "admin" else "员工",
                "正常" if user.get("status") == "active" else "已删除" if user.get("status") == "deleted" else "禁用",
            ])
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    @staticmethod
    def get_user_detail(uid):
        user = UserService.get_user(uid)
        db = BaseService.db()
        user["role_names"] = [row["name"] for row in UserRepository.get_user_role_names(uid, db=db)]
        user["assigned_processes"] = [dict(row) for row in UserRepository.get_user_assigned_processes(uid, db=db)]
        stats = UserRepository.get_user_work_stats(uid, db=db)
        user["work_stats"] = dict(stats) if stats else {}
        return user

    @staticmethod
    def list_user_documents(uid):
        return [dict(row) for row in UserRepository.list_user_documents(uid)]

    @staticmethod
    def _employee_document_name(filename):
        return EmployeeDocumentStorage.validate_name(
            filename, EMPLOYEE_DOCUMENT_ALLOWED_EXTENSIONS
        )

    @staticmethod
    def _validate_employee_document_content(filepath, extension, header):
        return EmployeeDocumentStorage.validate_content(filepath, extension, header)

    @staticmethod
    def _employee_document_path(upload_dir, stored_name):
        return EmployeeDocumentStorage.path(upload_dir, stored_name)

    @staticmethod
    def _existing_employee_document_path(
        upload_dir, stored_name, legacy_upload_dir=None
    ):
        return EmployeeDocumentStorage.existing_path(
            upload_dir, stored_name, legacy_upload_dir
        )

    @staticmethod
    def upload_user_document(uid, file_storage, doc_type, uploaded_by, upload_dir):
        prepared = EmployeeDocumentStorage.prepare_upload(
            uid,
            file_storage,
            upload_dir,
            EMPLOYEE_DOCUMENT_ALLOWED_EXTENSIONS,
            EMPLOYEE_DOCUMENT_MAX_BYTES,
        )
        installed = False
        try:
            with BaseService.transaction() as txn:
                if not UserRepository.find_user_by_id_basic(uid, db=txn):
                    raise NotFoundError("User not found")
                document_id = UserRepository.insert_user_document_txn(
                    uid,
                    prepared.original_name,
                    str(doc_type or "")[:64],
                    prepared.stored_name,
                    prepared.file_size,
                    uploaded_by,
                    db=txn,
                )
                EmployeeDocumentStorage.install(prepared)
                installed = True
                UserRepository.insert_audit_log_txn(
                    uploaded_by,
                    "upload_document",
                    "user",
                    uid,
                    "document_id=" + str(document_id) + "; size=" + str(prepared.file_size),
                    db=txn,
                )
        except Exception:
            if installed:
                EmployeeDocumentStorage.remove_installed(prepared)
            raise
        finally:
            EmployeeDocumentStorage.cleanup(prepared)
        return {"filename": prepared.original_name, "size": prepared.file_size}

    @staticmethod
    def get_user_document_file(uid, doc_id, upload_dir, legacy_upload_dir=None):
        doc = UserRepository.find_user_document(uid, doc_id)
        if not doc:
            raise NotFoundError("Document not found")
        doc = dict(doc)
        filepath = UserService._existing_employee_document_path(
            upload_dir, doc["file_path"], legacy_upload_dir
        )
        if not os.path.exists(filepath):
            raise FileNotFoundError("File not found on disk")
        return doc, filepath

    @staticmethod
    def delete_user_document(
        uid, doc_id, upload_dir, actor_id=None, legacy_upload_dir=None
    ):
        quarantine_dir = EmployeeDocumentStorage.ensure_quarantine_dir(upload_dir)
        quarantine_path = None
        filepath = None
        try:
            with BaseService.transaction() as txn:
                row = UserRepository.find_user_document(uid, doc_id, db=txn)
                if not row:
                    raise NotFoundError("Document not found")
                doc = dict(row)
                filepath = UserService._existing_employee_document_path(
                    upload_dir, doc["file_path"], legacy_upload_dir
                )
                if os.path.exists(filepath):
                    quarantine_path = EmployeeDocumentStorage.quarantine(
                        filepath, quarantine_dir
                    )
                UserRepository.delete_user_document_txn(doc_id, db=txn)
                UserRepository.insert_audit_log_txn(
                    actor_id,
                    "delete_document",
                    "user",
                    uid,
                    "document_id=" + str(doc_id),
                    db=txn,
                )
        except Exception:
            EmployeeDocumentStorage.restore_quarantine(quarantine_path, filepath)
            raise
        EmployeeDocumentStorage.discard_quarantine(quarantine_path)
        return doc
