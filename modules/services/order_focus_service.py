"""Order completion focus board, exceptions, and scan control policy."""

import logging

from modules.repositories.completion_focus_repository import CompletionFocusRepository
from modules.repositories.order_repository import OrderRepository
from modules.repositories.setting_repository import SettingRepository
from modules.domain.order_focus import OrderFocusPolicy
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


_logger = logging.getLogger(__name__)


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
            return CompletionFocusRepository.insert_event(
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
            _logger.exception("failed to record completion-focus event: %s", event_type)
            return None

    @staticmethod
    def active_exception(order_id):
        row = CompletionFocusRepository.find_active_exception(order_id)
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
            exception_id = CompletionFocusRepository.insert_exception(
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
    def exception_order_id(exception_id):
        exception = CompletionFocusRepository.find_exception_by_id(exception_id)
        return exception["order_id"] if exception else None

    @staticmethod
    def cancel_exception(exception_id, user, cancel_reason=""):
        with BaseService.transaction() as txn:
            exception = CompletionFocusRepository.find_exception_by_id(exception_id, db=txn)
            if not exception:
                raise ValueError("集中完工例外不存在")
            CompletionFocusRepository.cancel_exception(
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
        return OrderFocusPolicy.first_backlog_process(process_stats)

    @staticmethod
    def _focus_type(summary, analysis, completion_pct):
        return OrderFocusPolicy.focus_type(
            summary, completion_pct, OrderFocusService.tail_percent()
        )

    @staticmethod
    def _focus_label(focus_type):
        return OrderFocusPolicy.focus_label(focus_type)

    @staticmethod
    def board(limit=80, data_scope_pids=None):
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
        tail_percent = OrderFocusService.tail_percent()
        order_rows = CompletionFocusRepository.list_orders(
            limit=limit,
            data_scope_pids=data_scope_pids,
        )
        visible_order_ids = [row["id"] for row in order_rows]
        active_exceptions = {
            row["order_id"]: dict(row)
            for row in CompletionFocusRepository.list_active_exceptions(visible_order_ids)
        } if visible_order_ids else {}
        for order_row in order_rows:
            order = dict(order_row)
            try:
                progress = OrderProgressAnalyzer.analyze(order["id"])
            except Exception:
                continue
            summary = progress.get("summary", {})
            fallback_processes = (
                [] if summary.get("total_workpieces") else
                [dict(process) for process in OrderRepository.get_processes(order["id"])]
            )
            item = OrderFocusPolicy.board_item(
                progress,
                order,
                active_exceptions.get(order["id"]),
                tail_percent,
                fallback_processes,
            )
            if item:
                rows.append(item)

        rows.sort(key=OrderFocusPolicy.sort_key)
        return {
            "enabled": True,
            "config": config,
            "tail_percent": tail_percent,
            "summary": OrderFocusPolicy.summarize(rows),
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
        priority = CompletionFocusRepository.find_earlier_order(
            order_data.get("id"),
            process_id,
            route_id=order_data.get("route_id"),
            product_code=(order_data.get("product_code") or "").strip(),
        )
        if not priority:
            return None

        hard = OrderFocusService.hard_block_enabled()
        bypass_allowed = OrderFocusService.can_bypass(user)
        return OrderFocusPolicy.priority_warning(
            dict(priority), OrderFocusService.mode(), hard, bypass_allowed
        )

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
