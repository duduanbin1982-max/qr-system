"""Application service for versioned approval-policy revisions."""

import hashlib
import json

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.approval_policy import assert_transition, validate_policy_payload
from modules.repositories.approval_policy_repository import ApprovalPolicyRepository
from modules.repositories.process_repository import ProcessRepository
from modules.repositories.role_repository import RoleRepository
from modules.db_unit_of_work import BaseService
from modules import config
from modules.repositories.approval_repository import ApprovalRepository


class ApprovalPolicyService:
    policy_repository = ApprovalPolicyRepository
    process_repository = ProcessRepository
    role_repository = RoleRepository
    unit_of_work = BaseService

    @classmethod
    def list(cls, include_history=False):
        rows = cls.policy_repository.list_policies(include_history=include_history)
        result = []
        for row in rows:
            item = dict(row)
            if item.get("current_revision_id"):
                item["steps"] = [dict(step) for step in cls.policy_repository.list_steps(item["current_revision_id"])]
            else:
                item["steps"] = []
            result.append(item)
        return {"policies": result}

    @classmethod
    def history(cls, policy_id):
        if not cls.policy_repository.find_policy(policy_id):
            raise NotFoundError("审批策略不存在")
        return {"revisions": [dict(row) for row in cls.policy_repository.list_revisions(policy_id)]}

    @classmethod
    def create_revision(cls, payload, actor):
        if not config.APPROVAL_POLICY_VERSIONED_WRITE_ENABLED:
            raise ConflictError("审批策略版本化写入尚未启用")
        normalized = validate_policy_payload(payload)
        process_id = payload.get("process_id")
        if process_id is not None:
            try:
                process_id = int(process_id)
            except (TypeError, ValueError) as exc:
                raise ValidationError("process_id 必须是整数") from exc
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        if not idempotency_key:
            raise ValidationError("idempotency_key 不能为空")
        with cls.unit_of_work.transaction() as txn:
            existing = cls.policy_repository.find_by_idempotency_key(idempotency_key, db=txn)
            if existing:
                return dict(existing)
            if process_id is not None and not cls.process_repository.find_by_id(process_id, db=txn):
                raise NotFoundError("工序不存在")
            policy = cls.policy_repository.find_policy_by_process(process_id, db=txn)
            if not policy:
                key = f"process:{process_id}" if process_id is not None else "global"
                policy_id = cls.policy_repository.create_policy(key, process_id, key, txn)
            else:
                policy_id = policy["id"]
            latest = cls.policy_repository.next_version(policy_id, txn)
            steps = []
            for step in normalized["steps"]:
                role = None
                if step.get("role_id"):
                    role = cls.role_repository.find_active_by_id(int(step["role_id"]), db=txn)
                if not role:
                    role = cls.role_repository.find_active_by_code(step["code"], db=txn)
                if not role:
                    raise ValidationError(f"角色“{step['code']}”不存在或已停用")
                steps.append({"level": step["level"], "role_id": role["id"], "code": role["code"], "name": role["name"]})
            revision_id = cls.policy_repository.create_revision(
                policy_id, latest + 1, normalized["require_approval"], normalized["approval_level"],
                idempotency_key, actor, steps, txn,
            )
            cls.policy_repository.insert_event(revision_id, "created", actor, {"policy_id": policy_id}, idempotency_key, txn)
            row = cls.policy_repository.find_revision(revision_id, db=txn)
            return dict(row)

    @classmethod
    def transition(cls, revision_id, target, actor):
        if not config.APPROVAL_POLICY_VERSIONED_WRITE_ENABLED:
            raise ConflictError("审批策略版本化写入尚未启用")
        if target not in {"pending_approval", "published", "rejected", "superseded"}:
            raise ValidationError("不支持的策略状态变更")
        with cls.unit_of_work.transaction() as txn:
            revision = cls.policy_repository.find_revision(revision_id, db=txn)
            if not revision:
                raise NotFoundError("审批策略修订版不存在")
            assert_transition(revision, target, actor.get("id"))
            if target == "published":
                if revision["status"] != "pending_approval":
                    raise ConflictError("只有待批准修订版可以发布")
                cls.policy_repository.supersede_published(revision["policy_id"], revision_id, db=txn)
            updated = cls.policy_repository.transition(revision_id, revision["status"], target, actor, txn)
            if updated != 1:
                raise ConflictError("策略状态已变化，请刷新后重试")
            if target == "published":
                cls.policy_repository.set_current_revision(revision["policy_id"], revision_id, db=txn)
            cls.policy_repository.insert_event(revision_id, target, actor, {}, f"{revision_id}:{target}", txn)
            return dict(cls.policy_repository.find_revision(revision_id, db=txn))

    @classmethod
    def effective_snapshot(cls, process_id, db=None, use_versioned=None):
        versioned = config.APPROVAL_POLICY_VERSIONED_QUERY_ENABLED if use_versioned is None else bool(use_versioned)
        if not versioned:
            legacy = ApprovalRepository.find_approval_config(process_id, db=db)
            if not legacy:
                return {"require_approval": False, "approval_level": 1, "roles": [], "source": "legacy_config"}, None
            data = dict(legacy)
            level = int(data.get("approval_level") or 1)
            roles = []
            for step_level, (role_id_key, role_code_key) in enumerate((
                ("approver_role_id", "approver_role"),
                ("approver_role_2_id", "approver_role_2"),
                ("approver_role_3_id", "approver_role_3"),
            )[:level], start=1):
                code = data.get(role_code_key) or ("admin" if step_level == 1 else "")
                if code:
                    roles.append({"level": step_level, "role_id": data.get(role_id_key), "code": code, "name": code})
            return {"require_approval": bool(data.get("require_approval")), "approval_level": level,
                    "roles": roles, "source": "legacy_config"}, None
        legacy_snapshot = None
        if config.APPROVAL_POLICY_COMPAT_AUDIT_ENABLED:
            legacy_snapshot, _ = cls.effective_snapshot(process_id, db=db, use_versioned=False)
        revision = cls.policy_repository.find_published_revision(process_id, db=db)
        if not revision:
            revision = cls.policy_repository.find_published_revision(None, db=db)
        if not revision:
            snapshot = {"require_approval": False, "approval_level": 1, "roles": [], "source": "default"}
            return snapshot, None
        steps = cls.policy_repository.list_steps(revision["id"], db=db)
        snapshot = {
            "policy_key": revision["policy_key"],
            "require_approval": bool(revision["require_approval"]),
            "approval_level": revision["approval_level"],
            "roles": [{"level": s["step_level"], "role_id": s["role_id"], "code": s["role_code_snapshot"], "name": s["role_name_snapshot"]} for s in steps],
            "source": "versioned",
        }
        if legacy_snapshot is not None and db is not None:
            def digest(value):
                comparable = dict(value)
                comparable.pop("source", None)
                return hashlib.sha256(json.dumps(comparable, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            legacy_digest = digest(legacy_snapshot)
            versioned_digest = digest(snapshot)
            cls.policy_repository.record_compat_audit(
                process_id,
                legacy_digest,
                versioned_digest,
                {
                    "legacy_source": legacy_snapshot.get("source"),
                    "versioned_revision_id": revision["id"],
                },
                db=db,
            )
        return snapshot, revision["id"]

    @classmethod
    def snapshot_for_revision(cls, revision_id, db=None):
        revision = cls.policy_repository.find_revision(revision_id, db=db)
        if not revision:
            raise NotFoundError("审批策略修订版不存在")
        steps = cls.policy_repository.list_steps(revision_id, db=db)
        return {
            "policy_key": revision["policy_key"],
            "require_approval": bool(revision["require_approval"]),
            "approval_level": revision["approval_level"],
            "roles": [
                {"level": step["step_level"], "role_id": step["role_id"],
                 "code": step["role_code_snapshot"], "name": step["role_name_snapshot"]}
                for step in steps
            ],
            "source": "bound_revision",
        }
