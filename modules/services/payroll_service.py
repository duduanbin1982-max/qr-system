"""Versioned payroll calculation and dual-control workflow services."""

from datetime import datetime
import hashlib
import json
import logging

from modules import config
from modules.domain.payroll_policy import (
    PayrollConflictError,
    cents_to_yuan,
    require_row_version,
    validate_payroll_month,
    work_amount_cents,
    yuan_to_cents,
)
from modules.domain.reporting_day import reporting_month_bounds
from modules.repositories.payroll_repository import PayrollRepository
from modules.services import BaseService


logger = logging.getLogger("qr-system.payroll")


def _actor(user):
    user = user or {}
    return user.get("id"), user.get("name") or user.get("username") or "system"


def _snapshot(row):
    return {
        "work_record_id": row.get("work_record_id"),
        "order_id": row.get("order_id"),
        "process_id": row.get("process_id"),
        "user_id": row.get("user_id"),
        "type": row.get("work_type"),
        "quantity": row.get("quantity"),
        "created_at": row.get("work_recorded_at"),
        "employee_name": row.get("employee_name") or "",
        "employee_no": row.get("employee_no") or "",
        "position_name": row.get("position_name") or "",
        "order_no": row.get("order_no") or "",
        "product_code": row.get("product_code") or "",
        "product_name": row.get("product_name") or "",
        "route_id": row.get("route_id"),
        "route_version_id": row.get("route_version_id"),
        "route_name": row.get("route_name") or "",
        "process_name": row.get("process_name") or "",
        "process_version_id": row.get("process_version_id"),
        "process_code": row.get("process_code") or "",
        "process_category": row.get("process_category") or "",
    }


