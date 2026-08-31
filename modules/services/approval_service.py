"""Approval workflow orchestration service."""
from modules.services import BaseService
from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.approval_workflow import (
    DEFAULT_APPROVER_ROLE,
    ROLE_ALIASES,
    ApprovalWorkflow,
)
from modules.repositories.auth_repository import AuthRepository
from modules.repositories.approval_repository import ApprovalRepository
from modules.repositories.process_repository import ProcessRepository
from modules.repositories.role_repository import RoleRepository
from modules.services.work_report_writer import WorkReportWriter
from modules.domain.work_report import WorkReportCommand
from modules.services.access_policy_service import has_permission
from modules.services.serial_backfill_service import SerialBackfillService
import json
from modules.repositories.process_config_repository import ProcessConfigRepository
from modules import config


class ApprovalService:
    """Coordinate approval records and their work-report effects."""

    ROLE_ALIASES = ROLE_ALIASES
    DEFAULT_APPROVER_ROLE = DEFAULT_APPROVER_ROLE
    approval_repository = None
    auth_repository = None
    process_repository = None
    role_repository = None
    work_report_writer = None
    permission_checker = None
    serial_backfill_service = None
    unit_of_work = None

    @classmethod
    def _approval_repository(cls):
        return cls.approval_repository or ApprovalRepository

    @classmethod
    def _auth_repository(cls):
        return cls.auth_repository or AuthRepository

    @classmethod
    def _process_repository(cls):
        return cls.process_repository or ProcessRepository

    @classmethod
    def _role_repository(cls):
        return cls.role_repository or RoleRepository

    @classmethod
    def _work_report_writer(cls):
        return cls.work_report_writer or WorkReportWriter

    @classmethod
    def _permission_checker(cls):
        return vars(cls).get("permission_checker") or has_permission

    @classmethod
    def _serial_backfill_service(cls):
        return cls.serial_backfill_service or SerialBackfillService

    @classmethod
    def _unit_of_work(cls):
        return cls.unit_of_work or BaseService

    @staticmethod
    def _normalize_role_code(role_code):
        return ApprovalWorkflow.normalize_role_code(role_code)

    @staticmethod
    def _role_name_map(db=None):
        rows = ApprovalService._role_repository().list_approval_roles(db=db)
        return {
            ApprovalService._normalize_role_code(row['code']): row['name']
            for row in rows
        }

    @staticmethod
    def _role_options(db=None):
        rows = ApprovalService._role_repository().list_approval_roles(db=db)
        options = []
        seen = set()
        for row in rows:
            code = ApprovalService._normalize_role_code(row['code'])
            if not code or code in seen:
                continue
            seen.add(code)
            options.append({'id': row['id'], 'code': code, 'name': row['name']})
        return options

    @staticmethod
    def _normalized_config_row(row):
        cfg = dict(row)
        cfg['approver_role'] = ApprovalService._normalize_role_code(cfg.get('approver_role'))
        cfg['approver_role_2'] = ApprovalService._normalize_role_code(cfg.get('approver_role_2'))
        cfg['approver_role_3'] = ApprovalService._normalize_role_code(cfg.get('approver_role_3'))
        return cfg

    @staticmethod
    def _resolve_role_selection(cfg, id_key, code_key, default_code, db):
        """Resolve an approval role by stable ID, retaining code compatibility."""
        role_id = cfg.get(id_key)
        if role_id not in (None, ""):
            try:
                role_id = int(role_id)
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"{id_key} 必须是整数") from exc
            row = ApprovalService._role_repository().find_active_by_id(role_id, db=db)
            if not row:
                raise ValidationError("审批角色不存在或已停用")
            return row["id"], ApprovalService._normalize_role_code(row["code"])

        code = ApprovalService._normalize_role_code(cfg.get(code_key) or default_code)
        row = ApprovalService._role_repository().find_active_by_code(code, db=db)
        if not row:
            raise ValidationError(f"角色“{code}”不存在或已停用")
        return row["id"], ApprovalService._normalize_role_code(row["code"])

    @staticmethod
    def _approval_roles_from_config(cfg_row):
        return ApprovalWorkflow.approval_roles_from_config(cfg_row)

    @staticmethod
    def _load_pending_context(record_id, txn):
        repository = ApprovalService._approval_repository()
        record = repository.find_by_id(record_id, db=txn)
        if not record:
            raise NotFoundError('审批记录不存在')
        record = dict(record)
        work_record = repository.find_work_record(record['work_record_id'], db=txn)
        if not work_record:
            raise NotFoundError('关联的报工记录不存在')
        work_record = dict(work_record)
        ApprovalWorkflow.validate_pending(record['status'], work_record['status'])
        return record, work_record

    @staticmethod
    def _assert_backfill_permission(work_record, approver):
        backfill_service = ApprovalService._serial_backfill_service()
        if (
            work_record.get('report_source') == 'serial_backfill'
            and not ApprovalService._permission_checker()(
                approver, backfill_service.APPROVE_PERMISSION
            )
        ):
            raise ConflictError('您没有序列号补报审批权限')

    @staticmethod
    def _validate_final_quantity(work_record, txn):
        repository = ApprovalService._approval_repository()
        order = repository.find_order(work_record['order_id'], db=txn)
        if not order or order['deleted_at'] is not None:
            raise NotFoundError('关联订单不存在或已删除')
        order_process = repository.find_order_process(
            work_record['order_id'], work_record['process_id'], db=txn
        )
        if not order_process:
            raise NotFoundError('关联订单工序不存在')
        ApprovalWorkflow.validate_quantity(
            order_process['completed'],
            work_record['quantity'],
            order['quantity'],
        )

    @staticmethod
    def _require_updated(updated, message):
        if updated != 1:
            raise ConflictError(message)

    @staticmethod
    def _insert_step(record_id, decision, approver_id, approver_name, comment, txn):
        repository = ApprovalService._approval_repository()
        step_id = repository.insert_approval_step(
            record_id,
            decision.current_level,
            approver_id,
            approver_name,
            decision.current_role,
            decision.step_action,
            comment,
            db=txn,
        )
        if hasattr(repository, 'set_step_role_snapshot'):
            role = ApprovalService._role_repository().find_active_by_code(
                decision.required_role, db=txn
            )
            repository.set_step_role_snapshot(
                step_id,
                role['id'] if role else None,
                role['code'] if role else decision.required_role,
                role['name'] if role else decision.required_role,
                db=txn,
            )

    @staticmethod
    def _apply_final_approval(record_id, record, work_record, decision, approver, comment, txn):
        ApprovalService._validate_final_quantity(work_record, txn)
        ApprovalService._require_updated(
            ApprovalService._approval_repository().approve(
                record_id, approver['id'], approver['name'], comment, db=txn
            ),
            '审批记录状态已变化，请刷新后重试',
        )
        ApprovalService._require_updated(
            ApprovalService._approval_repository().update_work_record_status(
                record['work_record_id'], 'approved', db=txn
            ),
            '报工记录状态已变化，请刷新后重试',
        )
        ApprovalService._insert_step(
            record_id, decision, approver['id'], approver['name'], comment, txn
        )
        ApprovalService._work_report_writer().apply_approved_normal_report(
            WorkReportCommand.from_approved_record(work_record),
            txn,
            record['work_record_id'],
        )

    @staticmethod
    def _advance_approval(record_id, decision, approver, comment, txn):
        ApprovalService._require_updated(
            ApprovalService._approval_repository().advance_level(
                record_id,
                approver['id'],
                approver['name'],
                comment,
                decision.next_level,
                decision.current_level,
                db=txn,
            ),
            '审批记录状态已变化，请刷新后重试',
        )
        ApprovalService._insert_step(
            record_id, decision, approver['id'], approver['name'], comment, txn
        )

    @staticmethod
    def _reject_approval(record_id, record, decision, approver, comment, txn):
        ApprovalService._require_updated(
            ApprovalService._approval_repository().reject(
                record_id, approver['id'], approver['name'], comment, db=txn
            ),
            '审批记录状态已变化，请刷新后重试',
        )
        ApprovalService._require_updated(
            ApprovalService._approval_repository().update_work_record_status(
                record['work_record_id'], 'rejected', db=txn
            ),
            '报工记录状态已变化，请刷新后重试',
        )
        ApprovalService._insert_step(
            record_id, decision, approver['id'], approver['name'], comment, txn
        )

    @staticmethod
    def _decide_workflow(action, config, current_level, current_role, txn):
        try:
            return ApprovalWorkflow.decide(
                action, config, current_level, current_role
            )
        except ConflictError:
            return ApprovalWorkflow.decide(
                action,
                config,
                current_level,
                current_role,
                ApprovalService._role_name_map(db=txn),
            )

    @staticmethod
    def _current_user_role(approver, db=None):
        approver_id = approver.get('id')
        if approver_id is not None:
            role_codes = getattr(ApprovalService._auth_repository(), 'get_user_role_codes', None)
            if role_codes and hasattr(db, 'execute'):
                roles = [ApprovalService._normalize_role_code(code) for code in role_codes(approver_id, db=db)]
                if roles:
                    return roles
            role = ApprovalService._normalize_role_code(
                ApprovalService._auth_repository().get_user_role_code(approver_id, db=db)
            )
            if role:
                return [role]
        return [ApprovalService._normalize_role_code(approver.get('role', ''))]

    @staticmethod
    def _snapshot_config(record):
        raw = record.get('policy_snapshot_json') or '{}'
        try:
            snapshot = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            snapshot = {}
        if not isinstance(snapshot, dict) or 'approval_level' not in snapshot:
            return None
        roles = snapshot.get('roles') or []
        return {
            'require_approval': 1 if snapshot.get('require_approval') else 0,
            'approval_level': snapshot.get('approval_level', 1),
            'approver_role': roles[0].get('code', '') if len(roles) > 0 else '',
            'approver_role_2': roles[1].get('code', '') if len(roles) > 1 else '',
            'approver_role_3': roles[2].get('code', '') if len(roles) > 2 else '',
        }

    @staticmethod
    def list_pending(page, limit):
        """Return pending approval records."""
        repository = ApprovalService._approval_repository()
        total = repository.count_by_status('pending')
        offset = (page - 1) * limit
        rows = repository.find_by_status('pending', limit, offset)
        return {
            'approvals': [dict(r) for r in rows],
            'total': total, 'page': page, 'limit': limit
        }

    @staticmethod
    def list_history(page, limit):
        """Return processed approval records."""
        repository = ApprovalService._approval_repository()
        total = repository.count_by_status('history')
        offset = (page - 1) * limit
        rows = repository.find_by_status('history', limit, offset)
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
        ApprovalWorkflow.validate_action(action)
        with ApprovalService._unit_of_work().transaction() as txn:
            record, work_record = ApprovalService._load_pending_context(record_id, txn)
            ApprovalService._assert_backfill_permission(work_record, approver)
            cfg_row = ApprovalService._snapshot_config(record)
            if cfg_row is None:
                cfg_row = ApprovalService._approval_repository().find_approval_config(
                    work_record.get('process_id'), db=txn
                )
            current_role = ApprovalService._current_user_role(approver, db=txn)
            decision = ApprovalService._decide_workflow(
                action,
                dict(cfg_row) if cfg_row else None,
                record.get('current_level', 1),
                current_role,
                txn,
            )
            if decision.is_final:
                ApprovalService._apply_final_approval(
                    record_id, record, work_record, decision, approver, comment, txn
                )
            elif action == 'approve':
                ApprovalService._advance_approval(
                    record_id, decision, approver, comment, txn
                )
            else:
                ApprovalService._reject_approval(
                    record_id, record, decision, approver, comment, txn
                )

        return action

    @staticmethod
    def list_configs():
        """获取全部工序审批配置及可选审批角色。"""
        rows = ApprovalService._approval_repository().find_all_configs()
        configs = [ApprovalService._normalized_config_row(r) for r in rows]
        if config.APPROVAL_POLICY_VERSIONED_QUERY_ENABLED:
            from modules.services.approval_policy_service import ApprovalPolicyService
            for item in configs:
                snapshot, revision_id = ApprovalPolicyService.effective_snapshot(
                    item['process_id'], use_versioned=True
                )
                roles = snapshot.get('roles') or []
                item.update({
                    'require_approval': 1 if snapshot.get('require_approval') else 0,
                    'approval_level': snapshot.get('approval_level', 1),
                    'approver_role': roles[0].get('code', '') if len(roles) > 0 else '',
                    'approver_role_2': roles[1].get('code', '') if len(roles) > 1 else '',
                    'approver_role_3': roles[2].get('code', '') if len(roles) > 2 else '',
                    'approval_policy_revision_id': revision_id,
                    'policy_source': snapshot.get('source'),
                })
        process_config = ProcessConfigRepository.get_active()
        return {
            'configs': configs,
            'role_options': ApprovalService._role_options(),
            'global_approval_enabled': bool(process_config['approval_enabled']) if process_config else True,
        }

    @staticmethod
    def save_configs(configs):
        """保存审批配置（支持批量）。
        Args:
            configs: list of dict {process_id, require_approval, approver_role, approver_role_2, approver_role_3, approval_level}
        """
        if config.APPROVAL_POLICY_LEGACY_WRITE_BLOCKED:
            raise ConflictError('Legacy 审批配置写入已关闭，请使用版本化审批策略接口')
        if isinstance(configs, dict):
            configs = [configs]
        if not isinstance(configs, list):
            raise ValidationError('审批配置必须是列表')

        with ApprovalService._unit_of_work().transaction() as txn:
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
                if not ApprovalService._process_repository().find_by_id(pid, db=txn):
                    raise NotFoundError('工序不存在')

                require = 1 if cfg.get('require_approval') else 0
                if not require:
                    ApprovalService._approval_repository().upsert_config(
                        pid, 0, '', '', '', 1, db=txn
                    )
                    continue

                try:
                    level = int(cfg.get('approval_level', 1))
                except (TypeError, ValueError):
                    raise ValidationError('审批级别必须是整数')
                if level < 1 or level > 3:
                    raise ValidationError('审批级别必须为 1 到 3 级')

                role1_id, role1 = ApprovalService._resolve_role_selection(
                    cfg, 'approver_role_id', 'approver_role', ApprovalService.DEFAULT_APPROVER_ROLE, txn
                )
                role2_id = role3_id = None
                role2 = role3 = ''
                if cfg.get('approver_role_2_id') not in (None, '') or cfg.get('approver_role_2'):
                    role2_id, role2 = ApprovalService._resolve_role_selection(
                        cfg, 'approver_role_2_id', 'approver_role_2', '', txn
                    )
                if cfg.get('approver_role_3_id') not in (None, '') or cfg.get('approver_role_3'):
                    role3_id, role3 = ApprovalService._resolve_role_selection(
                        cfg, 'approver_role_3_id', 'approver_role_3', '', txn
                    )
                effective_roles = [role for role in (role1, role2, role3) if role]
                effective_role_ids = [role_id for role_id in (role1_id, role2_id, role3_id) if role_id]
                if not effective_roles:
                    raise ValidationError('启用审批时至少需要一个审批角色')
                if len(effective_roles) != level:
                    raise ValidationError('审批角色数量必须与审批级别一致')
                if len(set(effective_roles)) != len(effective_roles):
                    raise ValidationError('各级审批角色不能重复')
                invalid_roles = [role for role in effective_roles if role not in allowed_roles]
                if invalid_roles:
                    raise ValidationError(f'角色“{invalid_roles[0]}”不存在或已停用')
                if len(set(effective_role_ids)) != len(effective_role_ids):
                    raise ValidationError('各级审批角色不能重复')

                ApprovalService._approval_repository().upsert_config(
                    pid, 1, role1, role2, role3, level, db=txn,
                    approver_role_id=role1_id,
                    approver_role_2_id=role2_id,
                    approver_role_3_id=role3_id,
                )
        return True

    @staticmethod
    def get_stats():
        """获取审批统计数据。"""
        return ApprovalService._approval_repository().get_approval_stats()

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
