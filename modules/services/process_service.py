"""qr-system - ProcessService (Repository-refactored)"""
import re
import sqlite3
from modules.services import BaseService
from modules.repositories.process_repository import ProcessRepository


class ProcessService:
    RELATED_TABLES = [
        "work_records", "scrap_records", "rework_records",
        "quality_inspections", "process_route_items",
        "order_processes", "position_processes", "material_consumptions"
    ]

    @staticmethod
    def _validate_table_name(table_name):
        if table_name not in ProcessService.RELATED_TABLES:
            raise ValueError("Invalid table name: " + table_name)
        return table_name

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
            raise ValueError("Process '" + name + "' already exists")

        seq_order = data.get("seq_order")
        if seq_order is not None:
            try:
                seq_order = int(seq_order)
            except (ValueError, TypeError):
                seq_order = None

        category = data.get("category", "structural")
        if seq_order is None:
            seq_order = ProcessRepository.get_max_seq(category) + 1

        try:
            with BaseService.transaction() as txn:
                return ProcessRepository.insert_txn(
                    name, data.get("description", ""), category,
                    seq_order, data.get("status", "active"), db=txn
                )
        except sqlite3.IntegrityError:
            raise ValueError("Process '" + name + "' already exists")

    @staticmethod
    def update_process(pid, data):
        existing = ProcessRepository.find_by_id(pid)
        if not existing:
            raise ValueError("Process not found")

        if "name" in data:
            name = (data.get("name") or "").strip()
            if not name:
                raise ValueError("Process name required")
            if re.search(r"[';<>]", name):
                raise ValueError("Process name contains invalid characters")
            data["name"] = name

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
                raise ValueError("Process name '" + data["name"] + "' already exists")

        sets.append('updated_at = datetime("now","localtime")')

        try:
            with BaseService.transaction() as txn:
                ProcessRepository.update_txn(", ".join(sets), params, pid, db=txn)
        except sqlite3.IntegrityError:
            raise ValueError("Process name already exists")

    @staticmethod
    def check_impact(pid):
        existing = ProcessRepository.find_by_id(pid)
        if not existing:
            raise ValueError("Process not found")
        impact = ProcessRepository.check_impact(pid, ProcessService.RELATED_TABLES)
        return {"process_id": pid, "name": existing["name"], "impact": impact}

    @staticmethod
    def delete_process(pid):
        existing = ProcessRepository.find_by_id(pid)
        if not existing:
            raise ValueError("Not found")

        impact = ProcessRepository.check_impact(pid, ProcessService.RELATED_TABLES)
        if impact:
            critical_tables = ["work_records", "order_processes", "process_route_items", "quality_inspections"]
            blockers = {k: v for k, v in impact.items() if k in critical_tables}
            if blockers:
                details = ", ".join(k + ": " + str(v) for k, v in blockers.items())
                raise ValueError("Process has related data: " + details)
            raise ValueError("Process has " + str(sum(impact.values())) + " related records, cannot delete")

        with BaseService.transaction() as txn:
            ProcessRepository.delete_txn(pid, db=txn)
        return {"name": existing["name"], "impact": {}}
