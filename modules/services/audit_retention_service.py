"""Controlled retention workflow for audit evidence."""

from modules.audit_policy import AUDIT_MIN_RETENTION_DAYS
from modules.repositories.audit_log_repository import AuditLogRepository
from modules.services import BaseService


class AuditRetentionService:
    @staticmethod
    def list_requests(status="", limit=100):
        if status and status not in {
            "pending", "approved", "executed", "rejected", "cancelled"
        }:
            raise ValueError("无效的清理申请状态")
        return AuditLogRepository.list_cleanup_requests(status, limit)

    @staticmethod
    def request_cleanup(before_days, reason, actor):
        if int(before_days) < AUDIT_MIN_RETENTION_DAYS:
            raise ValueError(
                f"操作日志最小保留期为 {AUDIT_MIN_RETENTION_DAYS} 天"
            )
        reason = str(reason or "").strip()
        if len(reason) < 4:
            raise ValueError("清理理由至少需要 4 个字符")
        with BaseService.transaction() as txn:
            result = AuditLogRepository.create_cleanup_request_txn(
                int(before_days), reason, actor.get("id"), db=txn
            )
            AuditLogRepository.insert_log(
                actor.get("id"),
                "audit_cleanup_requested",
                "audit_log_cleanup_request",
                result["id"],
                {
                    "before_at": result["before_at"],
                    "affected_count": result["affected_count"],
                    "reason": reason,
                },
                db=txn,
            )
            return result
    @staticmethod
    def reject_request(request_id, actor, reason):
        reason = str(reason or "").strip()
        if len(reason) < 4:
            raise ValueError("驳回理由至少需要 4 个字符")
        with BaseService.transaction() as txn:
            row = AuditLogRepository.find_cleanup_request(request_id, db=txn)
            if row is None:
                raise ValueError("清理申请不存在")
            if int(row["requested_by"]) == int(actor.get("id")):
                raise ValueError("申请人不能复核自己的清理申请")
            if not AuditLogRepository.reject_cleanup_request_txn(
                request_id, actor.get("id"), reason, db=txn
            ):
                raise ValueError("清理申请已经处理")
            AuditLogRepository.insert_log(
                actor.get("id"),
                "audit_cleanup_rejected",
                "audit_log_cleanup_request",
                request_id,
                {"decision_reason": reason},
                db=txn,
            )

    @staticmethod
    def approve_and_execute(request_id, actor, reason):
        reason = str(reason or "").strip()
        if len(reason) < 4:
            raise ValueError("批准意见至少需要 4 个字符")
        with BaseService.transaction() as txn:
            result = AuditLogRepository.execute_cleanup_request_txn(
                request_id, actor.get("id"), reason, db=txn
            )
            AuditLogRepository.insert_log(
                actor.get("id"),
                "audit_cleanup_executed",
                "audit_log_cleanup_request",
                request_id,
                {
                    "archive_batch_id": result["archive_batch_id"],
                    "archived": result["archived"],
                    "deleted": result["deleted"],
                    "decision_reason": reason,
                },
                db=txn,
            )
            return result
