"""Versioned department supplements for immutable performance assignments."""


def m057_performance_assignment_department_revisions(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS performance_assignment_department_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            department_id INTEGER NOT NULL,
            department_name_snapshot TEXT NOT NULL,
            valid_from_snapshot TEXT NOT NULL,
            valid_to_snapshot TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft','approved','superseded','cancelled')),
            reason TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'manual_confirmation',
            source_key TEXT NOT NULL UNIQUE,
            created_by INTEGER NOT NULL,
            created_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            approved_at TEXT NOT NULL DEFAULT '',
            supersedes_revision_id INTEGER,
            superseded_by_revision_id INTEGER,
            row_version INTEGER NOT NULL DEFAULT 1,
            UNIQUE(assignment_id, revision),
            FOREIGN KEY (assignment_id) REFERENCES performance_assignment_history(id) ON DELETE RESTRICT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT,
            FOREIGN KEY (approved_by) REFERENCES users(id) ON DELETE RESTRICT,
            FOREIGN KEY (supersedes_revision_id) REFERENCES performance_assignment_department_revisions(id) ON DELETE RESTRICT,
            FOREIGN KEY (superseded_by_revision_id) REFERENCES performance_assignment_department_revisions(id) ON DELETE RESTRICT
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_perf_assignment_department_revision "
        "ON performance_assignment_department_revisions(assignment_id,revision)"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_perf_assignment_department_current "
        "ON performance_assignment_department_revisions(assignment_id) "
        "WHERE status='approved'"
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS prevent_perf_assignment_department_delete
        BEFORE DELETE ON performance_assignment_department_revisions
        BEGIN
            SELECT RAISE(ABORT,'performance assignment department revisions are immutable');
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS protect_perf_assignment_department_content
        BEFORE UPDATE OF assignment_id,revision,user_id,department_id,
            department_name_snapshot,valid_from_snapshot,valid_to_snapshot,
            reason,source_type,source_key,created_by,created_by_name,created_at
        ON performance_assignment_department_revisions
        WHEN OLD.status<>'draft'
        BEGIN
            SELECT RAISE(ABORT,'approved performance assignment department revisions are immutable');
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS prevent_invalid_perf_assignment_department_transition
        BEFORE UPDATE OF status ON performance_assignment_department_revisions
        WHEN NOT (
            (OLD.status='draft' AND NEW.status IN ('draft','approved','cancelled')) OR
            (OLD.status='approved' AND NEW.status IN ('approved','superseded')) OR
            (OLD.status='superseded' AND NEW.status='superseded') OR
            (OLD.status='cancelled' AND NEW.status='cancelled')
        )
        BEGIN
            SELECT RAISE(ABORT,'invalid performance assignment department revision transition');
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS prevent_same_perf_assignment_department_actors
        BEFORE UPDATE OF status ON performance_assignment_department_revisions
        WHEN NEW.status='approved' AND NEW.created_by=NEW.approved_by
        BEGIN
            SELECT RAISE(ABORT,'performance assignment department preparer and approver must differ');
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS require_perf_assignment_department_approval_actor
        BEFORE UPDATE OF status ON performance_assignment_department_revisions
        WHEN NEW.status='approved' AND (
            NEW.approved_by IS NULL OR NEW.approved_by_name='' OR NEW.approved_at=''
        )
        BEGIN
            SELECT RAISE(ABORT,'performance assignment department approval actor is required');
        END
        """
    )


MIGRATIONS = [
    (
        57,
        "Add versioned performance assignment department supplements",
        m057_performance_assignment_department_revisions,
    ),
]
