"""qr-system - ProcessService (Repository-refactored)"""
from modules.domain.errors import ConflictError, NotFoundError
import re
from modules.services import BaseService
from modules.repositories.process_repository import ProcessRepository


class ProcessService:
    VALID_CATEGORIES = ("结构件", "机加工")
    VALID_STATUSES = ("active", "inactive")

    @staticmethod
    def _validate_category(category):
        if category not in ProcessService.VALID_CATEGORIES:
            raise ValueError("工序分类只能是结构件或机加工")
        return category

    @staticmethod
    def _validate_status(status):
        if status not in ProcessService.VALID_STATUSES:
            raise ValueError("工序状态只能是 active 或 inactive")
        return status

    @staticmethod
    def list_processes(category="", search="", sort_by="seq_order", sort_dir="asc", limit=500, offset=0):
        allowed_sort = {"seq_order", "name", "category", "status", "created_at"}
        if sort_by not in allowed_sort:
            sort_by = "seq_order"
        if sort_dir.lower() not in ("asc", "desc"):
            raise ValueError("Invalid sort_dir")
        sort_dir = sort_dir.upper()
        limit = max(1, min(int(limit), 200)) if limit else None

        params = []
        conditions = []
        if category:
            conditions.append("category = ?")
            params.append(category)
        if search:
            conditions.append('name LIKE ? ESCAPE "\\"')
            safe_search = search.replace("%", "\\%").replace("_", "\\_")
            params.append("%" + safe_search + "%")

        category_counts = ProcessRepository.get_category_counts()
        total = ProcessRepository.count_all(conditions, params)
        rows = ProcessRepository.list_all(conditions, params, sort_by, sort_dir, limit, offset)
        return {"processes": [dict(r) for r in rows], "total": total, "category_counts": category_counts}

    @staticmethod
    def create_process(data):
        name = data.get("name", "").strip()
        if not name:
            raise ValueError("Process name required")
        if re.search(r"[';<>]", name):
            raise ValueError("Process name contains invalid characters")

        existing = ProcessRepository.find_by_name(name)
        if existing:
            raise ConflictError("Process '" + name + "' already exists")

        seq_order = data.get("seq_order")
        if seq_order is not None:
            try:
                seq_order = int(seq_order)
            except (ValueError, TypeError):
                seq_order = None

        category = ProcessService._validate_category(data.get("category", "结构件"))
        status = ProcessService._validate_status(data.get("status", "active"))
        if seq_order is None:
            seq_order = ProcessRepository.get_max_seq(category) + 1

        with BaseService.transaction() as txn:
            return ProcessRepository.insert_txn(
                name, data.get("description", ""), category,
                seq_order, status, db=txn
            )

    @staticmethod
    def update_process(pid, data):
        existing = ProcessRepository.find_by_id(pid)
        if not existing:
            raise NotFoundError("Process not found")

        if "name" in data:
            name = (data.get("name") or "").strip()
            if not name:
                raise ValueError("Process name required")
            if re.search(r"[';<>]", name):
                raise ValueError("Process name contains invalid characters")
            data["name"] = name

        if "category" in data:
            ProcessService._validate_category(data["category"])
            if ProcessRepository.count_route_category_conflicts(pid, data["category"]):
                raise ConflictError("工序已被其他分类的工艺路线引用，不能修改分类")
        if "status" in data:
            ProcessService._validate_status(data["status"])

        field_map = {
            "name": "name", "description": "description",
            "category": "category", "seq_order": "seq_order", "status": "status"
        }
        sets = []
        params = []
        for field in ["name", "description", "category", "seq_order", "status"]:
            if field in data:
                sets.append(field_map[field] + " = ?")
                params.append(data[field])
        if not sets:
            raise ValueError("No update fields")

        if "name" in data:
            dup = ProcessRepository.find_duplicate_name(data["name"], pid)
            if dup:
                raise ConflictError("Process name '" + data["name"] + "' already exists")

        sets.append('updated_at = datetime("now","localtime")')

        with BaseService.transaction() as txn:
            ProcessRepository.update_txn(", ".join(sets), params, pid, db=txn)

    @staticmethod
    def check_impact(pid):
        existing = ProcessRepository.find_by_id(pid)
        if not existing:
            raise NotFoundError("Process not found")
        impact = ProcessRepository.check_impact(pid)
        return {"process_id": pid, "name": existing["name"], "impact": impact}

    @staticmethod
    def delete_process(pid):
        existing = ProcessRepository.find_by_id(pid)
        if not existing:
            raise NotFoundError("Not found")

        impact = ProcessRepository.check_impact(pid)
        if impact:
            details = ", ".join(k + ": " + str(v) for k, v in impact.items())
            raise ConflictError("工序已有关联数据，只能停用，不能删除：" + details)

        with BaseService.transaction() as txn:
            deleted = ProcessRepository.delete_txn(pid, db=txn)
            if not deleted:
                raise ConflictError("工序已被业务数据引用，请改为停用")
        return {"name": existing["name"], "impact": {}}
