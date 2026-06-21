"""qr-system - SystemService (Repository-refactored)"""
from modules.services import BaseService
from modules.repositories.system_repository import SystemRepository


class SystemService:
    @staticmethod
    def ping():
        db = BaseService.db()
        db.execute("SELECT 1")
        return True

    @staticmethod
    def get_db_stats():
        tables = []
        for row in SystemRepository.get_tables():
            cnt = SystemRepository.count_table(row["name"])
            tables.append({"name": row["name"], "count": cnt})
        return tables

    @staticmethod
    def vacuum():
        SystemRepository.vacuum()

    @staticmethod
    def check_integrity():
        ok = SystemRepository.check_integrity()
        return list(ok) if ok else ["unknown"]
