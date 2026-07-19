"""Work time management service."""

from datetime import datetime

from modules.services import BaseService
from modules.repositories.work_time_repository import WorkTimeRepository


STANDARD_STATUSES = {"active", "inactive"}
RECORD_STATUSES = {"running", "completed", "abnormal"}
REVIEW_STATUSES = {"pending", "approved", "rejected"}


class WorkTimeService:
    @staticmethod
    def _to_int(value, default=None):
        if value in (None, ""):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_float(value, default=0.0):
        if value in (None, ""):
            return float(default)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return float(default)
        return number

    @staticmethod
    def _to_datetime(value):
        if not value:
            return None
        text = str(value).strip().replace("T", " ")
        for fmt, length in (
            ("%Y-%m-%d %H:%M:%S", 19),
            ("%Y-%m-%d %H:%M", 16),
            ("%Y-%m-%d", 10),
        ):
            try:
                return datetime.strptime(text[:length], fmt)
            except ValueError:
                continue
        raise ValueError("时间格式不正确")

    @staticmethod
    def _now_text():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _standard_route_groups(items):
        groups = []
        by_route = {}
        for item in items or []:
            route_id = item.get("route_id") or 0
            if route_id not in by_route:
                group = {
                    "route_id": item.get("route_id"),
                    "route_name": item.get("route_name") or "未归属工序路线",
                    "items": [],
                    "process_count": 0,
                    "active_count": 0,
                }
                by_route[route_id] = group
                groups.append(group)
            group = by_route[route_id]
            group["items"].append(item)
            group["process_count"] += 1
            if item.get("status") == "active":
                group["active_count"] += 1
        return groups

    @staticmethod
    def list_standards(filters, page=1, per_page=20):
        result = WorkTimeRepository.list_standards(filters or {}, page, per_page)
        result["route_groups"] = WorkTimeService._standard_route_groups(result.get("items", []))
        return result

    @staticmethod
    def list_standard_routes(filters, page=1, per_page=20):
        return WorkTimeRepository.list_standard_routes(filters or {}, page, per_page)

    @staticmethod
    def normalize_standard(data, user_id, db=None):
        route_id = WorkTimeService._to_int(data.get("route_id"))
        process_id = WorkTimeService._to_int(data.get("process_id"))
        standard_id = WorkTimeService._to_int(data.get("id"))
        if not route_id:
            raise ValueError("请选择工序路线")
        if not process_id:
            raise ValueError("请选择路线中的工序")
        if not WorkTimeRepository.find_route(route_id, db=db):
            raise ValueError("工序路线不存在")
        route_process = WorkTimeRepository.find_route_process(route_id, process_id, db=db)
        if not route_process:
            raise ValueError("所选工序不属于该工序路线")

        standard_minutes = WorkTimeService._to_float(data.get("standard_minutes_per_unit"), 0)
        setup_minutes = WorkTimeService._to_float(data.get("setup_minutes"), 0)
        difficulty_factor = WorkTimeService._to_float(data.get("difficulty_factor"), 1)
        if standard_minutes <= 0:
            raise ValueError("单件标准工时必须大于 0")
        if setup_minutes < 0:
            raise ValueError("准备工时不能小于 0")
        if difficulty_factor <= 0:
            raise ValueError("难度系数必须大于 0")

        status = (data.get("status") or "active").strip()
        if status not in STANDARD_STATUSES:
            raise ValueError("标准工时状态不正确")
        if status == "active" and WorkTimeRepository.find_active_standard_for_route_process(route_id, process_id, exclude_id=standard_id, db=db):
            raise ValueError("该工序路线的这道工序已存在启用标准工时")

        return {
            "product_id": None,
            "product_code": "",
            "product_name": "",
            "route_id": route_id,
            "process_id": process_id,
            "standard_minutes_per_unit": round(standard_minutes, 2),
            "setup_minutes": round(setup_minutes, 2),
            "difficulty_factor": round(difficulty_factor, 3),
            "effective_from": (data.get("effective_from") or datetime.now().strftime("%Y-%m-%d")).strip(),
            "effective_to": (data.get("effective_to") or "").strip(),
            "status": status,
            "version": max(WorkTimeService._to_int(data.get("version"), 1) or 1, 1),
            "remark": (data.get("remark") or "").strip(),
            "created_by": user_id,
            "updated_by": user_id,
        }

    @staticmethod
    def create_standard(data, user_id):
        normalized = WorkTimeService.normalize_standard(data or {}, user_id)
        with BaseService.transaction() as txn:
            return WorkTimeRepository.insert_standard(normalized, txn)

    @staticmethod
    def save_route_standards(route_id, items, user_id, effective_from=""):
        route_id = WorkTimeService._to_int(route_id)
        if not route_id:
            raise ValueError("请选择工序路线")
        route = WorkTimeRepository.find_route(route_id)
        if not route:
            raise ValueError("工序路线不存在")
        route_processes = WorkTimeRepository.list_route_processes(route_id)
        if not route_processes:
            raise ValueError("该工序路线没有配置工序")
        allowed_process_ids = {row["process_id"] for row in route_processes}
        if not isinstance(items, list) or not items:
            raise ValueError("请填写至少一道工序标准工时")

        created = 0
        updated = 0
        deactivated = 0
        seen_process_ids = set()
        with BaseService.transaction() as txn:
            for raw in items:
                raw = raw or {}
                if not isinstance(raw, dict):
                    raise ValueError("标准工时明细格式不正确")
                process_id = WorkTimeService._to_int(raw.get("process_id"))
                if not process_id:
                    raise ValueError("标准工时明细缺少工序")
                if process_id not in allowed_process_ids:
                    raise ValueError("所选工序不属于该工序路线")
                if process_id in seen_process_ids:
                    raise ValueError("同一路线内工序不能重复提交")
                seen_process_ids.add(process_id)

                enabled = raw.get("enabled", True)
                if isinstance(enabled, str):
                    enabled = enabled.lower() not in {"0", "false", "no", "off"}
                status = (raw.get("status") or ("active" if enabled else "inactive")).strip()
                if not enabled:
                    status = "inactive"

                standard_id = WorkTimeService._to_int(raw.get("id"))
                if standard_id:
                    existing = WorkTimeRepository.find_standard(standard_id, db=txn)
                    if not existing:
                        raise ValueError("标准工时不存在")
                    if existing["route_id"] != route_id or existing["process_id"] != process_id:
                        raise ValueError("标准工时与所选路线工序不匹配")
                else:
                    existing_active = WorkTimeRepository.find_active_standard_for_route_process(
                        route_id, process_id, db=txn
                    )
                    standard_id = existing_active["id"] if existing_active else None

                if status == "inactive":
                    if standard_id:
                        WorkTimeRepository.deactivate_standard(standard_id, user_id, txn)
                        deactivated += 1
                    continue

                payload = {
                    **raw,
                    "id": standard_id,
                    "route_id": route_id,
                    "process_id": process_id,
                    "status": "active",
                    "effective_from": raw.get("effective_from") or effective_from or datetime.now().strftime("%Y-%m-%d"),
                }
                normalized = WorkTimeService.normalize_standard(payload, user_id, db=txn)
                if standard_id:
                    WorkTimeRepository.update_standard(standard_id, normalized, txn)
                    updated += 1
                else:
                    WorkTimeRepository.insert_standard(normalized, txn)
                    created += 1

        if not seen_process_ids:
            raise ValueError("请填写至少一道工序标准工时")

        return {
            "route_id": route_id,
            "route_name": route["name"],
            "created": created,
            "updated": updated,
            "deactivated": deactivated,
            "submitted": len(seen_process_ids),
        }

    @staticmethod
    def update_standard(standard_id, data, user_id):
        if not WorkTimeRepository.find_standard(standard_id):
            raise ValueError("标准工时不存在")
        data = {**(data or {}), "id": standard_id}
        normalized = WorkTimeService.normalize_standard(data, user_id)
        with BaseService.transaction() as txn:
            WorkTimeRepository.update_standard(standard_id, normalized, txn)

    @staticmethod
    def deactivate_standard(standard_id, user_id):
        if not WorkTimeRepository.find_standard(standard_id):
            raise ValueError("标准工时不存在")
        with BaseService.transaction() as txn:
            WorkTimeRepository.deactivate_standard(standard_id, user_id, txn)

    @staticmethod
    def list_records(filters, page=1, per_page=20):
        return WorkTimeRepository.list_records(filters or {}, page, per_page)

    @staticmethod
    def _standard_total_minutes(standard, quantity):
        if not standard:
            return 0
        setup = WorkTimeService._to_float(standard["setup_minutes"], 0)
        unit = WorkTimeService._to_float(standard["standard_minutes_per_unit"], 0)
        factor = WorkTimeService._to_float(standard["difficulty_factor"], 1)
        return round(setup + unit * max(int(quantity or 1), 1) * factor, 2)

    @staticmethod
    def normalize_record(data, creator_id):
        process_id = WorkTimeService._to_int(data.get("process_id"))
        user_id = WorkTimeService._to_int(data.get("user_id"))
        if not process_id:
            raise ValueError("请选择工序")
        if not user_id:
            raise ValueError("请选择员工")
        process = WorkTimeRepository.find_process(process_id)
        if not process:
            raise ValueError("工序不存在")
        user = WorkTimeRepository.find_user(user_id)
        if not user:
            raise ValueError("员工不存在")

        order_id = WorkTimeService._to_int(data.get("order_id"))
        order_no = (data.get("order_no") or "").strip()
        product_code = (data.get("product_code") or "").strip()
        product_name = (data.get("product_name") or "").strip()
        route_id = WorkTimeService._to_int(data.get("route_id"))
        route_name = (data.get("route_name") or "").strip()
        if order_id:
            order = WorkTimeRepository.find_order(order_id)
            if not order:
                raise ValueError("订单不存在")
            order_no = order["order_no"] or order_no
            product_code = order["product_code"] or product_code
            product_name = order["product_name"] or product_name
            route_id = order["route_id"] or route_id
            route_name = order["route_name"] or route_name
            if not WorkTimeRepository.find_order_process(order_id, process_id):
                raise ValueError("所选工序不属于该订单的工序路线")
        if route_id:
            route = WorkTimeRepository.find_route(route_id)
            if not route:
                raise ValueError("工序路线不存在")
            route_name = route["name"] or route_name
            if not WorkTimeRepository.find_route_process(route_id, process_id):
                raise ValueError("所选工序不属于该工序路线")

        quantity = max(WorkTimeService._to_int(data.get("quantity"), 1) or 1, 1)
        start_time = (data.get("start_time") or WorkTimeService._now_text()).strip().replace("T", " ")
        end_time = (data.get("end_time") or "").strip().replace("T", " ")
        status = (data.get("status") or ("completed" if end_time else "running")).strip()
        if status not in RECORD_STATUSES:
            raise ValueError("工时流水状态不正确")
        if status == "completed" and not end_time:
            end_time = WorkTimeService._now_text()

        start_dt = WorkTimeService._to_datetime(start_time)
        end_dt = WorkTimeService._to_datetime(end_time) if end_time else None
        pause_minutes = max(WorkTimeService._to_float(data.get("pause_minutes"), 0), 0)
        actual_minutes = WorkTimeService._to_float(data.get("actual_minutes"), 0)
        if start_dt and end_dt:
            if end_dt < start_dt:
                raise ValueError("结束时间不能早于开始时间")
            actual_minutes = round(max((end_dt - start_dt).total_seconds() / 60 - pause_minutes, 0), 2)
        effective_minutes = WorkTimeService._to_float(data.get("effective_minutes"), actual_minutes)
        effective_minutes = round(max(effective_minutes, 0), 2)

        standard_id = WorkTimeService._to_int(data.get("standard_id"))
        standard = WorkTimeRepository.find_standard(standard_id) if standard_id else None
        if standard_id and not standard:
            raise ValueError("标准工时不存在")
        if not standard:
            standard = WorkTimeRepository.find_best_standard(
                route_id=route_id,
                product_code=product_code,
                process_id=process_id,
            )
            standard_id = standard["id"] if standard else None
        standard_missing = 0 if standard else 1
        standard_minutes = WorkTimeService._to_float(data.get("standard_minutes"), 0)
        if standard_minutes <= 0:
            standard_minutes = WorkTimeService._standard_total_minutes(standard, quantity)

        abnormal_reason = (data.get("abnormal_reason") or "").strip()
        review_status = (data.get("review_status") or "").strip()
        if not review_status:
            review_status = "pending" if status in {"running", "abnormal"} or abnormal_reason else "approved"
        if review_status not in REVIEW_STATUSES:
            raise ValueError("审核状态不正确")
        if abnormal_reason and status == "completed":
            status = "abnormal"
            review_status = "pending"

        return {
            "order_id": order_id,
            "order_no": order_no,
            "serial_no": (data.get("serial_no") or "").strip(),
            "route_id": route_id,
            "route_name": route_name,
            "product_code": product_code,
            "product_name": product_name,
            "standard_missing": standard_missing,
            "process_id": process_id,
            "process_name": process["name"],
            "user_id": user_id,
            "user_name": user["name"],
            "standard_id": standard_id,
            "source_work_record_id": WorkTimeService._to_int(data.get("source_work_record_id")),
            "quantity": quantity,
            "standard_minutes": round(standard_minutes, 2),
            "start_time": start_time,
            "end_time": end_time,
            "pause_minutes": round(pause_minutes, 2),
            "actual_minutes": actual_minutes,
            "effective_minutes": effective_minutes,
            "status": status,
            "abnormal_reason": abnormal_reason,
            "review_status": review_status,
            "reviewed_by": creator_id if review_status == "approved" else None,
            "reviewed_at": WorkTimeService._now_text() if review_status == "approved" else "",
            "review_note": (data.get("review_note") or "").strip(),
            "created_by": creator_id,
        }

    @staticmethod
    def create_record(data, creator_id):
        normalized = WorkTimeService.normalize_record(data or {}, creator_id)
        with BaseService.transaction() as txn:
            return WorkTimeRepository.insert_record(normalized, txn)

    @staticmethod
    def review_record(record_id, data, reviewer_id):
        record = WorkTimeRepository.find_record(record_id)
        if not record:
            raise ValueError("工时流水不存在")
        review_status = (data.get("review_status") or "approved").strip()
        if review_status not in REVIEW_STATUSES:
            raise ValueError("审核状态不正确")
        effective_minutes = WorkTimeService._to_float(
            data.get("effective_minutes"),
            record["effective_minutes"] if record["effective_minutes"] is not None else record["actual_minutes"],
        )
        if effective_minutes < 0:
            raise ValueError("有效工时不能小于 0")
        if review_status == "approved":
            status = "completed"
        elif review_status == "rejected":
            status = "abnormal"
        else:
            status = record["status"] or "abnormal"
        review_note = (data.get("review_note") or "").strip()
        abnormal_reason = (data.get("abnormal_reason") or record["abnormal_reason"] or "").strip()
        with BaseService.transaction() as txn:
            WorkTimeRepository.review_record(
                record_id,
                {
                    "effective_minutes": round(effective_minutes, 2),
                    "status": status,
                    "review_status": review_status,
                    "abnormal_reason": abnormal_reason,
                    "reviewed_by": reviewer_id,
                    "review_note": review_note,
                },
                txn,
            )
            WorkTimeRepository.insert_review_log(
                record_id,
                record["effective_minutes"] or 0,
                round(effective_minutes, 2),
                record["review_status"] or "",
                review_status,
                review_note or abnormal_reason,
                reviewer_id,
                txn,
            )

    @staticmethod
    def stats():
        return WorkTimeRepository.stats()
