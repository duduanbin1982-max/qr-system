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
            with BaseService.transaction() as txn:
                ApprovalRepository.reject(
                    record_id, approver_id, approver_name, comment, db=txn
                )
                ApprovalRepository.update_work_record_status(
                    record['work_record_id'], 'rejected', db=txn
                )

        return action
