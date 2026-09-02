"""Database access for the singleton versioned company profile."""

import json

from modules.domain.company_profile import (
    COMPANY_PROFILE_FIELDS,
    COMPANY_PROFILE_RETENTION_YEARS,
)
from modules.repositories.context import resolve_db
from modules.audit_writer import insert_audit_log


class CompanyProfileRepository:
    @staticmethod
    def get(db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM company_profiles WHERE id=1").fetchone()

    @staticmethod
    def list_revisions(limit=100, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM company_profile_revisions "
            "WHERE profile_id=1 ORDER BY version DESC LIMIT ?",
            (limit,),
        ).fetchall()

    @staticmethod
    def update_txn(expected_version, values, actor, db):
        next_version = expected_version + 1
        result = db.execute(
            "UPDATE company_profiles SET company_name=?, contact=?, phone=?, address=?, "
            "description=?, version=?, updated_by=?, updated_by_name=?, "
            "updated_at=datetime('now','localtime') WHERE id=1 AND version=?",
            (
                *(values[field] for field in COMPANY_PROFILE_FIELDS),
                next_version,
                actor.get("id"),
                actor.get("name") or actor.get("username") or "",
                expected_version,
            ),
        )
        return result.rowcount == 1

    @staticmethod
    def insert_revision_txn(profile, changed_fields, actor, db):
        db.execute(
            "INSERT INTO company_profile_revisions "
            "(profile_id, company_name, contact, phone, address, description, version, "
            "changed_fields, actor_user_id, actor_name, created_at) "
            "VALUES (1,?,?,?,?,?,?,?,?,?,?)",
            (
                *(profile[field] for field in COMPANY_PROFILE_FIELDS),
                profile["version"],
                json.dumps(changed_fields, ensure_ascii=False),
                actor.get("id"),
                actor.get("name") or actor.get("username") or "",
                profile["updated_at"],
            ),
        )

    @staticmethod
    def update_legacy_mirrors_txn(profile, db):
        for field in COMPANY_PROFILE_FIELDS:
            db.execute(
                "INSERT INTO system_settings (key, value, updated_at) "
                "VALUES (?,?,datetime('now','localtime')) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value, updated_at=excluded.updated_at",
                (field, profile[field]),
            )

    @staticmethod
    def insert_audit_txn(profile, changed_fields, actor, db):
        detail = json.dumps(
            {
                "version": profile["version"],
                "changed_fields": changed_fields,
                "actor_name": actor.get("name") or actor.get("username") or "",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        insert_audit_log(
            db,
            actor.get("id"),
            "company_profile_update",
            "company_profile",
            1,
            detail,
        )

    @staticmethod
    def prune_expired_revisions_txn(db):
        return db.execute(
            "DELETE FROM company_profile_revisions "
            "WHERE profile_id=1 "
            "AND created_at < datetime('now','localtime',?) "
            "AND version <> (SELECT version FROM company_profiles WHERE id=1)",
            (f"-{COMPANY_PROFILE_RETENTION_YEARS} years",),
        ).rowcount
