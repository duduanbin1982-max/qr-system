"""Evidence-backed performance improvement plan workflow."""

from contextlib import contextmanager
from datetime import datetime
import json

from modules.domain.errors import ConflictError, NotFoundError
from modules.domain.performance_policy import validate_production_month
from modules.repositories.performance_improvement_repository import (
    PerformanceImprovementRepository,
)
from modules.services import BaseService
from modules.services.performance_authorization_service import (
    PerformanceAuthorizationService,
)


class PerformanceImprovementService:
    VALID_STATUSES = {
        "draft",
        "active",
        "reassessment_pending",
        "closed",
        "cancelled",
    }
    TRANSITIONS = {
        "draft": {"active", "cancelled"},
        "active": {"reassessment_pending", "cancelled"},
        "reassessment_pending": {"active", "closed"},
        "closed": set(),
        "cancelled": set(),
    }

    @staticmethod
    @contextmanager
    def _transaction():
        db = BaseService.db()
        if not db.in_transaction:
            with BaseService.transaction() as txn:
                yield txn
            return

        savepoint = "performance_improvement_workflow"
        db.execute("SAVEPOINT " + savepoint)
        try:
            yield db
            db.execute("RELEASE SAVEPOINT " + savepoint)
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT " + savepoint)
            db.execute("RELEASE SAVEPOINT " + savepoint)
            raise

    @staticmethod
    def _canonical(value):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @staticmethod
    def _json_object(value):
        if isinstance(value, dict):
            return dict(value)
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ConflictError("绩效改进计划事件数据无效") from exc
        if not isinstance(parsed, dict):
            raise ConflictError("绩效改进计划事件数据无效")
        return parsed

    @staticmethod
    def _actor_identity(actor, label="绩效改进计划操作人"):
        actor_id = (actor or {}).get("id")
        if actor_id is None:
            raise PermissionError(label + "不存在")
        return int(actor_id), str(
            (actor or {}).get("name") or (actor or {}).get("username") or ""
        )

    @classmethod
    def _require_manager(cls, actor):
        if not PerformanceAuthorizationService.can_perform(actor, "plan_manage"):
            raise PermissionError("performance:plan_manage permission is required")
        return cls._actor_identity(actor)

    @classmethod
    def _require_reassessor(cls, actor):
        if not PerformanceAuthorizationService.can_perform(actor, "plan_reassess"):
            raise PermissionError("performance:plan_reassess permission is required")
        return cls._actor_identity(actor, "绩效改进计划复评人")

    @staticmethod
    def _idempotency_key(data, label):
        key = str((data or {}).get("idempotency_key") or "").strip()
        if not key:
            raise ValueError(label + "幂等键不能为空")
        if len(key) > 200:
            raise ValueError(label + "幂等键过长")
        return key

    @classmethod
    def _command(cls, data, label):
        if not isinstance(data, dict):
            raise ValueError(label + "参数无效")
        row_version = data.get("row_version")
        if row_version in (None, ""):
            row_version = data.get("expected_row_version")
        try:
            row_version = int(row_version)
        except (TypeError, ValueError) as exc:
            raise ValueError(label + "缺少有效的 row_version") from exc
        if row_version < 1:
            raise ValueError(label + "row_version 无效")
        return {
            "row_version": row_version,
            "idempotency_key": cls._idempotency_key(data, label),
        }

    @staticmethod
    def _positive_id(value, label):
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(label + "无效") from exc
        if result <= 0:
            raise ValueError(label + "无效")
        return result

    @staticmethod
    def _date(value, label):
        text = str(value or "").strip()
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(label + "格式必须为 YYYY-MM-DD") from exc
        if parsed.strftime("%Y-%m-%d") != text:
            raise ValueError(label + "格式必须为 YYYY-MM-DD")
        return text

    @staticmethod
    def _require_plan(plan_id, db):
        plan = PerformanceImprovementRepository.plan(plan_id, db=db)
        if not plan:
            raise NotFoundError("绩效改进计划不存在")
        return plan

    @staticmethod
    def _require_version(plan, expected):
        if int(plan["row_version"]) != int(expected):
            raise ConflictError("绩效改进计划版本号已变化，请刷新后重试")

    @staticmethod
    def _event_key(action, key):
        return "performance-plan-" + action + ":" + key

    @classmethod
    def _creation_replay(
        cls, event, actor_id, user_id, production_month, db
    ):
        if int(event.get("operator_id") or 0) != int(actor_id):
            raise PermissionError("绩效改进计划幂等请求只能由原操作人重试")
        result = PerformanceImprovementRepository.plan_summary(
            event["plan_id"], db=db
        )
        if not result:
            raise NotFoundError("绩效改进计划不存在")
        plan = result["plan"]
        if (
            int(plan["user_id"]) != int(user_id)
            or plan["production_month"] != production_month
        ):
            raise ConflictError("同一幂等键不能用于其他员工或生产月份")
        result.update({"event_id": event["id"], "idempotent_replay": True})
        return result

    @classmethod
    def _event_replay(
        cls,
        plan_id,
        actor_id,
        event_key,
        db,
        *,
        target_status=None,
    ):
        event = PerformanceImprovementRepository.event_by_idempotency_key(
            event_key, db=db
        )
        if not event:
            return None
        if int(event.get("plan_id") or 0) != int(plan_id):
            raise ConflictError("同一幂等键不能用于其他绩效改进计划")
        if int(event.get("operator_id") or 0) != int(actor_id):
            raise PermissionError("绩效改进计划幂等请求只能由原操作人重试")
        if target_status and event.get("to_status") != target_status:
            raise ConflictError("同一幂等键不能用于不同状态转换")
        result = PerformanceImprovementRepository.plan_summary(plan_id, db=db)
        if not result:
            raise NotFoundError("绩效改进计划不存在")
        payload = cls._json_object(event.get("payload_json"))
        result.update(payload.get("result") or {})
        result.update({"event_id": event["id"], "idempotent_replay": True})
        return result

    @classmethod
    def create_plan(cls, data, actor, db=None):
        if not isinstance(data, dict):
            raise ValueError("绩效改进计划参数无效")
        actor_id, actor_name = cls._require_manager(actor)
        user_id = cls._positive_id(data.get("user_id"), "绩效改进员工")
        production_month = validate_production_month(data.get("production_month"))
        client_key = cls._idempotency_key(data, "绩效改进计划创建")
        event_key = cls._event_key("create", client_key)

        owner_id = data.get("owner_id")
        if owner_id not in (None, ""):
            owner_id = cls._positive_id(owner_id, "绩效改进负责人")
        else:
            owner_id = None
        score_revision_id = data.get("score_revision_id")
        if score_revision_id not in (None, ""):
            score_revision_id = cls._positive_id(
                score_revision_id, "绩效评分修订版"
            )
        else:
            score_revision_id = None

        def execute(txn):
            employee = PerformanceImprovementRepository.user_snapshot(user_id, db=txn)
            if not employee:
                raise NotFoundError("绩效改进员工不存在")
            owner = None
            if owner_id is not None:
                owner = PerformanceImprovementRepository.user_snapshot(
                    owner_id, db=txn
                )
                if not owner:
                    raise NotFoundError("绩效改进负责人不存在")
            score = None
            if score_revision_id is not None:
                score = PerformanceImprovementRepository.score_revision(
                    score_revision_id, db=txn
                )
                if not score:
                    raise NotFoundError("绩效评分修订版不存在")
                if int(score["user_id"]) != user_id:
                    raise ConflictError("绩效评分修订版不属于计划员工")
                if score["batch_production_month"] != production_month:
                    raise ConflictError("绩效评分修订版不属于计划生产月份")

            created_at = PerformanceImprovementRepository.database_now(db=txn)
            plan_id = PerformanceImprovementRepository.insert_plan(
                {
                    "score_revision_id": score_revision_id,
                    "user_id": user_id,
                    "employee_name_snapshot": employee["employee_name_snapshot"],
                    "employee_no_snapshot": employee["employee_no_snapshot"],
                    "department_id_snapshot": employee["department_id_snapshot"],
                    "department_name_snapshot": employee[
                        "department_name_snapshot"
                    ],
                    "production_month": production_month,
                    "warning_level_snapshot": str(
                        data.get("warning_level")
                        or (score or {}).get("warning_level")
                        or ""
                    ).strip(),
                    "reason": str(data.get("reason") or "").strip(),
                    "goal": str(data.get("goal") or "").strip(),
                    "actions": str(data.get("actions") or "").strip(),
                    "owner_id": owner_id,
                    "owner_name_snapshot": (
                        owner["employee_name_snapshot"] if owner else ""
                    ),
                    "due_date": str(data.get("due_date") or "").strip(),
                    "created_by": actor_id,
                    "created_by_name": actor_name,
                    "created_at": created_at,
                    "updated_at": created_at,
                },
                txn,
            )
            event_id = PerformanceImprovementRepository.insert_event(
                {
                    "plan_id": plan_id,
                    "event_type": "plan_created",
                    "from_status": "",
                    "to_status": "draft",
                    "reassessment_round": 0,
                    "operator_id": actor_id,
                    "operator_name": actor_name,
                    "reason": str(data.get("reason") or "").strip(),
                    "payload_json": cls._canonical(
                        {
                            "production_month": production_month,
                            "user_id": user_id,
                        }
                    ),
                    "idempotency_key": event_key,
                    "created_at": created_at,
                },
                txn,
            )
            result = PerformanceImprovementRepository.plan_summary(plan_id, db=txn)
            result.update({"event_id": event_id, "idempotent_replay": False})
            return result

        if db is not None:
            # Creation replay needs the event's plan id, which is not known to callers.
            event = PerformanceImprovementRepository.event_by_idempotency_key(
                event_key, db=db
            )
            if event:
                return cls._creation_replay(
                    event, actor_id, user_id, production_month, db
                )
            return execute(db)
        with cls._transaction() as txn:
            event = PerformanceImprovementRepository.event_by_idempotency_key(
                event_key, db=txn
            )
            if event:
                return cls._creation_replay(
                    event, actor_id, user_id, production_month, txn
                )
            return execute(txn)

    @classmethod
    def transition(cls, plan_id, data, actor, db=None):
        actor_id, actor_name = cls._require_manager(actor)
        command = cls._command(data, "绩效改进计划状态转换")
        target_status = str((data or {}).get("target_status") or "").strip()
        if target_status not in cls.VALID_STATUSES:
            raise ConflictError("绩效改进计划目标状态无效")
        event_key = cls._event_key("transition", command["idempotency_key"])

        def execute(txn):
            replay = cls._event_replay(
                plan_id,
                actor_id,
                event_key,
                txn,
                target_status=target_status,
            )
            if replay:
                return replay
            plan = cls._require_plan(plan_id, txn)
            current_status = plan["status"]
            if target_status not in cls.TRANSITIONS[current_status]:
                raise ConflictError(
                    "当前状态不允许转换为 " + target_status
                )
            cls._require_version(plan, command["row_version"])
            now = PerformanceImprovementRepository.database_now(db=txn)
            fields = {}
            reason = str((data or {}).get("reason") or "").strip()

            if current_status == "draft" and target_status == "active":
                merged = {
                    "reason": str(
                        data.get("reason")
                        if "reason" in data
                        else plan.get("reason") or ""
                    ).strip(),
                    "goal": str(
                        data.get("goal")
                        if "goal" in data
                        else plan.get("goal") or ""
                    ).strip(),
                    "actions": str(
                        data.get("actions")
                        if "actions" in data
                        else plan.get("actions") or ""
                    ).strip(),
                    "owner_id": (
                        data.get("owner_id")
                        if "owner_id" in data
                        else plan.get("owner_id")
                    ),
                    "due_date": str(
                        data.get("due_date")
                        if "due_date" in data
                        else plan.get("due_date") or ""
                    ).strip(),
                }
                missing = []
                for field, label in (
                    ("reason", "问题依据"),
                    ("goal", "可衡量目标"),
                    ("actions", "行动措施"),
                    ("owner_id", "负责人"),
                    ("due_date", "截止日期"),
                ):
                    if not merged[field]:
                        missing.append(label)
                if missing:
                    raise ValueError("激活绩效改进计划前必须填写：" + "、".join(missing))
                owner_id = cls._positive_id(merged["owner_id"], "绩效改进负责人")
                owner = PerformanceImprovementRepository.user_snapshot(
                    owner_id, db=txn
                )
                if not owner:
                    raise NotFoundError("绩效改进负责人不存在")
                fields = {
                    "reason": merged["reason"],
                    "goal": merged["goal"],
                    "actions": merged["actions"],
                    "owner_id": owner_id,
                    "owner_name_snapshot": owner["employee_name_snapshot"],
                    "due_date": cls._date(merged["due_date"], "截止日期"),
                }
                reason = merged["reason"]
                event_type = "plan_activated"
            elif current_status == "active" and target_status == "reassessment_pending":
                evidence = PerformanceImprovementRepository.list_evidence(
                    plan_id,
                    reassessment_round=plan["reassessment_round"],
                    db=txn,
                )
                if not evidence:
                    raise ConflictError("当前复评轮次尚无改进证据，不能申请复评")
                event_type = "reassessment_requested"
            elif target_status == "cancelled":
                if not reason:
                    raise ValueError("取消绩效改进计划必须填写原因")
                fields = {
                    "cancelled_at": now,
                    "cancellation_reason": reason,
                }
                event_type = "plan_cancelled"
            else:
                raise ConflictError("该状态转换必须通过独立复评命令执行")

            if not PerformanceImprovementRepository.transition_plan(
                plan_id,
                command["row_version"],
                current_status,
                target_status,
                fields,
                txn,
            ):
                raise ConflictError("绩效改进计划版本号已变化，请刷新后重试")
            event_id = PerformanceImprovementRepository.insert_event(
                {
                    "plan_id": plan_id,
                    "event_type": event_type,
                    "from_status": current_status,
                    "to_status": target_status,
                    "reassessment_round": plan["reassessment_round"],
                    "operator_id": actor_id,
                    "operator_name": actor_name,
                    "reason": reason,
                    "payload_json": cls._canonical({"fields": fields}),
                    "idempotency_key": event_key,
                    "created_at": now,
                },
                txn,
            )
            result = PerformanceImprovementRepository.plan_summary(plan_id, db=txn)
            result.update({"event_id": event_id, "idempotent_replay": False})
            return result

        if db is not None:
            return execute(db)
        with cls._transaction() as txn:
            return execute(txn)

    @classmethod
    def add_evidence(cls, plan_id, data, actor, db=None):
        actor_id, actor_name = cls._require_manager(actor)
        command = cls._command(data, "绩效改进证据提交")
        evidence_type = str((data or {}).get("evidence_type") or "note").strip()
        description = str((data or {}).get("description") or "").strip()
        file_name = str((data or {}).get("file_name") or "").strip()
        file_path = str((data or {}).get("file_path") or "").strip()
        source_url = str((data or {}).get("source_url") or "").strip()
        if not evidence_type:
            raise ValueError("证据类型不能为空")
        if not any((description, file_name, file_path, source_url)):
            raise ValueError("证据说明、文件或来源链接至少填写一项")
        event_key = cls._event_key("evidence", command["idempotency_key"])

        def execute(txn):
            replay = cls._event_replay(plan_id, actor_id, event_key, txn)
            if replay:
                return replay
            plan = cls._require_plan(plan_id, txn)
            if plan["status"] != "active":
                raise ConflictError("只有执行中的绩效改进计划可以追加证据")
            cls._require_version(plan, command["row_version"])
            evidence_id = PerformanceImprovementRepository.insert_evidence(
                {
                    "plan_id": plan_id,
                    "reassessment_round": plan["reassessment_round"],
                    "evidence_type": evidence_type,
                    "description": description,
                    "file_name": file_name,
                    "file_path": file_path,
                    "source_url": source_url,
                    "submitted_by": actor_id,
                    "submitted_by_name": actor_name,
                },
                txn,
            )
            if not PerformanceImprovementRepository.transition_plan(
                plan_id,
                command["row_version"],
                "active",
                "active",
                {},
                txn,
            ):
                raise ConflictError("绩效改进计划版本号已变化，请刷新后重试")
            now = PerformanceImprovementRepository.database_now(db=txn)
            event_id = PerformanceImprovementRepository.insert_event(
                {
                    "plan_id": plan_id,
                    "event_type": "evidence_added",
                    "from_status": "active",
                    "to_status": "active",
                    "reassessment_round": plan["reassessment_round"],
                    "operator_id": actor_id,
                    "operator_name": actor_name,
                    "reason": description,
                    "payload_json": cls._canonical(
                        {"result": {"evidence_id": evidence_id}}
                    ),
                    "idempotency_key": event_key,
                    "created_at": now,
                },
                txn,
            )
            result = PerformanceImprovementRepository.plan_summary(plan_id, db=txn)
            result.update(
                {
                    "evidence_id": evidence_id,
                    "event_id": event_id,
                    "idempotent_replay": False,
                }
            )
            return result

        if db is not None:
            return execute(db)
        with cls._transaction() as txn:
            return execute(txn)

    @classmethod
    def reassess(cls, plan_id, data, actor, db=None):
        actor_id, actor_name = cls._require_reassessor(actor)
        command = cls._command(data, "绩效改进计划复评")
        result_value = str((data or {}).get("result") or "").strip()
        if result_value not in {"passed", "failed"}:
            raise ValueError("复评结论必须为 passed 或 failed")
        notes = str((data or {}).get("notes") or "").strip()
        if not notes:
            raise ValueError("复评说明不能为空")
        raw_evidence_ids = (data or {}).get("evidence_ids")
        if not isinstance(raw_evidence_ids, list) or not raw_evidence_ids:
            raise ValueError("复评必须引用至少一项证据")
        try:
            evidence_ids = sorted({int(value) for value in raw_evidence_ids})
        except (TypeError, ValueError) as exc:
            raise ValueError("复评证据 ID 无效") from exc
        if any(value <= 0 for value in evidence_ids):
            raise ValueError("复评证据 ID 无效")
        new_actions = str((data or {}).get("new_actions") or "").strip()
        new_due_date = str((data or {}).get("new_due_date") or "").strip()
        if result_value == "failed":
            missing = []
            if not new_actions:
                missing.append("新措施")
            if not new_due_date:
                missing.append("新截止日期")
            if missing:
                raise ValueError("复评不通过必须填写：" + "、".join(missing))
            new_due_date = cls._date(new_due_date, "新截止日期")
        reassessment_key = cls._event_key(
            "reassessment", command["idempotency_key"]
        )

        def replay(existing, txn):
            if int(existing.get("plan_id") or 0) != int(plan_id):
                raise ConflictError("同一复评幂等键不能用于其他绩效改进计划")
            if int(existing.get("reassessed_by") or 0) != actor_id:
                raise PermissionError("绩效改进复评幂等请求只能由原复评人重试")
            if existing.get("result") != result_value:
                raise ConflictError("同一复评幂等键不能用于不同复评结论")
            summary = PerformanceImprovementRepository.plan_summary(plan_id, db=txn)
            event = PerformanceImprovementRepository.event_by_idempotency_key(
                reassessment_key, db=txn
            )
            summary.update(
                {
                    "reassessment_id": existing["id"],
                    "reassessment": existing,
                    "event_id": event["id"] if event else None,
                    "idempotent_replay": True,
                }
            )
            return summary

        def execute(txn):
            existing = PerformanceImprovementRepository.reassessment_by_idempotency_key(
                reassessment_key, db=txn
            )
            if existing:
                return replay(existing, txn)
            plan = cls._require_plan(plan_id, txn)
            if plan.get("owner_id") is not None and int(plan["owner_id"]) == actor_id:
                raise PermissionError("绩效改进计划负责人不能复评自己的计划")
            if plan["status"] != "reassessment_pending":
                raise ConflictError("只有待复评的绩效改进计划可以执行复评")
            cls._require_version(plan, command["row_version"])
            reassessment_round = int(plan["reassessment_round"])
            duplicate = PerformanceImprovementRepository.reassessment_by_round(
                plan_id, reassessment_round, db=txn
            )
            if duplicate:
                raise ConflictError("当前轮次已经完成复评，不能重复复评")
            evidence = [
                PerformanceImprovementRepository.evidence(evidence_id, db=txn)
                for evidence_id in evidence_ids
            ]
            if any(item is None for item in evidence) or any(
                int(item["plan_id"]) != int(plan_id)
                or int(item["reassessment_round"]) != reassessment_round
                for item in evidence
            ):
                raise ConflictError("复评只能引用本计划当前轮次的证据")

            now = PerformanceImprovementRepository.database_now(db=txn)
            reassessment_id = PerformanceImprovementRepository.insert_reassessment(
                {
                    "plan_id": plan_id,
                    "reassessment_round": reassessment_round,
                    "result": result_value,
                    "notes": notes,
                    "evidence_ids_json": cls._canonical(evidence_ids),
                    "reassessed_by": actor_id,
                    "reassessed_by_name": actor_name,
                    "reassessed_at": now,
                    "idempotency_key": reassessment_key,
                },
                txn,
            )
            if result_value == "passed":
                target_status = "closed"
                fields = {"closed_at": now}
                event_type = "reassessment_passed"
            else:
                target_status = "active"
                fields = {
                    "actions": new_actions,
                    "due_date": new_due_date,
                    "reassessment_round": reassessment_round + 1,
                }
                event_type = "reassessment_failed"
            if not PerformanceImprovementRepository.transition_plan(
                plan_id,
                command["row_version"],
                "reassessment_pending",
                target_status,
                fields,
                txn,
            ):
                raise ConflictError("绩效改进计划版本号已变化，请刷新后重试")
            event_id = PerformanceImprovementRepository.insert_event(
                {
                    "plan_id": plan_id,
                    "event_type": event_type,
                    "from_status": "reassessment_pending",
                    "to_status": target_status,
                    "reassessment_round": reassessment_round,
                    "operator_id": actor_id,
                    "operator_name": actor_name,
                    "reason": notes,
                    "payload_json": cls._canonical(
                        {
                            "result": {
                                "reassessment_id": reassessment_id,
                                "reassessment_result": result_value,
                            },
                            "evidence_ids": evidence_ids,
                            "next_round": fields.get(
                                "reassessment_round", reassessment_round
                            ),
                        }
                    ),
                    "idempotency_key": reassessment_key,
                    "created_at": now,
                },
                txn,
            )
            summary = PerformanceImprovementRepository.plan_summary(plan_id, db=txn)
            summary.update(
                {
                    "reassessment_id": reassessment_id,
                    "reassessment": PerformanceImprovementRepository.reassessment(
                        reassessment_id, db=txn
                    ),
                    "event_id": event_id,
                    "idempotent_replay": False,
                }
            )
            return summary

        if db is not None:
            return execute(db)
        with cls._transaction() as txn:
            return execute(txn)

    @classmethod
    def list_plans(cls, filters, actor, db=None):
        cls._require_view_permission(actor)
        scope = PerformanceAuthorizationService.resolve_view_scope(actor, db=db)
        return {
            "plans": PerformanceImprovementRepository.list_plans(
                filters=filters or {}, scope=scope, db=db
            )
        }

    @classmethod
    def get_plan(cls, plan_id, actor, db=None):
        cls._require_view_permission(actor)
        summary = PerformanceImprovementRepository.plan_summary(plan_id, db=db)
        if not summary:
            raise NotFoundError("绩效改进计划不存在")
        scope = PerformanceAuthorizationService.resolve_view_scope(actor, db=db)
        plan = summary["plan"]
        visible = scope["all"]
        if not visible and scope.get("self_user_id") is not None:
            visible = int(plan["user_id"]) == int(scope["self_user_id"])
        if not visible and plan.get("department_id_snapshot") is not None:
            visible = int(plan["department_id_snapshot"]) in {
                int(value) for value in scope.get("department_ids", [])
            }
        if not visible:
            raise NotFoundError("绩效改进计划不存在")
        return summary

    @staticmethod
    def _require_view_permission(actor):
        if not any(
            PerformanceAuthorizationService.can_perform(actor, action)
            for action in ("view_self", "view_department", "view_all")
        ):
            raise PermissionError("无绩效改进计划查看权限")
