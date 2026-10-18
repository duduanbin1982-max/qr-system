"""Public role and authorization use cases for user management.

The legacy ``UserService`` facade delegates here while keeping its public method
signatures stable.  These methods own role invariants and never call facade
private helpers.
"""

from modules.domain.errors import ConflictError, NotFoundError
from modules.repositories.user_repository import UserRepository
from modules.services import BaseService
from modules.services.administrator_policy import AdministratorPolicy


class UserRoleUseCases:
    """Role resolution, role changes, and privileged user policy."""

    @staticmethod
    def validate_username(username, name):
        if not username or not name:
            raise ValueError("Username and name cannot be empty")
        if len(username) < 2 or len(username) > 32:
            raise ValueError("Username must be 2-32 characters")
        if not all(char.isalnum() or char in "_-." for char in username):
            raise ValueError(
                "Username can only contain letters, digits, underscores, hyphens and dots"
            )

    @staticmethod
    def resolve_create_role(data, db):
        role_id = data.get("role_id")
        role_code = (data.get("role") or "").strip()
        if role_id:
            role_code = UserRepository.find_role_code_by_id(role_id, db=db)
            if not role_code:
                raise NotFoundError("Specified role does not exist")
            return role_id, role_code
        if not role_code:
            role_code = "worker"
        role_row = UserRepository.find_role_by_code(role_code, db=db)
        if not role_row:
            role_row = UserRepository.find_role_by_code("worker", db=db)
            role_code = "worker"
        return (role_row[0] if role_row else 2), role_code

    @staticmethod
    def ensure_admin_creator(role_code, caller_id, db):
        if role_code == "worker":
            return
        AdministratorPolicy.require_actual_admin(
            caller_id,
            db,
            message="仅系统管理员可以创建特权账号",
        )

    @staticmethod
    def resolve_update_role(uid, data, old_role, current_user_id, db):
        new_role_id = None
        new_role_code = None
        if ("role" in data and data["role"] != old_role) or ("role_id" in data):
            new_role_id = data.get("role_id")
            if new_role_id:
                new_role_code = UserRepository.find_role_code_by_id(new_role_id, db=db)
                if not new_role_code:
                    raise NotFoundError("Specified role does not exist")
            else:
                new_role_code = (data.get("role") or "worker").strip() or "worker"
                new_role_id = UserRepository.find_role_id_by_code(new_role_code, db=db)
                if not new_role_id:
                    raise NotFoundError("Specified role does not exist")
            group_row = UserRepository.get_role_group_name(new_role_id, db=db)
            if group_row:
                data["group_name"] = group_row[0]
            data["role"] = new_role_code

        new_role_id_for_check = new_role_id
        if not new_role_id_for_check and "role" in data:
            new_role_id_for_check = UserRepository.find_role_id_by_code(data["role"], db=db)
        old_role_id_for_check = UserRepository.find_role_id_by_code(old_role, db=db)
        if new_role_id_for_check is not None and new_role_id_for_check != old_role_id_for_check:
            if current_user_id is None:
                raise ValueError("Only administrators can change roles")
            if current_user_id == uid:
                raise ConflictError("Cannot change your own role")
            if not UserRepository.check_admin_role(current_user_id, db=db):
                raise ValueError("Only administrators can change roles")
        return new_role_id, new_role_code

    @staticmethod
    def apply_role_update(uid, old_role, new_role_id, new_role_code, txn):
        if new_role_id is None:
            return
        if new_role_code != "admin":
            remaining = UserRepository.count_admin_roles_excluding(uid, db=txn)
            if remaining == 0:
                remaining_users = UserRepository.count_admin_users_excluding(uid, db=txn)
                if remaining_users == 0:
                    raise ConflictError("Cannot remove the last administrator")
        old_role_id = UserRepository.find_role_id_by_code(old_role, db=txn) or 2
        UserRepository.delete_user_role_txn(uid, old_role_id, db=txn)
        UserRepository.insert_user_role_txn(uid, new_role_id, db=txn)

    @staticmethod
    def normalize_ids(values, label):
        if not isinstance(values, list):
            raise ValueError(label + " must be a list")
        try:
            normalized = sorted({int(value) for value in values})
        except (TypeError, ValueError):
            raise ValueError(label + " must contain integers") from None
        if any(value <= 0 for value in normalized):
            raise ValueError(label + " must contain positive integers")
        return normalized

    @staticmethod
    def require_role_administrator(actor_id, db):
        if not actor_id or not UserRepository.check_admin_role(actor_id, db=db):
            raise PermissionError("users:admin permission is required")

    @staticmethod
    def prepare_role_change(user_id, role_ids, action, db):
        if action not in {"set", "add", "remove"}:
            raise ValueError("Invalid role action")
        target = UserRepository.find_user_by_id_for_update(user_id, db=db)
        if not target:
            raise NotFoundError("User not found")
        if target["status"] == "deleted":
            raise ConflictError("Cannot change roles for a deleted user")

        requested_rows = UserRepository.find_active_roles_by_ids(role_ids, db=db)
        if len(requested_rows) != len(role_ids):
            valid_ids = {row["id"] for row in requested_rows}
            invalid = [str(role_id) for role_id in role_ids if role_id not in valid_ids]
            raise ValueError("Invalid or inactive role IDs: " + ", ".join(invalid))

        current_rows = UserRepository.get_user_role_rows(user_id, db=db)
        role_codes = {row["id"]: row["code"] for row in current_rows}
        role_codes.update({row["id"]: row["code"] for row in requested_rows})
        current_ids = {row["id"] for row in current_rows}
        requested_ids = set(role_ids)
        if action == "set":
            proposed_ids = requested_ids
        elif action == "add":
            proposed_ids = current_ids | requested_ids
        else:
            proposed_ids = current_ids - requested_ids
        if not proposed_ids:
            raise ConflictError("A user must retain at least one role")

        current_codes = {row["code"] for row in current_rows}
        proposed_codes = {role_codes[role_id] for role_id in proposed_ids}
        if (
            "admin" in current_codes
            and "admin" not in proposed_codes
            and UserRepository.count_admin_roles_excluding(user_id, db=db) == 0
        ):
            raise ConflictError("Cannot remove the last administrator")
        return (
            sorted(current_ids),
            sorted(proposed_ids),
            sorted(current_codes),
            sorted(proposed_codes),
        )

    @staticmethod
    def apply_role_change(
        user_id, requested_ids, proposed_ids, proposed_codes, action, actor_id, db
    ):
        if action == "set":
            UserRepository.replace_user_roles_txn(user_id, proposed_ids, db=db)
        elif action == "add":
            UserRepository.add_user_roles_txn(user_id, requested_ids, db=db)
        else:
            UserRepository.remove_user_roles_txn(user_id, requested_ids, db=db)
        UserRepository.update_user_base_role_txn(
            user_id, "admin" if "admin" in proposed_codes else "worker", db=db
        )
        UserRepository.insert_audit_log_txn(
            actor_id,
            "set_user_roles" if action == "set" else "batch_set_roles",
            "user",
            user_id,
            "action=" + action + "; roles=" + ",".join(proposed_codes),
            db=db,
        )

    @classmethod
    def set_user_roles(cls, user_id, role_ids, actor_id):
        role_ids = cls.normalize_ids(role_ids, "role_ids")
        if not role_ids:
            raise ConflictError("A user must retain at least one role")
        if user_id == actor_id:
            raise ConflictError("Cannot change your own roles")
        with BaseService.transaction() as txn:
            cls.require_role_administrator(actor_id, txn)
            _, proposed_ids, _, proposed_codes = cls.prepare_role_change(
                user_id, role_ids, "set", txn
            )
            cls.apply_role_change(
                user_id, role_ids, proposed_ids, proposed_codes, "set", actor_id, txn
            )
        return {"user_id": user_id, "role_ids": proposed_ids}

    @classmethod
    def batch_set_user_roles(cls, user_ids, role_ids, action, actor_id):
        user_ids = cls.normalize_ids(user_ids, "user_ids")
        role_ids = cls.normalize_ids(role_ids, "role_ids")
        if not user_ids or not role_ids:
            raise ValueError("user_ids and role_ids are required")
        if actor_id in user_ids:
            raise ConflictError("Cannot change your own roles")
        changed = 0
        with BaseService.transaction() as txn:
            cls.require_role_administrator(actor_id, txn)
            for user_id in user_ids:
                _, proposed_ids, _, proposed_codes = cls.prepare_role_change(
                    user_id, role_ids, action, txn
                )
                cls.apply_role_change(
                    user_id, role_ids, proposed_ids, proposed_codes, action, actor_id, txn
                )
                changed += 1
        return changed
