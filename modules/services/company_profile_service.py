"""Application service for scoped, versioned company-profile access."""

import json

from modules.domain.company_profile import (
    COMPANY_PROFILE_FIELDS,
    CompanyProfileStaleError,
    changed_company_profile_fields,
    normalize_company_profile_changes,
    redact_company_profile_revision,
)
from modules.domain.errors import ValidationError
from modules.repositories.company_profile_repository import CompanyProfileRepository
from modules.services import BaseService


def _profile_dict(row):
    return {
        **{field: row[field] or "" for field in COMPANY_PROFILE_FIELDS},
        "version": row["version"],
        "updated_by": row["updated_by"],
        "updated_by_name": row["updated_by_name"] or "",
        "updated_at": row["updated_at"],
    }


class CompanyProfileService:
    @staticmethod
    def get_profile():
        row = CompanyProfileRepository.get()
        if not row:
            raise RuntimeError("公司资料尚未初始化")
        return _profile_dict(row)

    @staticmethod
    def get_public_profile():
        row = CompanyProfileRepository.get()
        return {"company_name": row["company_name"] if row else ""}

    @staticmethod
    def list_revisions(*, allow_sensitive_history=False, limit=100):
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ValidationError("历史记录条数必须是整数")
        limit = max(1, min(limit, 200))
        revisions = []
        for row in CompanyProfileRepository.list_revisions(limit=limit):
            revision = {
                **{field: row[field] or "" for field in COMPANY_PROFILE_FIELDS},
                "id": row["id"],
                "profile_id": row["profile_id"],
                "version": row["version"],
                "changed_fields": json.loads(row["changed_fields"] or "[]"),
                "actor_user_id": row["actor_user_id"],
                "actor_name": row["actor_name"] or "",
                "created_at": row["created_at"],
            }
            revisions.append(
                redact_company_profile_revision(revision, allow_sensitive_history)
            )
        return {"revisions": revisions, "sensitive_history_visible": allow_sensitive_history}

    @staticmethod
    def update_profile(changes, expected_version, actor):
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise ValidationError("version 必须是整数")
        if expected_version < 1:
            raise ValidationError("version 必须大于 0")
        normalized = normalize_company_profile_changes(changes)
        if not normalized:
            raise ValidationError("至少提交一个公司资料字段")

        with BaseService.transaction() as db:
            current_row = CompanyProfileRepository.get(db=db)
            current = _profile_dict(current_row)
            if current["version"] != expected_version:
                raise CompanyProfileStaleError(
                    "公司资料已被其他用户更新，请刷新后重试",
                    details={
                        "expected_version": expected_version,
                        "current_version": current["version"],
                    },
                )
            changed_fields = changed_company_profile_fields(current, normalized)
            if not changed_fields:
                return {"profile": current, "changed": False}

            updated = {**current, **normalized}
            if not CompanyProfileRepository.update_txn(
                expected_version, updated, actor, db
            ):
                latest = CompanyProfileRepository.get(db=db)
                raise CompanyProfileStaleError(
                    "公司资料已被其他用户更新，请刷新后重试",
                    details={
                        "expected_version": expected_version,
                        "current_version": latest["version"] if latest else None,
                    },
                )
            saved = _profile_dict(CompanyProfileRepository.get(db=db))
            CompanyProfileRepository.insert_revision_txn(
                saved, changed_fields, actor, db
            )
            CompanyProfileRepository.update_legacy_mirrors_txn(saved, db)
            CompanyProfileRepository.insert_audit_txn(
                saved, changed_fields, actor, db
            )
            CompanyProfileRepository.prune_expired_revisions_txn(db)

        from modules.setting_reader import clear_settings_cache

        clear_settings_cache()
        return {"profile": saved, "changed": True}
