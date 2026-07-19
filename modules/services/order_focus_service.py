"""Order completion focus board, exceptions, and scan control policy."""

from modules.repositories.order_repository import OrderRepository
from modules.repositories.setting_repository import SettingRepository
from modules.services import BaseService
from modules.services.access_policy_service import has_permission
from modules.services.order_progress_analyzer import OrderProgressAnalyzer
from modules.order_focus_config import (
    COMPLETION_FOCUS_BYPASS_PERMISSIONS,
    COMPLETION_FOCUS_ENABLED_KEY,
    COMPLETION_FOCUS_EXCEPTION_REASONS,
    COMPLETION_FOCUS_MODE_KEY,
    COMPLETION_FOCUS_MODE_OPTIONS,
    COMPLETION_FOCUS_MODES,
    COMPLETION_FOCUS_TAIL_PCT_KEY,
    DEFAULT_COMPLETION_FOCUS_MODE,
    DEFAULT_COMPLETION_FOCUS_TAIL_PERCENT,
    EVENT_EXCEPTION_CANCELLED,
    EVENT_EXCEPTION_CREATED,
    EVENT_SCAN_BLOCKED,
    EVENT_SCAN_BYPASSED,
    FOCUS_MODE_HARD,
    FOCUS_MODE_OFF,
    FOCUS_MODE_SOFT,
)
from modules.setting_reader import clear_settings_cache, get_setting


