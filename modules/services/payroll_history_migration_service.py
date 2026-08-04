"""Controlled migration of historical work records into the payroll ledger."""

from datetime import datetime
import hashlib
import json

from modules.domain.reporting_day import reporting_month_bounds
from modules.repositories.payroll_repository import PayrollRepository
from modules.repositories.payroll_history_migration_repository import (
    PayrollHistoryMigrationRepository,
)
from modules.services.payroll_service import PayrollCalculationService


POLICY_CODE = "current_price_migration_v1"
MANIFEST_FORMAT = "payroll_migration_manifest_v1"


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class PayrollHistoryMigrationService:
    @staticmethod
    def _require_schema(db):
        required = {
            "route_price_versions",
            "payroll_batches",
            "payroll_work_price_resolutions",
            "payroll_exceptions",
            "payroll_migration_manifests",
        }
        tables = PayrollHistoryMigrationRepository.table_names(db)
        missing = sorted(required - tables)
        if missing:
            raise RuntimeError(
                "工资台账迁移 v55 尚未完成，缺少表: " + ", ".join(missing)
            )

    @staticmethod
    def analyze(db, payroll_month):
        PayrollHistoryMigrationService._require_schema(db)
        period_start, period_end = reporting_month_bounds(payroll_month)
        rows = PayrollHistoryMigrationRepository.source_records(
            period_start, period_end, db
        )
        resolved = []
        unresolved = []
        reason_counts = {}
        for row in rows:
            if row.get("existing_resolution_id"):
                if (
                    row.get("existing_method") == "current_price_migration"
                    and row.get("existing_policy_code") == POLICY_CODE
                ):
                    row["classification"] = "current_price_migration"
                    row["price_version_id"] = row.get("existing_price_version_id")
                else:
                    row["classification"] = "already_resolved"
                resolved.append(row)
                continue
            if not row.get("route_id"):
                reason = "missing_route"
                candidates = []
            else:
                candidates = PayrollHistoryMigrationRepository.current_price_candidates(
                    row["route_id"], row["process_id"], db
                )
                if not candidates:
                    reason = "missing_current_price"
                elif len(candidates) > 1:
                    reason = "ambiguous_current_price"
                elif int(candidates[0].get("normal_unit_price_micros") or 0) <= 0:
                    reason = "zero_current_price"
                elif row["work_type"] == "rework" and not candidates[0]["rework_rate_configured"]:
                    reason = "missing_rework_rate"
                else:
                    reason = ""
            if reason:
                row["classification"] = reason
                unresolved.append(row)
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                continue
            row["classification"] = "current_price_migration"
            row["price_version_id"] = candidates[0]["id"]
            resolved.append(row)
        manifest_records = [
            {
                "work_record_id": int(row["work_record_id"]),
                "classification": row["classification"],
            }
            for row in sorted(rows, key=lambda item: int(item["work_record_id"]))
        ]
        manifest_document = {
            "format": MANIFEST_FORMAT,
            "payroll_month": payroll_month,
            "policy_code": POLICY_CODE,
            "period_start": period_start,
            "period_end": period_end,
            "records": manifest_records,
        }
        return {
            "payroll_month": payroll_month,
            "period_start": period_start,
            "period_end": period_end,
            "total": len(rows),
            "resolved": len(resolved),
            "unresolved": len(unresolved),
            "reason_counts": reason_counts,
            "resolved_rows": resolved,
            "unresolved_rows": unresolved,
            "manifest_records_json": _canonical_json(manifest_records),
            "manifest_sha256": hashlib.sha256(
                _canonical_json(manifest_document).encode("utf-8")
            ).hexdigest(),
        }

    @staticmethod
    def _validate_manifest(manifest, plan):
        expected = {
            "payroll_month": plan["payroll_month"],
            "policy_code": POLICY_CODE,
            "period_start": plan["period_start"],
            "period_end": plan["period_end"],
            "source_record_count": plan["total"],
            "resolved_record_count": plan["resolved"],
            "unresolved_record_count": plan["unresolved"],
            "records_json": plan["manifest_records_json"],
            "manifest_sha256": plan["manifest_sha256"],
        }
        mismatched = [
            field for field, value in expected.items()
            if manifest.get(field) != value
        ]
        if mismatched:
            raise RuntimeError(
                "历史工资迁移清单与当前数据不一致: " + ", ".join(mismatched)
            )

    @staticmethod
    def validate_counts(plan, expected_resolved, expected_unresolved):
        if plan["resolved"] != expected_resolved or plan["unresolved"] != expected_unresolved:
            raise RuntimeError(
                "历史工资基线不一致: "
                f"expected resolved={expected_resolved}, unresolved={expected_unresolved}; "
                f"actual resolved={plan['resolved']}, unresolved={plan['unresolved']}"
            )

    @staticmethod
    def apply(
        db,
        payroll_month,
        preparer_id,
        expected_resolved,
        expected_unresolved,
        create_revision=True,
    ):
        db.execute("BEGIN IMMEDIATE")
        try:
            plan = PayrollHistoryMigrationService.analyze(db, payroll_month)
            PayrollHistoryMigrationService.validate_counts(
                plan, expected_resolved, expected_unresolved
            )
            preparer = PayrollHistoryMigrationRepository.preparer(preparer_id, db)
            if not preparer:
                raise RuntimeError("指定的工资制单人不存在")
            preparer_name = preparer["name"] or preparer["username"] or ""
            manifest = PayrollHistoryMigrationRepository.migration_manifest(
                payroll_month, POLICY_CODE, db
            )
            if manifest:
                PayrollHistoryMigrationService._validate_manifest(manifest, plan)
            inserted = 0
            for row in plan["resolved_rows"]:
                if row.get("existing_resolution_id"):
                    continue
                PayrollRepository.insert_price_resolution(
                    {
                        "work_record_id": row["work_record_id"],
                        "price_version_id": row["price_version_id"],
                        "resolution_method": "current_price_migration",
                        "resolution_reason": "按迁移时当前工价结算历史报工",
                        "policy_code": POLICY_CODE,
                        "resolved_by": preparer_id,
                        "resolved_by_name": preparer_name,
                    },
                    db,
                )
                inserted += 1

            batch = None
            calculation = None
            if create_revision:
                batch, calculation, _ = PayrollHistoryMigrationService._create_revision(
                    db,
                    payroll_month,
                    preparer_id,
                    preparer_name,
                    expected_resolved,
                    expected_unresolved,
                )
            batch_id = batch["id"] if batch else None
            if manifest:
                if create_revision and manifest.get("batch_id") != batch_id:
                    raise RuntimeError("历史工资迁移清单关联的 V2 批次不一致")
            else:
                manifest_id = PayrollHistoryMigrationRepository.insert_migration_manifest(
                    {
                        "payroll_month": payroll_month,
                        "policy_code": POLICY_CODE,
                        "period_start": plan["period_start"],
                        "period_end": plan["period_end"],
                        "source_record_count": plan["total"],
                        "resolved_record_count": plan["resolved"],
                        "unresolved_record_count": plan["unresolved"],
                        "records_json": plan["manifest_records_json"],
                        "manifest_sha256": plan["manifest_sha256"],
                        "prepared_by": preparer_id,
                        "prepared_by_name": preparer_name,
                        "batch_id": batch_id,
                    },
                    db,
                )
                manifest = PayrollHistoryMigrationRepository.migration_manifest_by_id(
                    manifest_id, db
                )
            if batch:
                event_key = f"payroll-history-current-price:{payroll_month}:v2:event"
                if not PayrollHistoryMigrationRepository.event_exists(event_key, db):
                    PayrollRepository.insert_event(
                        {
                            "batch_id": batch_id,
                            "event_type": "historical_revision_generated",
                            "to_status": calculation["status"],
                            "operator_id": preparer_id,
                            "operator_name": preparer_name,
                            "reason": (
                                "按当前工价重算历史报工，"
                                f"{expected_unresolved} 条异常保留人工复核"
                            ),
                            "payload": {
                                "policy_code": POLICY_CODE,
                                "expected_resolved": expected_resolved,
                                "expected_unresolved": expected_unresolved,
                                "manifest_id": manifest["id"],
                                "manifest_sha256": manifest["manifest_sha256"],
                            },
                            "idempotency_key": event_key,
                        },
                        db,
                    )
            db.commit()
            return {
                "plan": plan,
                "inserted_resolutions": inserted,
                "batch": batch,
                "calculation": calculation,
                "manifest": manifest,
            }
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def _create_revision(
        db,
        payroll_month,
        preparer_id,
        preparer_name,
        expected_resolved,
        expected_unresolved,
    ):
        idempotency_key = f"payroll-history-current-price:{payroll_month}:v2"
        existing = PayrollRepository.get_batch_by_idempotency(idempotency_key, db)
        if existing:
            calculation = {
                "source_record_count": existing["source_record_count"],
                "priced_record_count": existing["priced_record_count"],
                "exception_count": existing["exception_count"],
                "status": existing["status"],
            }
            PayrollHistoryMigrationService._validate_calculation(
                calculation, expected_resolved, expected_unresolved
            )
            return existing, calculation, False
        legacy = PayrollHistoryMigrationRepository.legacy_batch(payroll_month, db)
        if not legacy:
            raise RuntimeError("未找到该月份的 Legacy V1 工资快照，不能生成修订版")
        next_version = PayrollRepository.next_version(payroll_month, db)
        if next_version != 2:
            raise RuntimeError(f"该月份下一版本应为 V2，实际为 V{next_version}")
        period_start, period_end = reporting_month_bounds(payroll_month)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        batch_id = PayrollRepository.insert_batch(
            {
                "payroll_month": payroll_month,
                "version": 2,
                "period_start": period_start,
                "period_end": period_end,
                "status": "draft",
                "source_cutoff_at": now,
                "input_digest": "",
                "idempotency_key": idempotency_key,
                "prepared_by": preparer_id,
                "prepared_by_name": preparer_name,
                "revision_reason": "按当前工价重算历史报工，保留 Legacy V1",
                "supersedes_batch_id": legacy["id"],
                "legacy_imported": 0,
            },
            db,
        )
        batch = PayrollRepository.get_batch(batch_id, db)
        calculation = PayrollCalculationService.populate(
            batch, {"id": preparer_id, "name": preparer_name}, db
        )
        PayrollHistoryMigrationService._validate_calculation(
            calculation, expected_resolved, expected_unresolved
        )
        return PayrollRepository.get_batch(batch_id, db), calculation, True

    @staticmethod
    def _validate_calculation(calculation, expected_resolved, expected_unresolved):
        if (
            calculation["source_record_count"] != expected_resolved + expected_unresolved
            or calculation["priced_record_count"] != expected_resolved
            or calculation["exception_count"] != expected_unresolved
        ):
            raise RuntimeError(
                "V2 计算结果与历史工资基线不一致: "
                f"source={calculation['source_record_count']} "
                f"priced={calculation['priced_record_count']} "
                f"exceptions={calculation['exception_count']}"
            )
