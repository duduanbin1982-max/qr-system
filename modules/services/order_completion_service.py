"""Derive the order completion state from workpiece and process facts."""

from modules.repositories.audit_log_repository import AuditLogRepository
from modules.repositories.order_completion_repository import OrderCompletionRepository
from modules.services import BaseService


class OrderCompletionService:
    """Keep ``orders.status`` synchronized at completion-sensitive boundaries."""

    ACTIVE_STATUSES = {"pending", "producing"}

    @staticmethod
    def _evaluate(snapshot):
        data = dict(snapshot)
        quantity = max(int(data.get("quantity") or 0), 0)
        serial_mode = (data.get("qr_mode") or "").strip().lower() == "serial"

        if serial_mode:
            completed = min(int(data.get("completed_items") or 0), quantity)
            mode_ready = (
                quantity > 0
                and int(data.get("item_total") or 0) >= quantity
                and int(data.get("completed_items") or 0) >= quantity
                and int(data.get("incomplete_items") or 0) == 0
            )
        else:
            completed = min(int(data.get("final_process_completed") or 0), quantity)
            mode_ready = quantity > 0

        process_total = int(data.get("process_total") or 0)
        processes_ready = (
            process_total > 0
            and int(data.get("completed_processes") or 0) == process_total
        )
        ready = (
            mode_ready
            and processes_ready
            and int(data.get("pending_approvals") or 0) == 0
        )
        target_status = "completed" if ready else data.get("status")
        return {
            **data,
            "derived_completed": completed,
            "target_status": target_status,
            "ready": ready,
            "needs_update": (
                completed != int(data.get("completed") or 0)
                or target_status != data.get("status")
            ),
        }

    @staticmethod
    def _reconcile_in_transaction(order_id, trigger, actor_id, db, apply_changes=True):
        snapshot = OrderCompletionRepository.find_snapshot(order_id, db=db)
        if not snapshot:
            return {"order_id": order_id, "found": False, "changed": False}

        result = OrderCompletionService._evaluate(snapshot)
        result.update({"found": True, "changed": False, "trigger": trigger})
        if result["deleted_at"] is not None or result["status"] not in OrderCompletionService.ACTIVE_STATUSES:
            return result
        if not result["needs_update"] or not apply_changes:
            return result

        changed = OrderCompletionRepository.update_derived_state(
            order_id,
            result["derived_completed"],
            result["target_status"],
            db=db,
        )
        result["changed"] = changed > 0
        if changed and result["target_status"] != result["status"]:
            detail = (
                f"trigger={trigger}; status={result['status']}->{result['target_status']}; "
                f"completed={result['derived_completed']}/{result['quantity']}; "
                f"items={result['completed_items']}/{result['item_total']}; "
                f"processes={result['completed_processes']}/{result['process_total']}"
            )
            AuditLogRepository.insert_log(
                actor_id,
                "order_status_reconciled",
                "order",
                order_id,
                detail,
                db=db,
            )
        return result

    @staticmethod
    def reconcile(order_id, trigger="unknown", actor_id=None, db=None):
        if db is not None:
            return OrderCompletionService._reconcile_in_transaction(
                order_id, trigger, actor_id, db
            )
        with BaseService.transaction() as txn:
            return OrderCompletionService._reconcile_in_transaction(
                order_id, trigger, actor_id, txn
            )

    @staticmethod
    def reconcile_all(dry_run=True, trigger="completion_repair", actor_id=None):
        results = []
        with BaseService.transaction() as txn:
            for order_id in OrderCompletionRepository.list_active_order_ids(db=txn):
                result = OrderCompletionService._reconcile_in_transaction(
                    order_id,
                    trigger,
                    actor_id,
                    txn,
                    apply_changes=not dry_run,
                )
                if result.get("needs_update"):
                    results.append(result)
        return results
