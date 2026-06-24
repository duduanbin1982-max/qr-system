"""
qr-system ? ApprovalService???????????

? routes/approvals.py ???????SQL ??? ApprovalRepository?
?? BaseService.transaction() ???? SAVEPOINT?
"""
from modules.services import BaseService
from modules.repositories.approval_repository import ApprovalRepository


class ApprovalService:
    """?????????"""

    @staticmethod
    def list_pending(page, limit):
        """????????????"""
        total = ApprovalRepository.count_by_status('pending')
        offset = (page - 1) * limit
        rows = ApprovalRepository.find_by_status('pending', limit, offset)
        return {
            'approvals': [dict(r) for r in rows],
            'total': total, 'page': page, 'limit': limit
        }

    @staticmethod
    def list_history(page, limit):
        """??????????????"""
        total = ApprovalRepository.count_by_status('history')
        offset = (page - 1) * limit
        rows = ApprovalRepository.find_by_status('history', limit, offset)
        return {
            'approvals': [dict(r) for r in rows],
            'total': total, 'page': page, 'limit': limit
        }

    @staticmethod
    def handle(record_id, action, approver, comment=''):
        """??????????????????

        Args:
            record_id: ???? ID
            action: 'approve' ? 'reject'
            approver: dict with 'id' and 'name'
            comment: ????

        Raises:
            ValueError: ???????????????
        """
        if action not in ('approve', 'reject'):
            raise ValueError('?????')

        record = ApprovalRepository.find_by_id(record_id)
        if not record:
            raise ValueError('???????')
        if record['status'] != 'pending':
            raise ValueError('???????')

        approver_id = approver['id']
        approver_name = approver['name']

        if action == 'approve':
            # ??????
            wr = ApprovalRepository.find_work_record(record['work_record_id'])
            if not wr:
                raise ValueError('???????')
            if wr['status'] == 'approved':
                raise ValueError('??????????????????')

            # ????
            order = ApprovalRepository.find_order(wr['order_id'])
            if not order or order['deleted_at'] is not None:
                raise ValueError('???????')
            if order['completed'] + wr['quantity'] > order['quantity']:
                raise ValueError(
                    f'?????????({order["completed"]}+{wr["quantity"]})'
                    f'??????({order["quantity"]})'
                )

            # Multi-level approval
            current_level = record.get('current_level', 1) or 1
            cfg_row = ApprovalRepository.find_approval_config(wr.get('process_id'))
            max_level = cfg_row['approval_level'] if cfg_row else 1

            if current_level >= max_level:
                with BaseService.transaction() as txn:
                    ApprovalRepository.approve(
                        record_id, approver_id, approver_name, comment, db=txn
                    )
                    ApprovalRepository.update_work_record_status(
                        record['work_record_id'], 'approved', db=txn
                    )
                    ApprovalRepository.increment_order_completed(
                        wr['order_id'], wr['quantity'], db=txn
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