def _fixed_snapshot(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class PayrollCalculationService:
    @staticmethod
    def _exception(batch, row, exception_type, db):
        PayrollRepository.insert_exception(
            {
                "batch_id": batch["id"],
                "work_record_id": row["work_record_id"],
                "employee_id": row["user_id"],
                "exception_type": exception_type,
                "snapshot": _snapshot(row),
            },
            db,
        )

    @staticmethod
    def _resolve(row, batch, db):
        resolution = PayrollRepository.price_resolution(row["work_record_id"], db)
        if resolution:
            if int(resolution.get("normal_unit_price_micros") or 0) <= 0:
                return None, None, "zero_price"
            return {
                "price_version_id": resolution["price_version_id"],
                "normal_unit_price_micros": resolution["normal_unit_price_micros"],
                "rework_rate_basis_points": resolution["rework_rate_basis_points"],
                "rework_rate_configured": resolution["rework_rate_configured"],
                "resolution_method": resolution["resolution_method"],
                "resolution_reason": resolution["resolution_reason"],
                "resolved_by": resolution.get("resolved_by"),
                "resolved_by_name": resolution.get("resolved_by_name") or "",
                "resolved_at": resolution.get("resolved_at") or "",
            }, None, None
        approved_exception = PayrollRepository.approved_exception(row["work_record_id"], batch["id"], db)
        if approved_exception:
            return None, approved_exception, "invalid_amount"
        if not row.get("route_id"):
            return None, None, "missing_route"
        has_exact_binding = (
            row.get("route_version_id") is not None
            and row.get("process_version_id") is not None
        )
        candidates = PayrollRepository.price_candidates(
            row["route_id"],
            row["process_id"],
            row["work_recorded_at"],
            db,
            route_version_id=(
                row["route_version_id"] if has_exact_binding else None
            ),
            process_version_id=(
                row["process_version_id"] if has_exact_binding else None
            ),
        )
        if not has_exact_binding and config.PROCESS_VERSION_COMPAT_AUDIT_ENABLED:
            logger.warning(
                "payroll_price_legacy_fallback work_record_id=%s route_id=%s process_id=%s",
                row.get("work_record_id"),
                row.get("route_id"),
                row.get("process_id"),
            )
        if len(candidates) > 1:
            return None, None, "overlapping_price"
        if not candidates:
            return None, None, "missing_price"
        price = candidates[0]
        if int(price.get("normal_unit_price_micros") or 0) <= 0:
            return None, None, "zero_price"
        if row["work_type"] == "rework" and not price.get("rework_rate_configured"):
            return None, None, "missing_rework_rate"
        return {
            "price_version_id": price["id"],
            "normal_unit_price_micros": price["normal_unit_price_micros"],
            "rework_rate_basis_points": price["rework_rate_basis_points"],
            "rework_rate_configured": price["rework_rate_configured"],
            "resolution_method": "versioned_price",
            "resolution_reason": (
                "Matched exact route and process versions at work-report time"
                if has_exact_binding
                else "Legacy root-ID price fallback for unversioned work record"
            ),
            "resolved_by": None,
            "resolved_by_name": "",
            "resolved_at": "",
        }, None, None

    @staticmethod
    def populate(batch, actor, db):
        PayrollRepository.delete_draft_calculation(batch["id"], db)
        rows = PayrollRepository.source_work_records(
            batch["period_start"], batch["period_end"], batch["source_cutoff_at"], db
        )
        adjustments = PayrollRepository.adjustments_for_month(
            batch["payroll_month"], batch["source_cutoff_at"], db
        )
        employees = {}
        details = []
        digest_items = []
        priced_count = 0

        def employee_bucket(row, employee_id=None):
            employee_id = row.get("user_id") if employee_id is None else employee_id
            key = employee_id if employee_id is not None else f"snapshot:{row.get('employee_no','')}:{row.get('employee_name','')}"
            if key not in employees:
                employees[key] = {
                    "batch_id": batch["id"], "employee_id": employee_id,
                    "employee_name_snapshot": row.get("employee_name") or "",
                    "employee_no_snapshot": row.get("employee_no") or "",
                    "position_name_snapshot": row.get("position_name") or "",
                    "normal_quantity": 0, "rework_quantity": 0,
                    "normal_wage_cents": 0, "rework_wage_cents": 0,
                    "bonus_cents": 0, "allowance_cents": 0, "deduction_cents": 0,
                    "payable_wage_cents": 0, "exception_count": 0,
                }
            return employees[key]

        for row in rows:
            digest_items.append({
                "id": row["work_record_id"], "type": row["work_type"], "quantity": row["quantity"],
                "created_at": row["work_recorded_at"], "route_id": row.get("route_id"),
                "route_version_id": row.get("route_version_id"),
                "process_id": row.get("process_id"),
                "process_version_id": row.get("process_version_id"),
            })
            price, approved_exception, exception_type = PayrollCalculationService._resolve(row, batch, db)
            bucket = employee_bucket(row)
            if exception_type:
                PayrollCalculationService._exception(batch, row, exception_type, db)
                continue
            try:
                if row["quantity"] is None or int(row["quantity"]) <= 0:
                    raise ValueError("quantity")
                amount = work_amount_cents(
                    row["quantity"], price["normal_unit_price_micros"],
                    price["rework_rate_basis_points"] if row["work_type"] == "rework" else None,
                )
            except (TypeError, ValueError, OverflowError):
                PayrollCalculationService._exception(batch, row, "invalid_amount", db)
                continue
            priced_count += 1
            if row["work_type"] == "rework":
                bucket["rework_quantity"] += int(row["quantity"])
                bucket["rework_wage_cents"] += amount
                source_type = "rework_work"
            else:
                bucket["normal_quantity"] += int(row["quantity"])
                bucket["normal_wage_cents"] += amount
                source_type = "normal_work"
            details.append({
                "bucket": bucket,
                "source_type": source_type,
                "source_id": row["work_record_id"],
                "work_record_id": row["work_record_id"],
                "work_recorded_at": row["work_recorded_at"],
                "order_id": row.get("order_id"), "order_no_snapshot": row.get("order_no") or "",
                "product_code_snapshot": row.get("product_code") or "",
                "product_name_snapshot": row.get("product_name") or "",
                "route_id": row.get("route_id"),
                "route_version_id": row.get("route_version_id"),
                "route_name_snapshot": row.get("route_name") or "",
                "process_id": row.get("process_id"),
                "process_version_id": row.get("process_version_id"),
                "process_name_snapshot": row.get("process_name") or "",
                "quantity": int(row["quantity"]), "price_version_id": price.get("price_version_id"),
                "unit_price_micros": price["normal_unit_price_micros"],
                "rework_rate_basis_points": price.get("rework_rate_basis_points") or 0,
                "amount_cents": amount, "resolution_method": price["resolution_method"],
                "resolution_reason": price["resolution_reason"], "resolved_by": price.get("resolved_by"),
                "resolved_by_name": price.get("resolved_by_name") or "", "resolved_at": price.get("resolved_at") or "",
                "source_snapshot_json": _fixed_snapshot(_snapshot(row)),
            })

        for adjustment in adjustments:
            key = adjustment.get("employee_id")
            bucket = employees.get(key)
            if bucket is None:
                bucket = employee_bucket({
                    "user_id": key,
                    "employee_name": adjustment.get("employee_name_snapshot") or "",
                    "employee_no": adjustment.get("employee_no_snapshot") or "",
                    "position_name": "",
                }, key)
            sign = -1 if adjustment.get("reversal_of_id") else 1
            amount = int(adjustment["amount_cents"]) * sign
            if adjustment["adjustment_type"] == "bonus":
                bucket["bonus_cents"] += amount
                source_type = "bonus"
                detail_amount = amount
            elif adjustment["adjustment_type"] == "allowance":
                bucket["allowance_cents"] += amount
                source_type = "allowance"
                detail_amount = amount
            else:
                bucket["deduction_cents"] += amount
                source_type = "deduction"
                detail_amount = -amount
            digest_items.append({
                "adjustment_id": adjustment["id"], "type": adjustment["adjustment_type"],
                "amount_cents": adjustment["amount_cents"], "reversal_of_id": adjustment.get("reversal_of_id"),
            })
            details.append({
                "bucket": bucket, "source_type": source_type, "source_id": adjustment["id"],
                "quantity": 0, "amount_cents": detail_amount,
                "resolution_method": "adjustment", "resolution_reason": adjustment["reason"],
                "resolved_by": adjustment.get("created_by"), "resolved_by_name": adjustment.get("created_by_name") or "",
                "resolved_at": adjustment.get("created_at") or "",
                "source_snapshot_json": _fixed_snapshot(adjustment),
                "work_record_id": None, "work_recorded_at": adjustment.get("created_at") or "",
                "order_id": None, "order_no_snapshot": "", "product_code_snapshot": "",
                "product_name_snapshot": "", "route_id": None,
                "route_version_id": None, "route_name_snapshot": "",
                "process_id": None, "process_version_id": None,
                "process_name_snapshot": "", "price_version_id": None,
                "unit_price_micros": 0, "rework_rate_basis_points": 0,
            })

        for bucket in employees.values():
            bucket["payable_wage_cents"] = (
                bucket["normal_wage_cents"] + bucket["rework_wage_cents"] +
                bucket["bonus_cents"] + bucket["allowance_cents"] - bucket["deduction_cents"]
            )
            bucket["line_id"] = PayrollRepository.insert_employee_line(bucket, db)
        for detail in details:
            detail["batch_id"] = batch["id"]
            detail["employee_line_id"] = detail["bucket"]["line_id"]
            detail.pop("bucket", None)
            PayrollRepository.insert_detail_line(detail, db)
        PayrollRepository.update_line_exception_counts(batch["id"], db)
        pending_count = len(PayrollRepository.list_exceptions(batch_id=batch["id"], status="pending", db=db))
        proposed_count = len(PayrollRepository.list_exceptions(batch_id=batch["id"], status="proposed", db=db))
        exception_count = pending_count + proposed_count
        status = "exceptions_pending" if exception_count else "draft"
        digest = hashlib.sha256(_fixed_snapshot(digest_items).encode("utf-8")).hexdigest()
        totals = {
            "status": status, "input_digest": digest, "source_cutoff_at": batch["source_cutoff_at"],
            "normal_wage_cents": sum(item["normal_wage_cents"] for item in employees.values()),
            "rework_wage_cents": sum(item["rework_wage_cents"] for item in employees.values()),
            "bonus_cents": sum(item["bonus_cents"] for item in employees.values()),
            "allowance_cents": sum(item["allowance_cents"] for item in employees.values()),
            "deduction_cents": sum(item["deduction_cents"] for item in employees.values()),
            "payable_wage_cents": sum(item["payable_wage_cents"] for item in employees.values()),
            "source_record_count": len(rows), "priced_record_count": priced_count, "exception_count": exception_count,
        }
        PayrollRepository.update_batch_calculation(batch["id"], batch["row_version"], totals, db)
        return {"batch_id": batch["id"], **totals, "employee_count": len(employees), "detail_count": len(details)}


class PayrollWorkflowService:
    @staticmethod
    def create_batch(month, actor_user, idempotency_key, revision_reason="", supersedes_batch_id=None):
        month = validate_payroll_month(month)
        if not str(idempotency_key or "").strip():
            raise ValueError("必须提供幂等键")
        actor_id, actor_name = _actor(actor_user)
        period_start, period_end = reporting_month_bounds(month)
        with BaseService.transaction() as db:
            existing = PayrollRepository.get_batch_by_idempotency(idempotency_key, db)
            if existing:
                if (
                    existing["payroll_month"] != month
                    or existing.get("supersedes_batch_id") != supersedes_batch_id
                ):
                    raise PayrollConflictError("幂等键已用于不同的工资批次请求")
                return PayrollWorkflowService.serialize_batch(existing)
            if supersedes_batch_id is None and PayrollRepository.current_confirmed(month, db):
                raise ValueError("该月份已有正式批次，请通过修订接口生成新版本")
            supersedes = PayrollRepository.get_batch(supersedes_batch_id, db) if supersedes_batch_id else None
            if supersedes_batch_id and not supersedes:
                raise ValueError("被修订批次不存在")
            if supersedes and supersedes["payroll_month"] != month:
                raise ValueError("修订批次月份不一致")
            if supersedes and not revision_reason.strip():
                raise ValueError("修订必须填写原因")
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            payload = {
                "payroll_month": month, "version": PayrollRepository.next_version(month, db),
                "period_start": period_start, "period_end": period_end, "status": "draft",
                "source_cutoff_at": now, "input_digest": "", "idempotency_key": idempotency_key,
                "prepared_by": actor_id, "prepared_by_name": actor_name,
                "revision_reason": revision_reason.strip(), "supersedes_batch_id": supersedes_batch_id,
                "legacy_imported": 0,
            }
            batch_id = PayrollRepository.insert_batch(payload, db)
            batch = PayrollRepository.get_batch(batch_id, db)
            calculation = PayrollCalculationService.populate(batch, actor_user, db)
            PayrollRepository.insert_event({
                "batch_id": batch_id, "event_type": "generated", "to_status": calculation["status"],
                "operator_id": actor_id, "operator_name": actor_name, "reason": revision_reason.strip(),
                "payload": calculation, "idempotency_key": idempotency_key,
            }, db)
            return {**PayrollWorkflowService.serialize_batch(PayrollRepository.get_batch(batch_id, db)), **calculation}

    @staticmethod
    def regenerate(batch_id, actor_user, expected_row_version):
        actor_id, actor_name = _actor(actor_user)
        expected_row_version = require_row_version(expected_row_version)
        with BaseService.transaction() as db:
            batch = PayrollRepository.get_batch(batch_id, db)
            if not batch:
                raise ValueError("工资批次不存在")
            if batch["status"] not in ("draft", "exceptions_pending"):
                raise ValueError("只有草稿或待异常处理批次可以重算")
            if batch["prepared_by"] not in (None, actor_id):
                raise ValueError("只能由制单人重算该批次")
            if batch["row_version"] != expected_row_version:
                raise PayrollConflictError("工资批次版本冲突")
            batch["source_cutoff_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            calculation = PayrollCalculationService.populate(batch, actor_user, db)
            PayrollRepository.insert_event({
                "batch_id": batch_id, "event_type": "regenerated", "from_status": batch["status"],
                "to_status": calculation["status"], "operator_id": actor_id, "operator_name": actor_name,
                "payload": calculation,
            }, db)
            return {**PayrollWorkflowService.serialize_batch(PayrollRepository.get_batch(batch_id, db)), **calculation}

    @staticmethod
    def submit(batch_id, actor_user, expected_row_version):
        return PayrollWorkflowService._transition(batch_id, actor_user, expected_row_version, "review_pending", "submitted")

    @staticmethod
    def lock(batch_id, actor_user, expected_row_version):
        return PayrollWorkflowService._transition(batch_id, actor_user, expected_row_version, "locked", "locked")

    @staticmethod
    def confirm(batch_id, actor_user, expected_row_version):
        actor_id, actor_name = _actor(actor_user)
        expected_row_version = require_row_version(expected_row_version)
        with BaseService.transaction() as db:
            batch = PayrollRepository.get_batch(batch_id, db)
            PayrollWorkflowService._check_approval(batch, actor_id, "locked")
            if batch["row_version"] != expected_row_version:
                raise PayrollConflictError("工资批次版本冲突")
            if PayrollRepository.list_exceptions(batch_id=batch_id, status="pending", db=db) or PayrollRepository.list_exceptions(batch_id=batch_id, status="proposed", db=db):
                raise ValueError("仍有未处理工资异常")
            old_id = batch.get("supersedes_batch_id")
            if old_id:
                old = PayrollRepository.get_batch(old_id, db)
                if old and old.get("status") == "confirmed":
                    PayrollRepository.mark_superseded(old_id, batch_id, db)
            PayrollRepository.transition_batch(
                batch_id, expected_row_version, "confirmed",
                {"confirmed_by": actor_id, "confirmed_by_name": actor_name,
                 "confirmed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, db,
            )
            PayrollRepository.insert_event({
                "batch_id": batch_id, "event_type": "confirmed", "from_status": "locked", "to_status": "confirmed",
                "operator_id": actor_id, "operator_name": actor_name, "payload": {"superseded_batch_id": old_id},
            }, db)
            return PayrollWorkflowService.serialize_batch(PayrollRepository.get_batch(batch_id, db))

    @staticmethod
    def void(batch_id, actor_user, expected_row_version, reason):
        if not str(reason or "").strip():
            raise ValueError("作废必须填写原因")
        actor_id, actor_name = _actor(actor_user)
        expected_row_version = require_row_version(expected_row_version)
        with BaseService.transaction() as db:
            batch = PayrollRepository.get_batch(batch_id, db)
            PayrollWorkflowService._check_approval(batch, actor_id, ("locked", "confirmed"))
            PayrollRepository.transition_batch(
                batch_id, expected_row_version, "voided",
                {"voided_by": actor_id, "voided_by_name": actor_name,
                 "voided_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "void_reason": reason.strip()}, db,
            )
            PayrollRepository.insert_event({
                "batch_id": batch_id, "event_type": "voided", "from_status": batch["status"], "to_status": "voided",
                "operator_id": actor_id, "operator_name": actor_name, "reason": reason.strip(),
            }, db)
            return PayrollWorkflowService.serialize_batch(PayrollRepository.get_batch(batch_id, db))

    @staticmethod
    def _check_approval(batch, actor_id, required_status):
        if not batch:
            raise ValueError("工资批次不存在")
        required = required_status if isinstance(required_status, tuple) else (required_status,)
        if batch["status"] not in required:
            raise ValueError("工资批次状态不允许此操作")
        if batch.get("prepared_by") is not None and batch.get("prepared_by") == actor_id:
            raise ValueError("制单人与审批人必须为不同用户")

    @staticmethod
    def _transition(batch_id, actor_user, expected_row_version, status, event_type):
        actor_id, actor_name = _actor(actor_user)
        expected_row_version = require_row_version(expected_row_version)
        with BaseService.transaction() as db:
            batch = PayrollRepository.get_batch(batch_id, db)
            if status == "review_pending":
                if not batch or batch["status"] not in ("draft", "exceptions_pending"):
                    raise ValueError("只有草稿可以提交复核")
                if batch.get("prepared_by") not in (None, actor_id):
                    raise ValueError("只能由制单人提交该批次")
                if PayrollRepository.list_exceptions(batch_id=batch_id, status="pending", db=db) or PayrollRepository.list_exceptions(batch_id=batch_id, status="proposed", db=db):
                    raise ValueError("存在未处理工资异常，不能提交复核")
            else:
                PayrollWorkflowService._check_approval(batch, actor_id, "review_pending")
            if batch["row_version"] != expected_row_version:
                raise PayrollConflictError("工资批次版本冲突")
            fields = {}
            if status == "review_pending":
                fields["submitted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                fields.update({
                    "locked_by": actor_id, "locked_by_name": actor_name,
                    "locked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
            PayrollRepository.transition_batch(batch_id, expected_row_version, status, fields, db)
            PayrollRepository.insert_event({
                "batch_id": batch_id, "event_type": event_type, "from_status": batch["status"],
                "to_status": status, "operator_id": actor_id, "operator_name": actor_name,
            }, db)
            return PayrollWorkflowService.serialize_batch(PayrollRepository.get_batch(batch_id, db))

    @staticmethod
    def propose_exception(exception_id, actor_user, data):
        actor_id, actor_name = _actor(actor_user)
        reason = str(data.get("resolution_reason") or "").strip()
        if not reason:
            raise ValueError("异常处理必须填写原因")
        with BaseService.transaction() as db:
            exception = next((row for row in PayrollRepository.list_exceptions(db=db) if row["id"] == exception_id), None)
            if not exception:
                raise ValueError("工资异常不存在")
            if exception["status"] not in ("pending", "rejected"):
                raise ValueError("当前异常状态不能提出处理方案")
            snapshot = json.loads(exception.get("snapshot_json") or "{}")
            price = data.get("proposed_price_micros")
            price = int(price) if price is not None else None
            if price is not None and price <= 0:
                raise ValueError("处理工价必须大于 0")
            rate = data.get("proposed_rework_rate_basis_points")
            rate = int(rate) if rate is not None else None
            if rate is not None and not 0 <= rate <= 10000:
                raise ValueError("返工倍率必须在 0 到 10000 之间")
            if price is None and exception["exception_type"] != "missing_rework_rate":
                raise ValueError("该异常必须填写人工核定工价")
            if snapshot.get("type") == "rework" and rate is None:
                raise ValueError("返工报工必须填写核定倍率")
            PayrollRepository.update_exception_proposal(
                exception_id, exception["status"], {
                    "proposed_price_micros": price, "proposed_rework_rate_basis_points": rate,
                    "proposed_by": actor_id, "proposed_by_name": actor_name, "resolution_reason": reason,
                }, db,
            )
            PayrollRepository.insert_event({
                "batch_id": exception["batch_id"], "event_type": "exception_proposed",
                "operator_id": actor_id, "operator_name": actor_name, "reason": reason,
                "payload": {"exception_id": exception_id},
            }, db)
            return {"ok": True, "exception_id": exception_id, "status": "proposed"}

    @staticmethod
    def approve_exception(exception_id, actor_user):
        actor_id, actor_name = _actor(actor_user)
        with BaseService.transaction() as db:
            exception = next((row for row in PayrollRepository.list_exceptions(db=db) if row["id"] == exception_id), None)
            if not exception:
                raise ValueError("工资异常不存在")
            if exception["status"] != "proposed":
                raise ValueError("只有待审批异常可以批准")
            if exception.get("proposed_by") == actor_id:
                raise ValueError("异常提出人与审批人必须不同")
            snapshot = json.loads(exception.get("snapshot_json") or "{}")
            price_version_id = None
            override_price = exception.get("proposed_price_micros")
            if override_price is None:
                candidates = PayrollRepository.price_candidates(
                    snapshot.get("route_id"),
                    snapshot.get("process_id"),
                    snapshot.get("created_at"),
                    db,
                    route_version_id=snapshot.get("route_version_id"),
                    process_version_id=snapshot.get("process_version_id"),
                )
                if len(candidates) != 1:
                    raise ValueError("无法唯一确定基础工价，请由制单人补充人工核定工价")
                price_version_id = candidates[0]["id"]
            PayrollRepository.insert_price_resolution({
                "work_record_id": exception["work_record_id"],
                "price_version_id": price_version_id,
                "override_unit_price_micros": override_price,
                "override_rework_rate_basis_points": exception.get("proposed_rework_rate_basis_points"),
                "resolution_method": "manual_exception_resolution",
                "resolution_reason": exception.get("resolution_reason") or "Approved payroll exception",
                "policy_code": "dual_review_manual_resolution_v1",
                "resolved_by": actor_id,
                "resolved_by_name": actor_name,
            }, db)
            PayrollRepository.approve_exception(exception_id, "proposed", {
                "approved_by": actor_id, "approved_by_name": actor_name,
            }, db)
            PayrollRepository.insert_event({
                "batch_id": exception["batch_id"], "event_type": "exception_approved",
                "operator_id": actor_id, "operator_name": actor_name,
                "payload": {"exception_id": exception_id},
            }, db)
            return {"ok": True, "exception_id": exception_id, "status": "approved"}

    @staticmethod
    def create_adjustment(actor_user, data):
        actor_id, actor_name = _actor(actor_user)
        month = validate_payroll_month(data.get("payroll_month"))
        adjustment_type = str(data.get("adjustment_type") or "").strip()
        if adjustment_type not in ("bonus", "allowance", "deduction"):
            raise ValueError("调整类型无效")
        reason = str(data.get("reason") or "").strip()
        if not reason:
            raise ValueError("调整项必须填写原因")
        employee_id = int(data.get("employee_id"))
        amount_cents = int(data.get("amount_cents")) if data.get("amount_cents") is not None else yuan_to_cents(data.get("amount"))
        if amount_cents <= 0:
            raise ValueError("调整金额必须大于 0")
        with BaseService.transaction() as db:
            employee = PayrollRepository.user_snapshot(employee_id, db)
            if not employee:
                raise ValueError("员工不存在")
            adjustment_id = PayrollRepository.create_adjustment({
                "employee_id": employee_id, "employee_name_snapshot": employee["name"] or "",
                "employee_no_snapshot": employee["employee_no"] or "", "payroll_month": month,
                "adjustment_type": adjustment_type, "amount_cents": amount_cents, "reason": reason,
                "created_by": actor_id, "created_by_name": actor_name,
            }, db)
            PayrollRepository.insert_event({
                "event_type": "adjustment_created", "operator_id": actor_id, "operator_name": actor_name,
                "reason": reason, "payload": {"adjustment_id": adjustment_id, "payroll_month": month},
            }, db)
            return {"ok": True, "id": adjustment_id}

    @staticmethod
    def reverse_adjustment(adjustment_id, actor_user, reason):
        actor_id, actor_name = _actor(actor_user)
        if not str(reason or "").strip():
            raise ValueError("冲销必须填写原因")
        with BaseService.transaction() as db:
            original = PayrollRepository.get_adjustment(adjustment_id, db)
            if not original:
                raise ValueError("调整项不存在")
            if original.get("reversal_of_id"):
                raise ValueError("不能再次冲销冲销记录")
            if PayrollRepository.has_adjustment_reversal(adjustment_id, db):
                raise ValueError("该调整项已经冲销")
            new_id = PayrollRepository.create_adjustment({
                "employee_id": original["employee_id"], "employee_name_snapshot": original["employee_name_snapshot"],
                "employee_no_snapshot": original["employee_no_snapshot"], "payroll_month": original["payroll_month"],
                "adjustment_type": original["adjustment_type"], "amount_cents": original["amount_cents"],
                "reason": reason.strip(), "created_by": actor_id, "created_by_name": actor_name,
                "reversal_of_id": adjustment_id,
            }, db)
            PayrollRepository.insert_event({
                "event_type": "adjustment_reversed", "operator_id": actor_id, "operator_name": actor_name,
                "reason": reason.strip(), "payload": {"adjustment_id": adjustment_id, "reversal_id": new_id},
            }, db)
            return {"ok": True, "id": new_id, "reversal_of_id": adjustment_id}

    @staticmethod
    def serialize_batch(batch):
        if not batch:
            return None
        result = dict(batch)
        for key in ("normal_wage_cents", "rework_wage_cents", "bonus_cents", "allowance_cents", "deduction_cents", "payable_wage_cents"):
            result[key.replace("_cents", "_yuan")] = cents_to_yuan(result.get(key, 0))
        return result

    @staticmethod
    def batch_detail(batch_id, employee_id=None):
        batch = PayrollRepository.get_batch(batch_id)
        if not batch:
            raise ValueError("工资批次不存在")
        return {
            "batch": PayrollWorkflowService.serialize_batch(batch),
            "lines": PayrollRepository.list_lines(batch_id, employee_id),
            "details": PayrollRepository.list_details(batch_id, employee_id),
            "exceptions": PayrollRepository.list_exceptions(batch_id=batch_id),
            "events": PayrollRepository.list_events(batch_id),
        }

    @staticmethod
    def my_payroll(actor_user, month=""):
        actor_id, _ = _actor(actor_user)
        if actor_id is None:
            raise ValueError("当前用户无员工身份")
        lines = PayrollRepository.my_confirmed_lines(actor_id, validate_payroll_month(month) if month else "")
        for line in lines:
            line["payable_wage_yuan"] = cents_to_yuan(line.get("payable_wage_cents", 0))
        return {"lines": lines}

    @staticmethod
    def list_batches(month="", status=""):
        return {"batches": PayrollRepository.list_batches(month, status)}

    @staticmethod
    def compare_batches(batch_id, other_id):
        if not PayrollRepository.get_batch(batch_id) or not PayrollRepository.get_batch(other_id):
            raise ValueError("工资批次不存在")
        return {"items": PayrollRepository.compare_batches(batch_id, other_id)}

    @staticmethod
    def export_data(batch_id):
        batch = PayrollRepository.get_batch(batch_id)
        if not batch:
            raise ValueError("工资批次不存在")
        if batch["status"] not in ("locked", "confirmed"):
            raise ValueError("只有锁定或确认批次可以正式导出")
        return batch, PayrollRepository.list_lines(batch_id)

    @staticmethod
    def list_exceptions(month="", batch_id=None, status=""):
        return {"exceptions": PayrollRepository.list_exceptions(month, batch_id, status)}

    @staticmethod
    def list_adjustments(month="", employee_id=None):
        return {"adjustments": PayrollRepository.list_adjustments(month, employee_id)}
