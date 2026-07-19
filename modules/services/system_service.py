"""qr-system — SystemService (DB maintenance)"""
from modules.services import BaseService
from modules.repositories.system_repository import SystemRepository


class SystemService:
    @staticmethod
    def check_orphans():
        """Check for orphaned records across all related tables."""
        results = []
        all_clean = True
        for item in SystemRepository.orphan_counts():
            if "detail" in item:
                results.append({**item, "pass": False})
                all_clean = False
                continue
            ok = item["orphans"] == 0
            results.append({**item, "pass": ok})
            if not ok:
                all_clean = False
        return {"all_clean": all_clean, "checks": results}


    @staticmethod
    def ping():
        """数据库连通性检查"""
        return SystemRepository.ping()

    @staticmethod
    def get_db_stats():
        db = BaseService.db()
        tables = []
        for row in SystemRepository.get_tables(db=db):
            cnt = SystemRepository.count_table(row["name"], db=db)
            tables.append({"name": row["name"], "count": cnt})
        return tables

    @staticmethod
    def vacuum():
        SystemRepository.vacuum()

    @staticmethod
    def check_integrity():
        ok = SystemRepository.check_integrity()
        return list(ok) if ok else ["unknown"]
