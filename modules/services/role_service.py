"""
qr-system — 角色组 + 角色管理 Service 层（Repository-refactored）
"""
import json
from modules.services import BaseService
from modules.config import _get_pinyin_initial
from modules.repositories.role_repository import RoleGroupRepository, RoleRepository


class RoleGroupService:

    @staticmethod
    def list_groups():
        rows = RoleGroupRepository.list_all()
        return {"role_groups": [dict(r) for r in rows]}

    @staticmethod
    def create_group(data):
        name = data.get("name", "").strip()
        if not name:
            raise ValueError("角色组名称不能为空")
        if RoleGroupRepository.find_by_name(name):
            raise ValueError("角色组名称【" + name + "】已存在")
        parent_id = data.get("parent_id")
        if parent_id is not None:
            if not RoleGroupRepository.find_by_id(parent_id):
                raise ValueError("父级角色组不存在")
        with BaseService.transaction() as txn:
            permissions = data.get("permissions", [])
            perm_val = json.dumps(permissions, ensure_ascii=False) if isinstance(permissions, list) else data.get("permissions", "")
            cur = RoleGroupRepository.insert_txn(
                name, data.get("description", ""), parent_id,
                data.get("status", "active"), perm_val, db=txn
            )
            return cur

    @staticmethod
    def update_group(gid, data):
        existing = RoleGroupRepository.find_by_id(gid)
        if not existing:
            raise ValueError("角色组不存在")

        if "parent_id" in data:
            pid = data["parent_id"]
            if pid is not None:
                if pid == gid:
                    raise ValueError("不能将自身设为父级")
                if not RoleGroupRepository.find_by_id(pid):
                    raise ValueError("父级角色组不存在")
                cur = pid
                while cur:
                    if cur == gid:
                        raise ValueError("不能建立循环引用")
                    cur = RoleGroupRepository.get_parent_id(cur)

        if "name" in data:
            new_name = data["name"].strip()
            if not new_name:
                raise ValueError("角色组名称不能为空")
            dup = RoleGroupRepository.find_by_name(new_name)
            if dup and dup["id"] != gid:
                raise ValueError("角色组名称【" + new_name + "】已存在")
            data["name"] = new_name

        sets = []
        params = []
        for field in ["name", "description", "parent_id", "status", "permissions"]:
            if field in data:
                sets.append(field + " = ?")
                val = data[field]
                params.append(json.dumps(val, ensure_ascii=False) if isinstance(val, list) else val)
        if not sets:
            raise ValueError("无更新内容")

        sets.append("updated_at = datetime(\"now\",\"localtime\")")
        with BaseService.transaction() as txn:
            RoleGroupRepository.update_txn(", ".join(sets), params, gid, db=txn)

    @staticmethod
    def delete_group(gid):
        child_count = RoleGroupRepository.count_children(gid)
        if child_count > 0:
            raise ValueError("该角色组有下级，无法删除")
        role_count = RoleGroupRepository.count_roles_in_group(gid)
        if role_count > 0:
            raise ValueError("该角色组下有 " + str(role_count) + " 个角色，无法删除")
        with BaseService.transaction() as txn:
            RoleGroupRepository.delete_txn(gid, db=txn)


class RoleService:

    @staticmethod
    def list_roles():
        rows = RoleRepository.list_all()
        return {"roles": [dict(r) for r in rows]}

    @staticmethod
    def create_role(data):
        name = data.get("name", "").strip()
        code = data.get("code", "").strip()
        if not name:
            raise ValueError("角色名称不能为空")
        if not code:
            code = "".join(_get_pinyin_initial(ch) for ch in name if _get_pinyin_initial(ch)).lower()
            if len(code) < 3:
                import time, uuid
                code = "role_" + uuid.uuid4().hex[:6]
        group_id = data.get("group_id")
        if group_id and not RoleRepository.group_exists(group_id):
            raise ValueError("所属角色组不存在")
        parent_id = data.get("parent_id")
        if parent_id and not RoleRepository.role_exists(parent_id):
            raise ValueError("父级角色不存在")
        if RoleRepository.find_by_code(code):
            raise ValueError("角色编码【" + code + "】已存在")
        with BaseService.transaction() as txn:
            cur = RoleRepository.insert_txn(
                name, code, data.get("description", ""), group_id, parent_id,
                data.get("level", 1), data.get("permissions", ""), data.get("status", "active"),
                db=txn
            )
            return cur

    @staticmethod
    def update_role(rid, data):
        role = RoleRepository.find_by_id(rid)
        if not role:
            raise ValueError("角色不存在")
        if "group_id" in data and data["group_id"]:
            if not RoleRepository.group_exists(data["group_id"]):
                raise ValueError("所属角色组不存在")
        if "parent_id" in data and data["parent_id"]:
            if data["parent_id"] == rid:
                raise ValueError("不能将自身设为父级")
            if not RoleRepository.role_exists(data["parent_id"]):
                raise ValueError("父级角色不存在")
            to_check = [data["parent_id"]]
            visited = {rid}
            while to_check:
                cur = to_check.pop()
                if cur in visited:
                    raise ValueError("不能建立循环引用的父子关系")
                visited.add(cur)
                for pr in RoleRepository.get_parent_chain(cur):
                    if pr not in visited:
                        to_check.append(pr)
        if "code" in data:
            new_code = data["code"].strip()
            if not new_code:
                raise ValueError("角色编码不能为空")
            dup = RoleRepository.find_by_code_exclude(new_code, rid)
            if dup:
                raise ValueError("角色编码【" + new_code + "】已存在")
            data["code"] = new_code
        if "name" in data and not data["name"].strip():
            raise ValueError("角色名称不能为空")

        sets = []
        params = []
        for field in ["name", "code", "description", "group_id", "parent_id",
                      "level", "permissions", "status"]:
            if field in data:
                sets.append(field + " = ?")
                val = data[field]
                params.append(json.dumps(val, ensure_ascii=False) if isinstance(val, list) else val)
        if not sets:
            raise ValueError("无更新内容")

        sets.append("updated_at = datetime(\"now\",\"localtime\")")
        with BaseService.transaction() as txn:
            RoleRepository.update_txn(", ".join(sets), params, rid, db=txn)

    @staticmethod
    def delete_role(rid):
        role = RoleRepository.find_by_id(rid)
        if not role:
            raise ValueError("角色不存在")
        if role["is_builtin"]:
            raise ValueError("不能删除内置角色「" + role["name"] + "」")
        user_count = RoleRepository.count_user_roles(rid)
        if user_count > 0:
            raise ValueError("该角色已分配给 " + str(user_count) + " 个用户，请先取消分配后再删除")
        with BaseService.transaction() as txn:
            RoleRepository.delete_txn(rid, db=txn)
