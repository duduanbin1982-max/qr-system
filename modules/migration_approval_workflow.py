"""Approval workflow audit trail migration."""


def m044_approval_workflow_audit_trail(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            approval_record_id INTEGER NOT NULL,
            step_level INTEGER NOT NULL,
            approver_id INTEGER,
            approver_name TEXT NOT NULL,
            approver_role TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            comment TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (approval_record_id) REFERENCES approval_records(id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_steps_record_id ON approval_steps(approval_record_id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_steps_created_at ON approval_steps(created_at)"
    )
    db.execute(
        """
        INSERT INTO approval_steps (
            approval_record_id, step_level, approver_id, approver_name,
            approver_role, action, comment, created_at
        )
        SELECT
            ar.id,
            CASE
                WHEN ar.status = 'pending' AND COALESCE(ar.current_level, 1) > 1
                    THEN ar.current_level - 1
                ELSE COALESCE(ar.current_level, 1)
            END,
            ar.approver_id,
            COALESCE(ar.approver_name, ''),
            '',
            CASE
                WHEN ar.status = 'approved' THEN 'approve'
                WHEN ar.status = 'rejected' THEN 'reject'
                ELSE 'advance'
            END,
            COALESCE(ar.comment, ''),
            COALESCE(ar.processed_at, ar.created_at)
        FROM approval_records ar
        WHERE ar.processed_at IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM approval_steps s WHERE s.approval_record_id = ar.id
          )
        """
    )


MIGRATIONS = [
    (44, 'approval workflow audit trail', m044_approval_workflow_audit_trail),
]
