"""Pure approval policy lifecycle rules."""

from modules.domain.errors import ConflictError, ValidationError


POLICY_STATUSES = {"draft", "pending_approval", "published", "superseded", "rejected", "retired"}


def validate_policy_payload(payload):
    try:
        level = int(payload.get("approval_level", 1))
    except (TypeError, ValueError) as exc:
        raise ValidationError("审批级别必须是整数") from exc
    if level < 1 or level > 3:
        raise ValidationError("审批级别必须为 1 到 3 级")
    require = 1 if payload.get("require_approval") else 0
    steps = payload.get("steps") or []
    if require and len(steps) != level:
        raise ValidationError("审批角色数量必须与审批级别一致")
    if not require:
        steps = []
    seen = set()
    normalized = []
    for index, step in enumerate(steps, start=1):
        code = str(step.get("code") or "").strip().lower()
        if not code:
            raise ValidationError("审批角色编码不能为空")
        if code in seen:
            raise ValidationError("各级审批角色不能重复")
        seen.add(code)
        normalized.append({
            "level": index,
            "role_id": step.get("role_id"),
            "code": code,
            "name": str(step.get("name") or code),
        })
    return {"require_approval": require, "approval_level": level, "steps": normalized}


def assert_transition(revision, target, actor_id=None):
    current = revision.get("status") if hasattr(revision, "get") else revision["status"]
    allowed = {
        "draft": {"pending_approval", "rejected"},
        "pending_approval": {"published", "rejected"},
        "published": {"superseded"},
        "superseded": set(),
        "rejected": {"draft"},
        "retired": set(),
    }
    if target not in allowed.get(current, set()):
        raise ConflictError(f"修订版状态 {current} 不允许变更为 {target}")
    created_by = revision.get("created_by") if hasattr(revision, "get") else revision["created_by"]
    if target == "published" and actor_id is not None and created_by == actor_id:
        raise ConflictError("制单人不能批准或发布本人创建的审批策略")
