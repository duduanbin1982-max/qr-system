"""qr-system - StatsService"""
from modules.repositories.stats_repository import StatsRepository
from modules.repositories.work_time_repository import WorkTimeRepository


class StatsService:
    @staticmethod
    def _quantity(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _rate(part, total):
        total = StatsService._quantity(total)
        return round(StatsService._quantity(part) / total * 100, 2) if total else 0

    @staticmethod
    def _empty_employee_group(record):
        return {
            "user_id": record.get("user_id"),
            "worker_name": record.get("worker_name") or "-",
            "employee_no": record.get("employee_no") or "",
            "group_name": record.get("group_name") or "",
            "department_name": record.get("department_name") or "",
            "position_name": record.get("position_name") or "",
            "record_count": 0,
            "total_quantity": 0,
            "normal_quantity": 0,
            "scrap_quantity": 0,
            "rework_quantity": 0,
            "order_count": 0,
            "product_count": 0,
            "scrap_rate": 0,
            "rework_rate": 0,
            "records": [],
        }

    @staticmethod
    def _daily_employee_groups(records):
        groups = []
        group_by_user = {}
        order_sets = {}
        product_sets = {}
        for record in records:
            user_id = record.get("user_id") or 0
            if user_id not in group_by_user:
                group = StatsService._empty_employee_group(record)
                group_by_user[user_id] = group
                order_sets[user_id] = set()
                product_sets[user_id] = set()
                groups.append(group)
            group = group_by_user[user_id]
            quantity = StatsService._quantity(record.get("quantity"))
            record_type = record.get("type") or "normal"
            group["record_count"] += 1
            group["total_quantity"] += quantity
            if record_type == "scrap":
                group["scrap_quantity"] += quantity
            elif record_type == "rework":
                group["rework_quantity"] += quantity
            else:
                group["normal_quantity"] += quantity
            if record.get("order_id"):
                order_sets[user_id].add(record.get("order_id"))
            product_key = record.get("product_code") or record.get("product_name") or ""
            if product_key:
                product_sets[user_id].add(product_key)
            group["records"].append(record)

        for group in groups:
            user_id = group["user_id"] or 0
            group["order_count"] = len(order_sets.get(user_id, set()))
            group["product_count"] = len(product_sets.get(user_id, set()))
            group["scrap_rate"] = StatsService._rate(group["scrap_quantity"], group["total_quantity"])
            group["rework_rate"] = StatsService._rate(group["rework_quantity"], group["total_quantity"])
            for key in ("total_quantity", "normal_quantity", "scrap_quantity", "rework_quantity"):
                if float(group[key]).is_integer():
                    group[key] = int(group[key])
        return groups

    @staticmethod
    def _daily_totals(date, product_code, records):
        totals = StatsRepository.get_daily_totals(date, product_code)
        for key in ("record_count", "worker_count", "order_count", "product_count"):
            totals[key] = int(totals.get(key) or 0)
        for key in ("total_quantity", "normal_quantity", "scrap_quantity", "rework_quantity"):
            value = StatsService._quantity(totals.get(key))
            totals[key] = int(value) if value.is_integer() else value
        totals["scrap_rate"] = StatsService._rate(totals.get("scrap_quantity"), totals.get("total_quantity"))
        totals["rework_rate"] = StatsService._rate(totals.get("rework_quantity"), totals.get("total_quantity"))
        totals["loaded_record_count"] = len(records)
        return totals

    @staticmethod
    def get_daily_records(date, product_code="", page_param=1, per_page_param=500):
        page = int(page_param or 1)
        per_page = min(int(per_page_param or 500), 5000)
        offset = (page - 1) * per_page
        records = StatsRepository.get_daily_records(date, product_code, per_page, offset)
        summary = StatsRepository.get_daily_summary(date, product_code)
        total = StatsRepository.get_daily_count(date, product_code)
        totals = StatsService._daily_totals(date, product_code, records)
        work_time_summary = WorkTimeRepository.daily_summary(date, product_code)
        return {
            "records": records,
            "summary": summary,
            "summary_totals": totals,
            "work_time_summary": work_time_summary,
            "employee_groups": StatsService._daily_employee_groups(records),
            "total": total,
            "page": page,
            "per_page": per_page,
            "is_truncated": total > len(records) + offset,
        }

    @staticmethod
    def get_scrap_records(start="", end="", product_code=""):
        records = StatsRepository.get_scrap_records(start, end, product_code)
        summary = StatsRepository.get_scrap_summary(start, end, product_code)
        by_process = StatsRepository.get_scrap_by_process(start, end, product_code)
        return {
            "records": records,
            "summary": summary if summary else {},
            "by_process": by_process,
        }

    @staticmethod
    def get_order_progress(start="", end="", product_code=""):
        return StatsRepository.get_order_progress(start, end, product_code)

    @staticmethod
    def get_worker_stats(sort_by="quantity", sort_dir="desc", start="", end="", product_code=""):
        return StatsRepository.get_worker_stats(sort_by, sort_dir, start, end, product_code)

    @staticmethod
    def get_worker_detail(user_id, start='', end=''):
        return StatsRepository.get_worker_detail(user_id, start, end)

    @staticmethod
    def get_material_detail(material_id, start='', end=''):
        return StatsRepository.get_material_detail(material_id, start, end)
