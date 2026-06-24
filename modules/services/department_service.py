"""Department service."""
from modules.db_unit_of_work import BaseService
from modules.repositories.department_repository import DepartmentRepository


class DepartmentService:
    @staticmethod
    def list_departments():
        rows = DepartmentRepository.list_active()
        deps = [dict(row) for row in rows]
        dep_map = {dep["id"]: dep for dep in deps}
        tree = []
        for dep in deps:
            dep.setdefault("children", [])
        for dep in deps:
            parent_id = dep.get("parent_id")
            if parent_id and parent_id in dep_map:
                dep_map[parent_id].setdefault("children", []).append(dep)
            else:
                tree.append(dep)
        return {"departments": tree, "flat": deps}

    @staticmethod
    def create_department(data):
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("Department name required")
        if DepartmentRepository.find_by_name(name):
            raise ValueError("Department name already exists")
        with BaseService.transaction() as txn:
            DepartmentRepository.insert_txn(
                name,
                data.get("description", ""),
                data.get("parent_id"),
                data.get("sort_order", 0),
                db=txn,
            )
        return name

    @staticmethod
    def update_department(dep_id, data):
        if not DepartmentRepository.find_by_id(dep_id):
            raise LookupError("Not found")
        fields = {k: data[k] for k in ["name", "description", "parent_id", "sort_order", "status"] if k in data}
        if not fields:
            raise ValueError("No fields")
        with BaseService.transaction() as txn:
            DepartmentRepository.update_txn(dep_id, fields, db=txn)
        return True

    @staticmethod
    def delete_department(dep_id):
        if not DepartmentRepository.find_active_by_id(dep_id):
            raise LookupError("Not found")
        with BaseService.transaction() as txn:
            DepartmentRepository.soft_delete_txn(dep_id, db=txn)
        return True
