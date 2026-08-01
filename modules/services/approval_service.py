"""Approval workflow orchestration service."""
from modules.services import BaseService
from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.repositories.auth_repository import AuthRepository
from modules.repositories.approval_repository import ApprovalRepository
from modules.repositories.process_repository import ProcessRepository
from modules.repositories.role_repository import RoleRepository
from modules.services.work_report_writer import WorkReportWriter
from modules.domain.work_report import WorkReportCommand
from modules.services.access_policy_service import has_permission
from modules.services.serial_backfill_service import SerialBackfillService


class ApprovalService:
    """Coordinate approval records and their work-report effects."""

    ROLE_ALIASES = {
        'supervisor': 'production_manager',
        'quality': 'qc_inspector',
    }
    DEFAULT_APPROVER_ROLE = 'admin'

    @staticmethod
    def _normalize_role_code(role_code):
        code = (role_code or '').strip().lower()
        if not code:
            return ''
        return ApprovalService.ROLE_ALIASES.get(code, code)

    @staticmethod
    def _role_name_map(db=None):
        rows = RoleRepository.list_approval_roles(db=db)
        return {
            ApprovalService._normalize_role_code(row['code']): row['name']
            for row in rows
        }

    @staticmethod
    def _role_options(db=None):
        rows = RoleRepository.list_approval_roles(db=db)
        options = []
        seen = set()
        for row in rows:
            code = ApprovalService._normalize_role_code(row['code'])
            if not code or code in seen:
                continue
            seen.add(code)
            options.append({'code': code, 'name': row['name']})
        return options

    @staticmethod
    def _normalized_config_row(row):
        cfg = dict(row)
        cfg['approver_role'] = ApprovalService._normalize_role_code(cfg.get('approver_role'))
        cfg['approver_role_2'] = ApprovalService._normalize_role_code(cfg.get('approver_role_2'))
        cfg['approver_role_3'] = ApprovalService._normalize_role_code(cfg.get('approver_role_3'))
        return cfg

    @staticmethod
    def _approval_roles_from_config(cfg_row):
        if not cfg_row or not cfg_row.get('require_approval', 1):
            return [ApprovalService.DEFAULT_APPROVER_ROLE]
        try:
            approval_level = int(cfg_row.get('approval_level') or 1)
        except (TypeError, ValueError):
            raise ValidationError('审批级别必须为 1 到 3 级')
        if approval_level < 1 or approval_level > 3:
            raise ValidationError('审批级别必须为 1 到 3 级')
        base_roles = [
            ApprovalService._normalize_role_code(cfg_row.get('approver_role') or ApprovalService.DEFAULT_APPROVER_ROLE),
            ApprovalService._normalize_role_code(cfg_row.get('approver_role_2')),
            ApprovalService._normalize_role_code(cfg_row.get('approver_role_3')),
        ]
        effective_roles = []
        last_role = ApprovalService.DEFAULT_APPROVER_ROLE
        for idx in range(approval_level):
            role = base_roles[idx] or last_role or ApprovalService.DEFAULT_APPROVER_ROLE
            effective_roles.append(role)
            last_role = role
        return effective_roles

    @staticmethod
    def _current_user_role(approver, db=None):
        approver_id = approver.get('id')
        if approver_id is not None:
            role = ApprovalService._normalize_role_code(
                AuthRepository.get_user_role_code(approver_id, db=db)
            )
            if role:
                return role
        return ApprovalService._normalize_role_code(approver.get('role', ''))

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

        approver_id = approver['id']
        approver_name = approver['name']

        with BaseService.transaction() as txn:
            record = ApprovalRepository.find_by_id(record_id, db=txn)
            if not record:
                raise NotFoundError('审批记录不存在')
            record = dict(record)
            if record['status'] != 'pending':
                raise ConflictError('审批记录已处理，请勿重复操作')

            wr = ApprovalRepository.find_work_record(record['work_record_id'], db=txn)
            if not wr:
                raise NotFoundError('关联的报工记录不存在')
            wr = dict(wr)
            if wr['status'] == 'approved':
                raise ConflictError('报工记录已审批，请勿重复操作')
            if (
                wr.get('report_source') == 'serial_backfill'
                and not has_permission(approver, SerialBackfillService.APPROVE_PERMISSION)
            ):
                raise ConflictError('您没有序列号补报审批权限')

            cfg_row = ApprovalRepository.find_approval_config(wr.get('process_id'), db=txn)
            cfg = dict(cfg_row) if cfg_row else None
            approval_roles = ApprovalService._approval_roles_from_config(cfg)
            current_level = int(record.get('current_level', 1) or 1)
            if current_level < 1 or current_level > len(approval_roles):
                raise ValidationError('审批级别配置无效')
            current_role = ApprovalService._current_user_role(approver, db=txn)
            required_role = approval_roles[current_level - 1]
            if current_role != required_role:
                role_map = ApprovalService._role_name_map(db=txn)
                raise ConflictError(
                    f'当前审批步骤需要“{role_map.get(required_role, required_role)}”角色处理'
                )

            if action == 'approve':
                order = ApprovalRepository.find_order(wr['order_id'], db=txn)
                if not order or order['deleted_at'] is not None:
                    raise NotFoundError('关联订单不存在或已删除')
                order = dict(order)
                order_process = ApprovalRepository.find_order_process(
                    wr['order_id'], wr['process_id'], db=txn
                )
                if not order_process:
                    raise NotFoundError('关联订单工序不存在')
                process_completed = order_process['completed'] or 0
                if process_completed + wr['quantity'] > order['quantity']:
                    raise ConflictError(
                        f'审批后工序完成数量({process_completed}+{wr["quantity"]})'
                        f'将超过订单数量({order["quantity"]})'
                    )

                if current_level >= len(approval_roles):
                    updated = ApprovalRepository.approve(
                        record_id, approver_id, approver_name, comment, db=txn
                    )
                    if updated != 1:
                        raise ConflictError('审批记录状态已变化，请刷新后重试')
                    updated_work = ApprovalRepository.update_work_record_status(
                        record['work_record_id'], 'approved', db=txn
                    )
                    if updated_work != 1:
                        raise ConflictError('报工记录状态已变化，请刷新后重试')
                    ApprovalRepository.insert_approval_step(
                        record_id, current_level, approver_id, approver_name,
                        current_role, 'approve', comment, db=txn,
                    )
                    command = WorkReportCommand.from_approved_record(wr)
                    WorkReportWriter.apply_approved_normal_report(
                        command,
                        txn,
                        record['work_record_id'],
                    )
                else:
                    next_level = current_level + 1
                    updated = ApprovalRepository.advance_level(
                        record_id, approver_id, approver_name, comment,
                        next_level, current_level, db=txn,
                    )
                    if updated != 1:
                        raise ConflictError('审批记录状态已变化，请刷新后重试')
                    ApprovalRepository.insert_approval_step(
                        record_id, current_level, approver_id, approver_name,
                        current_role, 'advance', comment, db=txn,
                    )
            else:
                updated = ApprovalRepository.reject(
                    record_id, approver_id, approver_name, comment, db=txn
                )
                if updated != 1:
                    raise ConflictError('审批记录状态已变化，请刷新后重试')
                updated_work = ApprovalRepository.update_work_record_status(
                    record['work_record_id'], 'rejected', db=txn
                )
                if updated_work != 1:
                    raise ConflictError('报工记录状态已变化，请刷新后重试')
                ApprovalRepository.insert_approval_step(
                    record_id, current_level, approver_id, approver_name,
                    current_role, 'reject', comment, db=txn,
                )

        return action

    @staticmethod
    def list_configs():
        """获取全部工序审批配置及可选审批角色。"""
        rows = ApprovalRepository.find_all_configs()
        return {
            'configs': [ApprovalService._normalized_config_row(r) for r in rows],
            'role_options': ApprovalService._role_options(),
        }

    @staticmethod
    def save_configs(configs):
        """保存审批配置（支持批量）。
        Args:
            configs: list of dict {process_id, require_approval, approver_role, approver_role_2, approver_role_3, approval_level}
        """
        if isinstance(configs, dict):
            configs = [configs]
        if not isinstance(configs, list):
            raise ValidationError('审批配置必须是列表')

        with BaseService.transaction() as txn:
            role_map = ApprovalService._role_name_map(db=txn)
            allowed_roles = set(role_map.keys())
            for cfg in configs:
                if not isinstance(cfg, dict):
                    raise ValidationError('每项审批配置必须是对象')
                pid = cfg.get('process_id')
                try:
                    pid = int(pid)
                except (TypeError, ValueError):
                    raise ValidationError('process_id 必须是整数')
                if not ProcessRepository.find_by_id(pid, db=txn):
                    raise NotFoundError('工序不存在')

                require = 1 if cfg.get('require_approval') else 0
                if not require:
                    ApprovalRepository.upsert_config(pid, 0, '', '', '', 1, db=txn)
                    continue

                try:
                    level = int(cfg.get('approval_level', 1))
                except (TypeError, ValueError):
                    raise ValidationError('审批级别必须是整数')
                if level < 1 or level > 3:
                    raise ValidationError('审批级别必须为 1 到 3 级')

                role1 = ApprovalService._normalize_role_code(cfg.get('approver_role') or ApprovalService.DEFAULT_APPROVER_ROLE)
                role2 = ApprovalService._normalize_role_code(cfg.get('approver_role_2'))
                role3 = ApprovalService._normalize_role_code(cfg.get('approver_role_3'))
                effective_roles = [role for role in (role1, role2, role3) if role]
                if not effective_roles:
                    raise ValidationError('启用审批时至少需要一个审批角色')
                if len(effective_roles) != level:
                    raise ValidationError('审批角色数量必须与审批级别一致')
                if len(set(effective_roles)) != len(effective_roles):
                    raise ValidationError('各级审批角色不能重复')
                invalid_roles = [role for role in effective_roles if role not in allowed_roles]
                if invalid_roles:
                    raise ValidationError(f'角色“{invalid_roles[0]}”不存在或已停用')

                ApprovalRepository.upsert_config(pid, 1, role1, role2, role3, level, db=txn)
        return True

    @staticmethod
    def get_stats():
        """获取审批统计数据。"""
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
