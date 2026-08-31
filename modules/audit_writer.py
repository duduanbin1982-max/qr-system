"""Low-level audit insertion port shared by transactional repositories."""

import uuid

from modules.audit_action_catalog import describe_action
from modules.audit_policy import sanitize_audit_detail


def insert_audit_log(
    db,
    user_id,
    action,
    target_type="",
    target_id=0,
    detail="",
    *,
    event_id=None,
    request_id="",
):
    metadata = describe_action(action)
    cursor = db.execute(
        "INSERT INTO audit_logs "
        "(event_id,user_id,action,target_type,target_id,detail,category,severity,"
        "mandatory,schema_version,redaction_version,request_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            event_id or uuid.uuid4().hex,
            user_id,
            action,
            target_type,
            target_id,
            sanitize_audit_detail(detail),
            metadata.category,
            metadata.severity,
            int(metadata.mandatory),
            1,
            1,
            request_id or "",
        ),
    )
    return cursor.lastrowid
