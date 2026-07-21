"""Approval workflow orchestration service."""
from modules.services import BaseService
from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.repositories.approval_repository import ApprovalRepository
from modules.services.scan_helper_service import ScanHelperService
from modules.services.work_report_writer import WorkReportWriter


class ApprovalService:
    """Coordinate approval records and their work-report effects."""

    @staticmethod
    def list_pending(page, limit):
        """Return pending approval records."""
        total = ApprovalRepository.count_by_status('pending')
        offset = (page - 1) * limit
        rows = ApprovalRepository.find_by_status('pending', limit, offset)
        return {
            'approvals': [dict(r) for r in rows],
            'total': total, 'page': page, 'limit': limit
        }

    @staticmethod
    def list_history(page, limit):
        """Return processed approval records."""
        total = ApprovalRepository.count_by_status('history')
        offset = (page - 1) * limit
        rows = ApprovalRepository.find_by_status('history', limit, offset)
        return {
            'approvals': [dict(r) for r in rows],
            'total': total, 'page': page, 'limit': limit
        }

    @staticmethod
    def handle(record_id, action, approver, comment=''):
        """Approve or reject one pending work report.

        Args:
            record_id: approval record ID
            action: ``approve`` or ``reject``
            approver: dict with 'id' and 'name'
            comment: optional approval comment

        Raises:
            DomainError: when the action or approval state is invalid
        """
        if action not in ('approve', 'reject'):
            raise ValidationError('审批操作必须是通过或驳回')

        record = ApprovalRepository.find_by_id(record_id)
        if not record:
            raise NotFoundError('审批记录不存在')
        record = dict(record)
        if record['status'] != 'pending':
            raise ConflictError('审批记录已处理，请勿重复操作')

        approver_id = approver['id']
        approver_name = approver['name']

        if action == 'approve':
            # Load the work report linked to this approval.
            wr = ApprovalRepository.find_work_record(record['work_record_id'])
            if not wr:
                raise NotFoundError('关联的报工记录不存在')
            wr = dict(wr)
            if wr['status'] == 'approved':
                raise ConflictError('报工记录已审批，请勿重复操作')

            # Validate the order invariant before applying approved quantity.
            order = ApprovalRepository.find_order(wr['order_id'])
            if not order or order['deleted_at'] is not None:
                raise NotFoundError('关联订单不存在或已删除')
            order = dict(order)
            order_process = ApprovalRepository.find_order_process(
                wr['order_id'], wr['process_id']
            )
            if not order_process:
                raise NotFoundError('关联订单工序不存在')
            process_completed = order_process['completed'] if order_process else 0
            if (process_completed or 0) + wr['quantity'] > order['quantity']:
                raise ConflictError(
                    f'审批后工序完成数量({process_completed or 0}+{wr["quantity"]})'
                    f'将超过订单数量({order["quantity"]})'
                )

            # Multi-level approval
            current_level = record.get('current_level', 1) or 1
            cfg_row = ApprovalRepository.find_approval_config(wr.get('process_id'))
            cfg_row = dict(cfg_row) if cfg_row else None
            max_level = cfg_row['approval_level'] if cfg_row else 1

            if current_level >= max_level:
                with BaseService.transaction() as txn:
                    ApprovalRepository.approve(
                        record_id, approver_id, approver_name, comment, db=txn
                    )
                    ApprovalRepository.update_work_record_status(
                        record['work_record_id'], 'approved', db=txn
                    )
                    WorkReportWriter.apply_approved_normal_report(
                        ScanHelperService,
                        wr['order_id'],
                        wr['process_id'],
                        wr['user_id'],
                        wr['user_name'],
                        wr['quantity'],
                        wr['serial_no'],
                        txn,
                    )
            else:
                next_level = current_level + 1
                with BaseService.transaction() as txn:
                    ApprovalRepository.advance_level(
                        record_id, approver_id, approver_name, comment, next_level, db=txn
                    )
        else:
            with BaseService.transaction() as txn:
                ApprovalRepository.reject(
                    record_id, approver_id, approver_name, comment, db=txn
                )
                ApprovalRepository.update_work_record_status(
                    record['work_record_id'], 'rejected', db=txn
                )

        return action

    @staticmethod
    def list_configs():
        """获取所有工序的审批配置"""
        rows = ApprovalRepository.find_all_configs()
        return {"configs": [dict(r) for r in rows]}

    @staticmethod
    def save_configs(configs):
        """保存审批配置(支持批量)
        Args:
            configs: list of dict {process_id, require_approval, approver_role, approver_role_2, approver_role_3, approval_level}
        """
        from modules.services import BaseService
        with BaseService.transaction() as txn:
            for cfg in configs:
                pid = cfg["process_id"]
                require = 1 if cfg.get("require_approval") else 0
                role = cfg.get("approver_role", "admin")
                role2 = cfg.get("approver_role_2", "")
                role3 = cfg.get("approver_role_3", "")
                level = cfg.get("approval_level", 1)
                ApprovalRepository.upsert_config(pid, require, role, role2, role3, level, db=txn)
        return True

    @staticmethod
    def get_stats():
        """获取审批统计数据"""
        return ApprovalRepository.get_approval_stats()

    @staticmethod
    def batch_handle(record_ids, action, approver, comment=""):
        """Batch handle multiple approval records.
        Returns (processed_count, failed_ids) tuple.
        """
        processed = 0
        failed = []
        for rid in record_ids:
            try:
                ApprovalService.handle(rid, action, approver, comment)
                processed += 1
            except ValueError as e:
                failed.append({"id": rid, "reason": str(e)})
        return processed, failed
