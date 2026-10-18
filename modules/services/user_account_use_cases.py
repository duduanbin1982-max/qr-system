"""Account lifecycle use cases behind the stable ``UserService`` facade."""

import bcrypt
import secrets

from modules.domain.errors import ConflictError, NotFoundError
from modules.repositories.user_repository import UserRepository
from modules.services import BaseService
from modules.services.administrator_policy import AdministratorPolicy
from modules.services.user_performance_assignment_coordinator import (
    UserPerformanceAssignmentCoordinator,
)
from modules.services.user_role_use_cases import UserRoleUseCases


class UserAccountUseCases:
    """Create, update, lifecycle, and password use cases for employees."""

    @staticmethod
    def validate_process_ids(data):
        if "process_ids" in data and data["process_ids"]:
            id_list = [int(x.strip()) for x in data["process_ids"].split(",") if x.strip()]
            if id_list:
                valid_ids = UserRepository.validate_process_ids(id_list)
                filtered = [str(x) for x in id_list if x in valid_ids]
                data["process_ids"] = ",".join(filtered) if filtered else ""
                data["_valid_process_ids"] = [int(x) for x in filtered] if filtered else []

    @staticmethod
    def next_employee_no(data, db):
        employee_no = (data.get("employee_no") or "").strip()
        if employee_no:
            if UserRepository.find_user_by_employee_no(employee_no, db=db):
                raise ConflictError("Employee number already exists")
            return employee_no
        next_no = UserRepository.get_next_employee_no(db=db)
        employee_no = str(next_no).zfill(4)
        while UserRepository.check_employee_no_exists(employee_no, db=db):
            next_no += 1
            employee_no = str(next_no).zfill(4)
        return employee_no

    @staticmethod
    def hash_or_generate_password(data):
        raw_pw = (data.get("password") or "").strip() or secrets.token_urlsafe(8)
        if data.get("password") and len(raw_pw) < 6:
            raise ValueError("Password must be at least 6 characters")
        return raw_pw, bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt(rounds=12)).decode()

    @staticmethod
    def build_update_fields(data):
        if "employee_no" in data and not data["employee_no"]:
            del data["employee_no"]
        sets = []
        params = []
        for field in [
            "name", "nickname", "email", "group_name", "role", "employee_no",
            "marker", "phone", "status", "position_id", "department_id",
        ]:
            if field in data:
                sets.append(field + " = ?")
                params.append(data[field])
        if "password" in data and data["password"]:
            sets.append("password = ?")
            params.append(
                bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt(rounds=12)).decode()
            )
        if not sets:
            raise ValueError("No update fields provided")
        return sets, params

    @staticmethod
    def sync_user_processes(uid, data, txn):
        if "process_ids" not in data and "_valid_process_ids" not in data:
            return
        UserRepository.delete_user_processes_txn(uid, db=txn)
        valid_pids = data.get("_valid_process_ids", [])
        if not valid_pids and data.get("process_ids"):
            valid_pids = [int(x.strip()) for x in data["process_ids"].split(",") if x.strip()]
        for pid in valid_pids:
            UserRepository.insert_user_process_txn(uid, pid, db=txn)

    @staticmethod
    def audit_user_update(uid, data, existing, current_user_id, db):
        changed = []
        field_labels = {
            "name": "Name", "nickname": "Nickname", "email": "Email", "phone": "Phone",
            "role": "Role", "employee_no": "Employee No", "marker": "Marker",
            "group_name": "Role Group", "position_id": "Position ID",
            "department_id": "Department ID", "status": "Status",
        }
        for field, label in field_labels.items():
            old_val = existing[field] if field in existing.keys() else None
            if field not in data:
                continue
            new_val = data.get(field)
            if str(old_val) != str(new_val):
                changed.append(label + ": " + str(old_val) + " -> " + str(new_val))
        if "password" in data and data["password"]:
            changed.append("Password: changed")
        if changed:
            UserRepository.insert_audit_log_txn(
                current_user_id,
                "update_user",
                "user",
                uid,
                "; ".join(changed),
                db=db,
            )

    @classmethod
    def create_user(cls, data):
        username = data.get("username", "").strip()
        name = data.get("name", "").strip()
        status = AdministratorPolicy.normalize_status(data.get("status", "active"))
        if not name and data.get("role") == "admin":
            name = username
        UserRoleUseCases.validate_username(username, name)

        db = BaseService.db()
        role_id, role_code = UserRoleUseCases.resolve_create_role(data, db)
        UserRoleUseCases.ensure_admin_creator(role_code, data.get("_caller_user_id"), db)
        if UserRepository.find_user_by_username(username, db=db):
            raise ConflictError("Username already exists")

        position_id = data.get("position_id")
        if position_id and not UserRepository.find_position_by_id(position_id, db=db):
            raise NotFoundError("Specified position does not exist")
        department_id = data.get("department_id")
        if department_id and not UserRepository.find_department_by_id(department_id, db=db):
            raise NotFoundError("Specified department does not exist")

        cls.validate_process_ids(data)
        raw_pw, pw = cls.hash_or_generate_password(data)

        with BaseService.transaction() as txn:
            UserRoleUseCases.ensure_admin_creator(
                role_code, data.get("_caller_user_id"), txn
            )
            if UserRepository.find_user_by_username(username, db=txn):
                raise ConflictError("Username already exists")
            data["employee_no"] = cls.next_employee_no(data, txn)
            uid = UserRepository.insert_user_txn(
                username=username, pw_hash=pw, name=name,
                nickname=data.get("nickname", ""), email=data.get("email", ""),
                group_name=data.get("group_name", "员工组"), role=role_code,
                employee_no=data.get("employee_no", ""),
                marker=(data.get("marker") or "").strip(), phone=data.get("phone", ""),
                position_id=position_id or None, department_id=department_id or None,
                status=status, db=txn,
            )
            UserRepository.insert_user_role_txn(uid, role_id, db=txn)
            valid_pids = data.get("_valid_process_ids", [])
            if not valid_pids and data.get("process_ids"):
                valid_pids = [int(x.strip()) for x in data["process_ids"].split(",") if x.strip()]
            for pid in valid_pids:
                UserRepository.insert_user_process_txn(uid, pid, db=txn)
            UserPerformanceAssignmentCoordinator.record_initial(
                uid,
                created_by=data.get("_caller_user_id"),
                source_type="user_created",
                db=txn,
            )
            UserRepository.insert_audit_log_txn(
                data.get("_caller_user_id"), "create_user", "user", uid,
                "role=" + role_code + "; status=" + status, db=txn,
            )
        return uid, raw_pw

    @classmethod
    def update_user(cls, uid, data, current_user_id=None):
        if "status" in data:
            data["status"] = AdministratorPolicy.normalize_status(data["status"])
        db = BaseService.db()
        existing = UserRepository.find_user_by_id_for_update(uid, db=db)
        if not existing:
            raise NotFoundError("User not found")

        if "position_id" in data and data["position_id"]:
            if not UserRepository.find_position_by_id(data["position_id"], db=db):
                raise NotFoundError("Specified position does not exist")
        if "department_id" in data:
            department_id = data["department_id"]
            if department_id and not UserRepository.find_department_by_id(department_id, db=db):
                raise NotFoundError("Specified department does not exist")

        cls.validate_process_ids(data)
        old_role = UserRepository.get_primary_role_code(uid, db=db) or existing["role"]
        new_role_id, new_role_code = UserRoleUseCases.resolve_update_role(
            uid, data, old_role, current_user_id, db
        )
        if "employee_no" in data:
            data["employee_no"] = (data.get("employee_no") or "").strip()
        sets, params = cls.build_update_fields(data)

        with BaseService.transaction() as txn:
            existing = UserRepository.find_user_by_id_for_update(uid, db=txn)
            if not existing:
                raise NotFoundError("User not found")
            AdministratorPolicy.protect_admin_accounts(current_user_id, [uid], txn)
            if uid == current_user_id and data.get("status") and data["status"] != existing["status"]:
                raise ConflictError("Cannot change your own status")
            if (
                data.get("status") == "inactive"
                and UserRepository.has_admin_assignment(uid, db=txn)
                and UserRepository.count_admin_roles(db=txn) <= 1
            ):
                raise ConflictError("Cannot deactivate the last administrator")
            if "employee_no" in data:
                conflict = UserRepository.find_user_by_employee_no(
                    data["employee_no"], exclude_user_id=uid, db=txn
                )
                if conflict:
                    raise ConflictError("Employee number already exists")
            cls.sync_user_processes(uid, data, txn)
            UserRepository.update_user_txn(uid, ", ".join(sets), params, db=txn)
            UserRoleUseCases.apply_role_update(
                uid, old_role, new_role_id, new_role_code, txn
            )
            UserPerformanceAssignmentCoordinator.record_snapshot_change(
                uid, existing, created_by=current_user_id, db=txn
            )
            cls.audit_user_update(uid, data, existing, current_user_id, txn)
        return True

    @staticmethod
    def restore_user(uid, actor_id=None):
        with BaseService.transaction() as txn:
            user = UserRepository.find_user_by_id_for_update(uid, db=txn)
            if not user or user["status"] != "deleted":
                raise NotFoundError("User not found or not deleted")
            AdministratorPolicy.protect_admin_accounts(actor_id, [uid], txn)
            if user["purged_at"]:
                raise ConflictError("An anonymized employee identity cannot be restored")
            UserRepository.restore_user_txn(uid, db=txn)
            UserPerformanceAssignmentCoordinator.record_snapshot_change(uid, user, db=txn)
            UserRepository.insert_audit_log_txn(
                actor_id, "restore_user", "user", uid, "status=active", db=txn
            )
        return True

    @staticmethod
    def permanent_delete_user(uid, actor_id, reason):
        reason = (reason or "").strip()
        if len(reason) < 4:
            raise ValueError("Purge reason must be at least 4 characters")
        with BaseService.transaction() as txn:
            UserRoleUseCases.require_role_administrator(actor_id, txn)
            user = UserRepository.find_deleted_user(uid, db=txn)
            if not user:
                raise ConflictError("Can only permanently delete trashed users")
            if user["purged_at"]:
                raise ConflictError("User identity has already been purged")
            password_hash = bcrypt.hashpw(
                secrets.token_urlsafe(32).encode(), bcrypt.gensalt(rounds=12)
            ).decode()
            UserRepository.anonymize_deleted_user_txn(
                uid, actor_id, reason, password_hash, db=txn
            )
            UserRepository.insert_audit_log_txn(
                actor_id, "anonymize_user_identity", "user", uid,
                "reason=" + reason, db=txn,
            )
        return True

    @staticmethod
    def delete_user(uid, current_user_id):
        if uid == current_user_id:
            raise ConflictError("Cannot delete self")
        with BaseService.transaction() as txn:
            before = UserRepository.find_user_by_id_for_update(uid, db=txn)
            if not before:
                raise NotFoundError("User not found")
            AdministratorPolicy.protect_admin_accounts(current_user_id, [uid], txn)
            if UserRepository.check_admin_role(uid, db=txn):
                if UserRepository.count_admin_roles(db=txn) <= 1:
                    raise ConflictError("Cannot delete the last administrator")
            UserRepository.soft_delete_user_txn(uid, db=txn)
            UserPerformanceAssignmentCoordinator.record_snapshot_change(
                uid, before, created_by=current_user_id, db=txn
            )
            UserRepository.insert_audit_log_txn(
                current_user_id, "delete_user", "user", uid, "status=deleted", db=txn
            )
        return True

    @classmethod
    def batch_update_status(cls, ids, status, current_user_id=None):
        if not ids:
            return 0
        ids = UserRoleUseCases.normalize_ids(ids, "ids")
        if current_user_id and current_user_id in ids:
            raise ConflictError("Cannot change own status")
        if status not in ("active", "inactive"):
            raise ValueError("Invalid status")
        with BaseService.transaction() as txn:
            AdministratorPolicy.protect_admin_accounts(current_user_id, ids, txn)
            if status == "inactive":
                admin_count = UserRepository.count_admin_roles_in_ids(ids, db=txn)
                if admin_count > 0 and UserRepository.count_admin_roles(db=txn) <= admin_count:
                    raise ConflictError("Cannot deactivate all administrators")
            before_rows = {
                row["id"]: row
                for row in UserRepository.find_users_by_ids_for_update(ids, db=txn)
            }
            count = UserRepository.batch_update_status_txn(ids, status, db=txn)
            after_rows = {
                row["id"]: row
                for row in UserRepository.find_users_by_ids_for_update(ids, db=txn)
            }
            UserPerformanceAssignmentCoordinator.record_status_changes(
                before_rows, after_rows, created_by=current_user_id, db=txn
            )
            UserRepository.insert_audit_log_txn(
                current_user_id, "batch_update_status", "user", 0,
                "status=" + status + "; user_ids=" + ",".join(str(item) for item in ids),
                db=txn,
            )
        return count

    @classmethod
    def batch_delete_users(cls, ids, current_user_id):
        if not ids:
            return 0
        ids = UserRoleUseCases.normalize_ids(ids, "ids")
        if current_user_id in ids:
            raise ConflictError("Cannot delete self")
        with BaseService.transaction() as txn:
            AdministratorPolicy.protect_admin_accounts(current_user_id, ids, txn)
            admin_count = UserRepository.count_admin_roles_in_ids(ids, db=txn)
            if admin_count > 0 and UserRepository.count_admin_roles(db=txn) <= admin_count:
                raise ConflictError("Cannot remove all administrators")
            before_rows = {
                row["id"]: row
                for row in UserRepository.find_users_by_ids_for_update(ids, db=txn)
            }
            count = UserRepository.batch_soft_delete_users_txn(ids, db=txn)
            UserPerformanceAssignmentCoordinator.record_deleted_users(
                before_rows, created_by=current_user_id, db=txn
            )
            UserRepository.insert_audit_log_txn(
                current_user_id, "batch_delete_users", "user", 0,
                "user_ids=" + ",".join(str(item) for item in ids), db=txn,
            )
        return count

    @staticmethod
    def reset_password(uid, password=None, actor_id=None):
        new_pw = password if password else secrets.token_urlsafe(8)
        if password:
            if len(password) < 8:
                raise ValueError("Password must be at least 8 characters")
            if not any(c.isalpha() for c in password):
                raise ValueError("Password must contain at least one letter")
            if not any(c.isdigit() for c in password):
                raise ValueError("Password must contain at least one digit")
        hashed = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt(rounds=12)).decode()

        db = BaseService.db()
        existing = UserRepository.find_user_status(uid, db=db)
        if not existing:
            raise NotFoundError("User not found")
        if existing["status"] != "active":
            raise ConflictError("User is disabled, cannot reset password")

        with BaseService.transaction() as txn:
            AdministratorPolicy.require_actual_admin(actor_id, txn)
            UserRepository.reset_password_txn(uid, hashed, db=txn)
            UserRepository.insert_audit_log_txn(
                actor_id, "reset_password", "user", uid,
                "password_changed=true", db=txn,
            )
        return new_pw

    @staticmethod
    def unlock_user(uid, actor_id=None):
        db = BaseService.db()
        row = UserRepository.find_user_by_id_basic(uid, db=db)
        if not row:
            raise NotFoundError("User not found")
        with BaseService.transaction() as txn:
            AdministratorPolicy.require_actual_admin(actor_id, txn)
            UserRepository.unlock_user_txn(uid, db=txn)
            UserRepository.insert_audit_log_txn(
                actor_id, "unlock_user", "user", uid,
                "account_unlocked=true", db=txn,
            )
        return row["username"]
