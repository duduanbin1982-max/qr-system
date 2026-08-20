"""Role and role-group services with administrator-owned invariants."""
import json
import re

from modules.config import _get_pinyin_initial
from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.repositories.audit_log_repository import AuditLogRepository
from modules.repositories.role_repository import RoleGroupRepository, RoleRepository
from modules.services import BaseService
from modules.services.administrator_policy import AdministratorPolicy


def _audit_detail(before, after):
    return json.dumps(
        {"before": before, "after": after},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class RoleGroupService:

    @staticmethod
    def list_groups():
        rows = RoleGroupRepository.list_all()
        return {"role_groups": [dict(row) for row in rows]}

    @staticmethod
    def create_group(data, actor_id):
        name = data.get("name", "").strip()
        if not name:
            raise ValueError("角色组名称不能为空")
        with BaseService.transaction() as txn:
            AdministratorPolicy.require_actual_admin(actor_id, txn)
            if RoleGroupRepository.find_by_name(name, db=txn):
                raise ConflictError("角色组名称【" + name + "】已存在")
            parent_id = data.get("parent_id")
            if parent_id is not None and not RoleGroupRepository.find_by_id(parent_id, db=txn):
                raise NotFoundError("父级角色组不存在")
            permissions = AdministratorPolicy.normalize_group_permissions(
                data.get("permissions", [])
            )
            status = AdministratorPolicy.normalize_status(
                data.get("status", "active")
            )
            group_id = RoleGroupRepository.insert_txn(
                name,
                data.get("description", ""),
                parent_id,
                status,
                json.dumps(permissions, ensure_ascii=False),
                db=txn,
            )
            after = dict(RoleGroupRepository.find_by_id(group_id, db=txn))
            AuditLogRepository.insert_log(
                actor_id,
                "create_role_group",
                "role_group",
                group_id,
                _audit_detail(None, after),
                db=txn,
            )
            return group_id

    @staticmethod
    def update_group(group_id, data, actor_id):
        with BaseService.transaction() as txn:
            AdministratorPolicy.require_actual_admin(actor_id, txn)
            existing = RoleGroupRepository.find_by_id(group_id, db=txn)
            if not existing:
                raise NotFoundError("角色组不存在")
            before = dict(existing)

            if "parent_id" in data:
                parent_id = data["parent_id"]
                if parent_id is not None:
                    if parent_id == group_id:
                        raise ConflictError("不能将自身设为父级")
                    if not RoleGroupRepository.find_by_id(parent_id, db=txn):
                        raise NotFoundError("父级角色组不存在")
                    current = parent_id
                    while current:
                        if current == group_id:
                            raise ConflictError("不能建立循环引用")
                        current = RoleGroupRepository.get_parent_id(current, db=txn)

            if "name" in data:
                name = data["name"].strip()
                if not name:
                    raise ValueError("角色组名称不能为空")
                duplicate = RoleGroupRepository.find_by_name(name, db=txn)
                if duplicate and duplicate["id"] != group_id:
                    raise ConflictError("角色组名称【" + name + "】已存在")
                data["name"] = name

            if "permissions" in data:
                AdministratorPolicy.normalize_group_permissions(data["permissions"])
                data.pop("permissions")
            if "status" in data:
                data["status"] = AdministratorPolicy.normalize_status(data["status"])

            sets = []
            params = []
            for field in ["name", "description", "parent_id", "status"]:
                if field in data:
                    sets.append(field + " = ?")
                    value = data[field]
                    params.append(
                        json.dumps(value, ensure_ascii=False)
                        if isinstance(value, list)
                        else value
                    )
            if not sets:
                raise ValueError("无更新内容")
            sets.append('updated_at = datetime("now","localtime")')
            RoleGroupRepository.update_txn(", ".join(sets), params, group_id, db=txn)
            after = dict(RoleGroupRepository.find_by_id(group_id, db=txn))
            AuditLogRepository.insert_log(
                actor_id,
                "update_role_group",
                "role_group",
                group_id,
                _audit_detail(before, after),
                db=txn,
            )

    @staticmethod
    def delete_group(group_id, actor_id):
        with BaseService.transaction() as txn:
            AdministratorPolicy.require_actual_admin(actor_id, txn)
            existing = RoleGroupRepository.find_by_id(group_id, db=txn)
            if not existing:
                raise NotFoundError("角色组不存在")
            if RoleGroupRepository.count_children(group_id, db=txn) > 0:
                raise ConflictError("该角色组有下级，无法删除")
            role_count = RoleGroupRepository.count_roles_in_group(group_id, db=txn)
            if role_count > 0:
                raise ConflictError("该角色组下有 " + str(role_count) + " 个角色，无法删除")
            before = dict(existing)
            RoleGroupRepository.delete_txn(group_id, db=txn)
            AuditLogRepository.insert_log(
                actor_id,
                "delete_role_group",
                "role_group",
                group_id,
                _audit_detail(before, None),
                db=txn,
            )


class RoleService:

    ROLE_CODE_RE = re.compile(r"^[a-z0-9_]{2,64}$")

    @classmethod
    def _normalize_code(cls, value):
        code = str(value or "").strip()
        if not code:
            raise ValidationError("角色编码不能为空")
        if not cls.ROLE_CODE_RE.fullmatch(code):
            raise ValidationError("角色编码必须为 2-64 位小写字母、数字或下划线")
        return code

    @staticmethod
    def _normalize_level(value):
        try:
            level = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("角色级别必须为正整数") from exc
        if level < 1 or str(value).strip() not in {str(level), str(float(level))}:
            raise ValidationError("角色级别必须为正整数")
        return level

    @staticmethod
    def list_roles():
        rows = RoleRepository.list_all()
        return {"roles": [dict(row) for row in rows]}

    @staticmethod
    def create_role(data, actor_id):
        name = data.get("name", "").strip()
        code = str(data.get("code", "") or "").strip()
        if not name:
            raise ValueError("角色名称不能为空")
        if not code:
            code = "".join(
                _get_pinyin_initial(char)
                for char in name
                if _get_pinyin_initial(char)
            ).lower()
            if len(code) < 3:
                import time
                code = "role_" + hex(int(time.time() * 1000))[2:]
        code = RoleService._normalize_code(code)

        with BaseService.transaction() as txn:
            AdministratorPolicy.require_actual_admin(actor_id, txn)
            group_id = data.get("group_id")
            if group_id and not RoleRepository.group_exists(group_id, db=txn):
                raise NotFoundError("所属角色组不存在")
            parent_id = data.get("parent_id")
            if parent_id and not RoleRepository.role_exists(parent_id, db=txn):
                raise NotFoundError("父级角色不存在")
            if RoleRepository.find_by_code_or_alias(code, db=txn):
                raise ConflictError("角色编码【" + code + "】已存在")
            if RoleRepository.find_by_name(name, db=txn):
                raise ConflictError("角色名称【" + name + "】已存在")
            permissions = AdministratorPolicy.normalize_permissions(
                data.get("permissions", [])
            )
            status = AdministratorPolicy.normalize_status(
                data.get("status", "active")
            )
            level = RoleService._normalize_level(data.get("level", 1))
            role_id = RoleRepository.insert_txn(
                name,
                code,
                data.get("description", ""),
                group_id,
                parent_id,
                level,
                json.dumps(permissions, ensure_ascii=False),
                status,
                db=txn,
            )
            RoleRepository.insert_code_alias_txn(
                role_id,
                code,
                "role created",
                actor_id,
                db=txn,
            )
            after = dict(RoleRepository.find_by_id(role_id, db=txn))
            AuditLogRepository.insert_log(
                actor_id,
                "create_role",
                "role",
                role_id,
                _audit_detail(None, after),
                db=txn,
            )
            return role_id

    @staticmethod
    def _protect_builtin_fields(role, data):
        if not role["is_builtin"]:
            return
        protected = {"code", "status"}
        if role["code"] == "admin":
            protected.update({"permissions", "group_id", "parent_id", "level"})
        for field in protected:
            if field not in data:
                continue
            if field == "permissions":
                current = AdministratorPolicy.normalize_permissions(
                    role["permissions"], allow_wildcard=True
                )
                proposed = AdministratorPolicy.normalize_permissions(
                    data[field], allow_wildcard=True
                )
            else:
                current = role[field]
                proposed = data[field]
            if proposed != current:
                raise ConflictError("内置角色的安全字段不可修改：" + field)

    @staticmethod
    def update_role(role_id, data, actor_id):
        with BaseService.transaction() as txn:
            AdministratorPolicy.require_actual_admin(actor_id, txn)
            role = RoleRepository.find_by_id(role_id, db=txn)
            if not role:
                raise NotFoundError("角色不存在")
            before = dict(role)
            RoleService._protect_builtin_fields(role, data)

            if "group_id" in data and data["group_id"]:
                if not RoleRepository.group_exists(data["group_id"], db=txn):
                    raise NotFoundError("所属角色组不存在")
            if "parent_id" in data and data["parent_id"]:
                if data["parent_id"] == role_id:
                    raise ConflictError("不能将自身设为父级")
                if not RoleRepository.role_exists(data["parent_id"], db=txn):
                    raise NotFoundError("父级角色不存在")
                to_check = [data["parent_id"]]
                visited = {role_id}
                while to_check:
                    current = to_check.pop()
                    if current in visited:
                        raise ConflictError("不能建立循环引用的父子关系")
                    visited.add(current)
                    for parent in RoleRepository.get_parent_chain(current, db=txn):
                        if parent not in visited:
                            to_check.append(parent)
            if "code" in data:
                code = RoleService._normalize_code(data["code"])
                duplicate = RoleRepository.find_by_code_or_alias(code, db=txn)
                if duplicate and duplicate["id"] == role_id and duplicate["code"] == code:
                    duplicate = None
                if duplicate:
                    raise ConflictError("角色编码【" + code + "】已存在")
                data["code"] = code
            if "name" in data:
                data["name"] = data["name"].strip()
                if not data["name"]:
                    raise ValueError("角色名称不能为空")
            if "permissions" in data:
                data["permissions"] = AdministratorPolicy.normalize_permissions(
                    data["permissions"],
                    allow_wildcard=bool(role["is_builtin"] and role["code"] == "admin"),
                )
            if "status" in data:
                data["status"] = AdministratorPolicy.normalize_status(data["status"])
            if "level" in data:
                data["level"] = RoleService._normalize_level(data["level"])

            old_code = role["code"]
            if "code" in data and data["code"] != old_code:
                refs = RoleRepository.count_references(role_id, old_code, db=txn)
                if refs["total"]:
                    raise ConflictError(
                        "角色编码已被用户或审批配置引用，不能直接修改；请新建角色并迁移授权"
                    )
                RoleRepository.close_code_alias_txn(role_id, old_code, db=txn)
                RoleRepository.insert_code_alias_txn(
                    role_id,
                    data["code"],
                    "role code changed",
                    actor_id,
                    db=txn,
                )

            sets = []
            params = []
            for field in [
                "name", "code", "description", "group_id", "parent_id",
                "level", "permissions", "status",
            ]:
                if field in data:
                    sets.append(field + " = ?")
                    value = data[field]
                    params.append(
                        json.dumps(value, ensure_ascii=False)
                        if isinstance(value, list)
                        else value
                    )
            if not sets:
                raise ValueError("无更新内容")
            sets.append('updated_at = datetime("now","localtime")')
            RoleRepository.update_txn(", ".join(sets), params, role_id, db=txn)
            after = dict(RoleRepository.find_by_id(role_id, db=txn))
            AuditLogRepository.insert_log(
                actor_id,
                "update_role",
                "role",
                role_id,
                _audit_detail(before, after),
                db=txn,
            )

    @staticmethod
    def delete_role(role_id, actor_id):
        with BaseService.transaction() as txn:
            AdministratorPolicy.require_actual_admin(actor_id, txn)
            role = RoleRepository.find_by_id(role_id, db=txn)
            if not role:
                raise NotFoundError("角色不存在")
            if role["is_builtin"]:
                raise ConflictError("不能删除内置角色「" + role["name"] + "」")
            user_count = RoleRepository.count_user_roles(role_id, db=txn)
            if user_count > 0:
                raise ConflictError(
                    "该角色已分配给 " + str(user_count) + " 个用户，请先取消分配后再删除"
                )
            before = dict(role)
            RoleRepository.delete_txn(role_id, db=txn)
            AuditLogRepository.insert_log(
                actor_id,
                "delete_role",
                "role",
                role_id,
                _audit_detail(before, None),
                db=txn,
            )