class OrderFocusService:
    """Keeps earlier-started orders concentrated until full completion."""

    MODE_OFF = FOCUS_MODE_OFF
    MODE_SOFT = FOCUS_MODE_SOFT
    MODE_HARD = FOCUS_MODE_HARD
    MODES = COMPLETION_FOCUS_MODES
    EXCEPTION_REASONS = COMPLETION_FOCUS_EXCEPTION_REASONS


    @staticmethod
    def _setting_bool(key, default=True):
        value = str(get_setting(key, "1" if default else "0") or "").strip().lower()
        return value not in ("0", "false", "off", "no", "否", "关闭")

    @staticmethod
    def _setting_float(key, default):
        try:
            return float(get_setting(key, str(default)) or default)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def tail_percent():
        return min(max(OrderFocusService._setting_float(COMPLETION_FOCUS_TAIL_PCT_KEY, DEFAULT_COMPLETION_FOCUS_TAIL_PERCENT), 1), 99)

    @staticmethod
    def mode():
        mode = str(get_setting(COMPLETION_FOCUS_MODE_KEY, DEFAULT_COMPLETION_FOCUS_MODE) or DEFAULT_COMPLETION_FOCUS_MODE).strip().lower()
        if mode in OrderFocusService.MODES:
            return mode
        if not OrderFocusService._setting_bool(COMPLETION_FOCUS_ENABLED_KEY, True):
            return OrderFocusService.MODE_OFF
        return OrderFocusService.MODE_SOFT

    @staticmethod
    def config():
        return {
            "mode": OrderFocusService.mode(),
            "tail_percent": OrderFocusService.tail_percent(),
            "reason_options": OrderFocusService.EXCEPTION_REASONS,
            "mode_options": COMPLETION_FOCUS_MODE_OPTIONS,
            "bypass_permissions": COMPLETION_FOCUS_BYPASS_PERMISSIONS,
            "default_mode": DEFAULT_COMPLETION_FOCUS_MODE,
            "default_tail_percent": DEFAULT_COMPLETION_FOCUS_TAIL_PERCENT,
        }

    @staticmethod
    def save_config(data):
        mode = str(data.get("mode", OrderFocusService.mode()) or "").strip().lower()
        if mode not in OrderFocusService.MODES:
            raise ValueError("管控模式必须是 off、soft 或 hard")
        try:
            tail_percent = int(data.get("tail_percent", OrderFocusService.tail_percent()))
        except (TypeError, ValueError):
            raise ValueError("尾数阈值必须是 1-99 的整数")
        if tail_percent < 1 or tail_percent > 99:
            raise ValueError("尾数阈值必须是 1-99 的整数")

        with BaseService.transaction() as txn:
            SettingRepository.upsert_txn(COMPLETION_FOCUS_MODE_KEY, mode, db=txn)
            SettingRepository.upsert_txn(COMPLETION_FOCUS_TAIL_PCT_KEY, str(tail_percent), db=txn)
        clear_settings_cache()
        return OrderFocusService.config()

    @staticmethod
    def enabled():
        return OrderFocusService.mode() != OrderFocusService.MODE_OFF

    @staticmethod
    def scan_hint_enabled():
        return OrderFocusService.enabled()

    @staticmethod
    def hard_block_enabled():
        return OrderFocusService.mode() == OrderFocusService.MODE_HARD

    @staticmethod
    def can_bypass(user):
        if not user:
            return False
        if user.get("role") == "admin":
            return True
        return any(has_permission(user, perm) for perm in COMPLETION_FOCUS_BYPASS_PERMISSIONS)

    @staticmethod
    def _record_event(event_type, order_id=None, process_id=None, warning=None, user=None, reason="", detail="", db=None):
        warning = warning or {}
        user = user or {}
        try:
            return OrderRepository.insert_completion_focus_event(
                event_type,
                order_id=order_id,
                process_id=process_id or warning.get("recommended_process_id"),
                recommended_order_id=warning.get("recommended_order_id"),
                recommended_order_no=warning.get("recommended_order_no", ""),
                mode=warning.get("mode") or OrderFocusService.mode(),
                blocking=bool(warning.get("blocking")),
                bypass_allowed=bool(warning.get("bypass_allowed")),
                reason=reason,
                detail=detail,
                user_id=user.get("id"),
                user_name=user.get("name") or user.get("username") or "",
                db=db,
            )
        except Exception:
            return None

    @staticmethod
    def active_exception(order_id):
        row = OrderRepository.find_active_completion_focus_exception(order_id)
        return dict(row) if row else None

    @staticmethod
    def create_exception(order_id, data, user):
        order = OrderRepository.find_by_id(order_id)
        if not order:
            raise ValueError("订单不存在")
        reason = (data.get("reason") or "").strip()
        if reason not in OrderFocusService.EXCEPTION_REASONS:
            raise ValueError("请选择有效的例外原因")
        detail = (data.get("detail") or "").strip()
        expires_at = (data.get("expires_at") or "").strip()
        user_name = user.get("name") or user.get("username") or ""
        with BaseService.transaction() as txn:
            exception_id = OrderRepository.insert_completion_focus_exception(
                order_id,
                reason,
                detail,
                expires_at,
                user.get("id"),
                user_name,
                db=txn,
            )
            OrderFocusService._record_event(
                EVENT_EXCEPTION_CREATED,
                order_id=order_id,
                user=user,
                reason=reason,
                detail=detail,
                db=txn,
            )
        return {
            "id": exception_id,
            "order_id": order_id,
            "reason": reason,
            "detail": detail,
            "expires_at": expires_at,
            "created_by_name": user_name,
        }

    @staticmethod
    def cancel_exception(exception_id, user, cancel_reason=""):
        with BaseService.transaction() as txn:
            exception = OrderRepository.find_completion_focus_exception_by_id(exception_id, db=txn)
            OrderRepository.cancel_completion_focus_exception(
                exception_id, user.get("id"), cancel_reason, db=txn
            )
            OrderFocusService._record_event(
                EVENT_EXCEPTION_CANCELLED,
                order_id=exception["order_id"] if exception else None,
                user=user,
                reason=cancel_reason,
                detail=f"exception_id={exception_id}",
                db=txn,
            )

    @staticmethod
    def _first_backlog_process(process_stats):
        for stat in process_stats or []:
            if stat.get("backlog", 0) > 0:
                return stat
        return None

    @staticmethod
    def _focus_type(summary, analysis, completion_pct):
        if summary.get("completed_workpieces", 0) and completion_pct >= OrderFocusService.tail_percent():
            return "tail"
        if summary.get("stuck_workpieces", 0):
            return "stuck"
        if summary.get("in_progress_workpieces", 0) or summary.get("completed_workpieces", 0):
            return "partial"
        return "pending"

    @staticmethod
    def _focus_label(focus_type):
        return {
            "tail": "尾数清理",
            "stuck": "滞留卡点",
            "partial": "部分完工",
            "pending": "待集中启动",
        }.get(focus_type, "待处理")

    @staticmethod
    def board(limit=80):
        config = OrderFocusService.config()
        if not OrderFocusService.enabled():
            return {
                "enabled": False,
                "config": config,
                "items": [],
                "summary": {"total": 0, "tail": 0, "stuck": 0, "partial": 0, "pending": 0, "exception": 0},
                "exceptions": [],
            }

        rows = []
        active_exceptions = {
            row["order_id"]: dict(row)
            for row in OrderRepository.list_active_completion_focus_exceptions()
        }
        for order in OrderRepository.list_completion_focus_orders(limit=limit):
            try:
                progress = OrderProgressAnalyzer.analyze(order["id"])
            except Exception:
                continue
            summary = progress.get("summary", {})
            analysis = progress.get("analysis", {})
            total = summary.get("total_workpieces") or progress.get("quantity") or order["quantity"] or 0
            completed = summary.get("completed_workpieces", 0)
            if not summary.get("total_workpieces"):
                completed = min(order["completed"] or 0, total)
                process_stats = []
                for process in OrderRepository.get_processes(order["id"]):
                    process_completed = min(process["completed"] or 0, total)
                    process_stats.append({
                        "process_id": process["process_id"],
                        "process_name": process["process_name"],
                        "seq_order": process["seq_order"],
                        "completed": process_completed,
                        "current": 0,
                        "pending": max(total - process_completed, 0),
                        "stuck": 0,
                        "backlog": max(total - process_completed, 0),
                        "total": total,
                        "completion_pct": round(process_completed / max(total, 1) * 100, 1),
                    })
                summary = {
                    **summary,
                    "total_workpieces": total,
                    "completed_workpieces": completed,
                    "remaining_workpieces": max(total - completed, 0),
                    "in_progress_workpieces": 0,
                    "pending_workpieces": max(total - completed, 0),
                    "stuck_workpieces": 0,
                    "process_stats": process_stats,
                    "overall_progress_pct": round(completed / max(total, 1) * 100, 1),
                }
            remaining = summary.get("remaining_workpieces", 0)
            if not total or remaining <= 0:
                continue

            completed = summary.get("completed_workpieces", completed)
            completion_pct = round(completed / max(total, 1) * 100, 1)
            bottlenecks = analysis.get("bottlenecks") or []
            bottleneck = bottlenecks[0] if bottlenecks else OrderFocusService._first_backlog_process(
                summary.get("process_stats")
            )
            focus_type = OrderFocusService._focus_type(summary, analysis, completion_pct)
            exception = active_exceptions.get(order["id"])
            if exception:
                focus_type = "exception"
            rows.append({
                "order_id": progress.get("order_id"),
                "order_no": progress.get("order_no"),
                "product_name": progress.get("product_name"),
                "product_code": order["product_code"] or "",
                "customer": order["customer_name"] or order["customer"] or "",
                "route_name": progress.get("route_name") or order["route_name"] or "",
                "quantity": progress.get("quantity"),
                "created_at": order["created_at"] or "",
                "deadline": progress.get("deadline") or "",
                "completed_workpieces": completed,
                "remaining_workpieces": remaining,
                "in_progress_workpieces": summary.get("in_progress_workpieces", 0),
                "pending_workpieces": summary.get("pending_workpieces", 0),
                "stuck_workpieces": summary.get("stuck_workpieces", 0),
                "completion_pct": completion_pct,
                "overall_progress_pct": summary.get("overall_progress_pct", 0),
                "focus_type": focus_type,
                "focus_label": "例外放行" if exception else OrderFocusService._focus_label(focus_type),
                "is_exception": bool(exception),
                "exception": exception,
                "exception_reason": exception.get("reason") if exception else "",
                "exception_expires_at": exception.get("expires_at") if exception else "",
                "priority_process_id": bottleneck.get("process_id") if bottleneck else None,
                "priority_process_name": bottleneck.get("process_name") if bottleneck else "",
                "priority_backlog": bottleneck.get("backlog", 0) if bottleneck else 0,
                "priority_stuck": bottleneck.get("stuck", 0) if bottleneck else 0,
                "risk_level": (analysis.get("deadline_risk") or {}).get("level", "low"),
                "risk_reason": (analysis.get("deadline_risk") or {}).get("reason", ""),
                "recommendations": analysis.get("recommendations", [])[:3],
            })

        rows.sort(key=lambda item: (
            item["created_at"] or "",
            1 if item["is_exception"] else 0,
            0 if item["focus_type"] == "tail" else 1,
            -item["completion_pct"],
            item["order_id"] or 0,
        ))
        summary = {
            "total": len(rows),
            "tail": sum(1 for item in rows if item["focus_type"] == "tail"),
            "stuck": sum(1 for item in rows if item["stuck_workpieces"] > 0),
            "partial": sum(1 for item in rows if item["focus_type"] == "partial"),
            "pending": sum(1 for item in rows if item["focus_type"] == "pending"),
            "exception": sum(1 for item in rows if item["is_exception"]),
        }
        return {
            "enabled": True,
            "config": config,
            "tail_percent": OrderFocusService.tail_percent(),
            "summary": summary,
            "items": rows,
            "exceptions": list(active_exceptions.values()),
        }

    @staticmethod
    def _build_priority_warning(order_data, current_process, user=None):
        if not OrderFocusService.scan_hint_enabled() or not order_data or not current_process:
            return None
        process_id = current_process.get("process_id")
        if not process_id:
            return None
        if OrderFocusService.active_exception(order_data.get("id")):
            return None
        priority = OrderRepository.find_earlier_completion_focus_order(
            order_data.get("id"),
            process_id,
            route_id=order_data.get("route_id"),
            product_code=(order_data.get("product_code") or "").strip(),
        )
        if not priority:
            return None

        backlog = int(priority["backlog"] or 0)
        hard = OrderFocusService.hard_block_enabled()
        bypass_allowed = OrderFocusService.can_bypass(user)
        blocking = hard and not bypass_allowed
        message = (
            f"集中完工{'强拦截' if blocking else '提示'}：同路线/同产品存在更早下达订单"
            f"「{priority['order_no']}」的「{priority['process_name']}」还剩 {backlog} 件。"
            + (
                "请先完成前序订单，或联系班组长/管理员设置例外后再报工。"
                if blocking else
                "当前订单允许继续报工，但建议先按班组排程完成前序订单尾数。"
            )
        )
        return {
            "enabled": True,
            "mode": OrderFocusService.mode(),
            "blocking": blocking,
            "bypass_allowed": bypass_allowed,
            "severity": "danger" if blocking else "warning",
            "message": message,
            "recommended_order_id": priority["id"],
            "recommended_order_no": priority["order_no"],
            "recommended_process_id": priority["process_id"],
            "recommended_process_name": priority["process_name"],
            "recommended_backlog": backlog,
        }

    @staticmethod
    def scan_priority_warning(order_data, current_process, user=None):
        warning = OrderFocusService._build_priority_warning(order_data, current_process, user=user)
        if warning and warning.get("bypass_allowed") and OrderFocusService.hard_block_enabled():
            OrderFocusService._record_event(
                EVENT_SCAN_BYPASSED,
                order_id=order_data.get("id") if order_data else None,
                process_id=current_process.get("process_id") if current_process else None,
                warning=warning,
                user=user,
            )
        return warning

    @staticmethod
    def report_block_error(order, process_id, user):
        if not order or not OrderFocusService.hard_block_enabled():
            return None
        warning = OrderFocusService._build_priority_warning(
            dict(order),
            {"process_id": process_id},
            user=user,
        )
        if not warning:
            return None
        if warning.get("bypass_allowed"):
            OrderFocusService._record_event(
                EVENT_SCAN_BYPASSED,
                order_id=order["id"],
                process_id=process_id,
                warning=warning,
                user=user,
            )
            return None
        if not warning.get("blocking"):
            return None
        OrderFocusService._record_event(
            EVENT_SCAN_BLOCKED,
            order_id=order["id"],
            process_id=process_id,
            warning=warning,
            user=user,
        )
        return ({"error": warning["message"], "completion_focus_warning": warning}, 409)
