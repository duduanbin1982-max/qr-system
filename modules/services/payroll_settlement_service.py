"""Payroll payment-list, receipt, reconciliation, and close workflow."""

import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import io
import json
import re

from modules.domain.payroll_policy import PayrollConflictError, cents_to_yuan
from modules.repositories.payroll_repository import PayrollRepository
from modules.repositories.payroll_settlement_repository import PayrollSettlementRepository as Repo
from modules.services import BaseService


PAYMENT_HEADERS = (
    "payment_reference",
    "payroll_month",
    "payroll_version",
    "employee_no",
    "employee_name",
    "payable_amount",
)
RECEIPT_HEADERS = (
    "payment_reference",
    "employee_no",
    "employee_name",
    "paid_amount",
    "payment_status",
    "paid_at",
    "external_transaction_no",
    "failure_reason",
)
RECEIPT_REQUIRED_HEADERS = set(RECEIPT_HEADERS[:5])
RECEIPT_ALLOWED_HEADERS = set(RECEIPT_HEADERS)
MAX_RECEIPT_BYTES = 2 * 1024 * 1024
MAX_RECEIPT_ROWS = 10000
PAYMENT_STATUSES = {"success", "failed", "processing", "returned"}


def _actor(user):
    user = user or {}
    return user.get("id"), user.get("name") or user.get("username") or "system"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _key(value):
    key = str(value or "").strip()
    if not key or len(key) > 128:
        raise ValueError("必须提供 1 到 128 个字符的 Idempotency-Key")
    return key


def _sha256(value):
    return hashlib.sha256(value).hexdigest()


def _csv_cell(value):
    text = str(value or "")
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def _payment_reference(batch_id, export_version, line_id):
    return f"PAY{batch_id:08d}V{export_version:04d}L{line_id:010d}"


def _money_cents(value, *, allow_zero=True):
    text = str(value or "").strip()
    try:
        amount = Decimal(text)
        rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("金额格式无效") from exc
    if not amount.is_finite() or amount != rounded:
        raise ValueError("金额最多支持两位小数")
    cents = int(rounded * 100)
    if cents < 0 or (cents == 0 and not allow_zero):
        raise ValueError("金额不能为负数")
    if cents > 9_000_000_000_000_000:
        raise ValueError("金额超出允许范围")
    return cents


def _sensitive_header(header):
    text = str(header or "").strip().lower()
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", text)
    return any(token in compact for token in (
        "bank", "account", "iban", "routing", "sortcode", "cardnumber",
        "卡号", "银行卡", "账户", "帐号", "账号", "开户", "銀行帳戶",
        "銀行帳號", "銀行卡號", "帳戶", "帳號",
    ))


def _parse_receipt(content):
    if not content:
        raise ValueError("回执 CSV 不能为空")
    if len(content) > MAX_RECEIPT_BYTES:
        raise ValueError("回执文件不能超过 2 MB")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("回执 CSV 必须使用 UTF-8 编码") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = [str(value or "").strip().lower() for value in (reader.fieldnames or [])]
    if not headers or len(headers) != len(set(headers)):
        raise ValueError("回执 CSV 表头为空或存在重复列")
    if any(_sensitive_header(header) for header in headers):
        raise ValueError("回执 CSV 不得包含银行卡号、开户行或收款账户字段")
    missing = RECEIPT_REQUIRED_HEADERS - set(headers)
    if missing:
        raise ValueError("回执 CSV 缺少必需列：" + ", ".join(sorted(missing)))

    rows = []
    for row_number, raw in enumerate(reader, start=2):
        if row_number - 1 > MAX_RECEIPT_ROWS:
            raise ValueError("回执 CSV 不能超过 10000 行")
        if None in raw:
            rows.append({
                "row_number": row_number,
                "validation_status": "invalid",
                "validation_error": "列数与表头不一致",
            })
            continue
        row = {str(k).strip().lower(): str(v or "").strip() for k, v in raw.items() if k}
        if not any(row.values()):
            continue
        item = {
            "row_number": row_number,
            "payment_reference": row.get("payment_reference", ""),
            "employee_no_snapshot": row.get("employee_no", ""),
            "employee_name_snapshot": row.get("employee_name", ""),
            "paid_cents": None,
            "payment_status": row.get("payment_status", "").lower(),
            "paid_at": row.get("paid_at", ""),
            "external_transaction_no": row.get("external_transaction_no", ""),
            "failure_reason": row.get("failure_reason", ""),
            "validation_status": "valid",
            "validation_error": "",
        }
        if not item["payment_reference"]:
            item["validation_status"] = "invalid"
            item["validation_error"] = "缺少 payment_reference"
        elif item["payment_status"] not in PAYMENT_STATUSES:
            item["validation_status"] = "invalid"
            item["validation_error"] = "payment_status 必须为 success、failed、processing 或 returned"
        else:
            try:
                item["paid_cents"] = _money_cents(row.get("paid_amount"), allow_zero=True)
                if item["payment_status"] == "success" and item["paid_cents"] <= 0:
                    raise ValueError("成功支付金额必须大于零")
            except ValueError as exc:
                item["validation_status"] = "invalid"
                item["validation_error"] = str(exc)
        rows.append(item)
    if not rows:
        raise ValueError("回执 CSV 没有数据行")
    return rows


def _write_csv(rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(PAYMENT_HEADERS)
    for row in rows:
        writer.writerow([
            row["payment_reference"],
            row["payroll_month"],
            row["payroll_version"],
            _csv_cell(row["employee_no_snapshot"]),
            _csv_cell(row["employee_name_snapshot"]),
            cents_to_yuan(row["payable_cents"]),
        ])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _receipt_digest(receipt_items, resolutions):
    rows = [{
        key: row.get(key) for key in (
            "id", "receipt_batch_id", "row_number", "payment_reference", "employee_no_snapshot",
            "employee_name_snapshot", "paid_cents", "payment_status", "paid_at",
            "external_transaction_no", "validation_status", "validation_error",
        )
    } for row in receipt_items]
    return _sha256(_json({"receipts": rows, "resolutions": resolutions}).encode("utf-8"))


def _emit_event(batch_id, event_type, actor_id, actor_name, reason, payload, key, db):
    Repo.insert_event({
        "batch_id": batch_id,
        "event_type": event_type,
        "operator_id": actor_id,
        "operator_name": actor_name,
        "reason": reason or "",
        "payload": payload,
        "idempotency_key": f"payroll-settlement:{event_type}:{key}",
    }, db)


class PayrollSettlementService:
    @staticmethod
    def get_by_batch(batch_id):
        db = BaseService.db()
        batch = PayrollRepository.get_batch(batch_id, db)
        if not batch:
            raise ValueError("工资批次不存在")
        settlement = Repo.get_by_batch(batch_id, db)
        if not settlement:
            return {
                "batch_id": batch_id,
                "status": "not_exported",
                "batch_status": batch["status"],
                "expected_total_cents": batch["payable_wage_cents"],
                "successful_paid_cents": 0,
                "difference_cents": batch["payable_wage_cents"],
                "blocking_difference_count": 0,
                "exports": [],
                "receipt_batches": [],
                "latest_reconciliation": None,
                "close_record": None,
            }
        export_id = settlement.get("current_export_batch_id")
        export = Repo.get_export(export_id, db) if export_id else None
        receipts = Repo.list_receipt_batches(export_id, db) if export_id else []
        latest = Repo.run_detail(settlement.get("latest_reconciliation_run_id"), db) \
            if settlement.get("latest_reconciliation_run_id") else None
        return {
            **settlement,
            "batch_id": batch_id,
            "batch_status": batch["status"],
            "exports": Repo.list_exports(settlement["id"], db),
            "current_export": export,
            "receipt_batches": receipts,
            "latest_reconciliation": latest,
            "close_record": Repo.close_record(settlement["id"], db),
            "can_close": bool(
                settlement["status"] == "reconciled"
                and latest
                and latest["status"] == "reconciled"
            ),
        }

    @staticmethod
    def create_export(batch_id, actor_user, idempotency_key):
        key = _key(idempotency_key)
        actor_id, actor_name = _actor(actor_user)
        with BaseService.transaction() as db:
            existing = Repo.get_export_by_key(key, db)
            if existing:
                settlement = Repo.get_settlement(existing["settlement_id"], db)
                if not settlement or settlement["batch_id"] != batch_id:
                    raise PayrollConflictError("幂等键已用于其他工资导出")
                return {**existing, "replayed": True}

            batch = PayrollRepository.get_batch(batch_id, db)
            if not batch:
                raise ValueError("工资批次不存在")
            if batch["status"] != "confirmed" or batch.get("superseded_by_batch_id"):
                raise ValueError("只有未被替代的已确认工资批次可以创建支付清单")

            settlement = Repo.get_by_batch(batch_id, db)
            if settlement and settlement["status"] == "closed":
                raise ValueError("已结账的工资不能再次导出")
            lines = PayrollRepository.list_lines(batch_id, db=db)
            if not lines:
                raise ValueError("工资批次没有员工支付明细")
            total = sum(int(line["payable_wage_cents"] or 0) for line in lines)
            if total != int(batch["payable_wage_cents"] or 0):
                raise ValueError("员工明细合计与工资批次应发金额不一致")

            if settlement:
                current_id = settlement.get("current_export_batch_id")
                if current_id:
                    receipts = Repo.receipt_batch_count(current_id, db)
                    if receipts:
                        raise ValueError("当前支付清单已有回执，不能替代导出版本")
                    old_export = Repo.get_export(current_id, db)
                    if old_export:
                        Repo.supersede_export(current_id, db)
            else:
                settlement = Repo.create_settlement(
                    batch_id, total, actor_id, actor_name, db
                )

            version = Repo.next_export_version(settlement["id"], db)
            rows = []
            for sequence, line in enumerate(lines, start=1):
                rows.append({
                    "employee_line_id": line["id"],
                    "employee_id": line.get("employee_id"),
                    "employee_no_snapshot": line.get("employee_no_snapshot") or "",
                    "employee_name_snapshot": line.get("employee_name_snapshot") or "",
                    "payable_cents": int(line["payable_wage_cents"] or 0),
                    "payment_reference": _payment_reference(batch_id, version, line["id"]),
                    "sequence_no": sequence,
                    "payroll_month": batch["payroll_month"],
                    "payroll_version": batch["version"],
                })
            content = _write_csv(rows)
            digest = _sha256(content)
            export_id = Repo.create_export_batch(
                settlement["id"], version, rows, total, digest, content, key,
                actor_id, actor_name, db,
            )
            Repo.activate_export(settlement["id"], total, export_id, db)
            _emit_event(
                batch_id, "payroll_settlement_export_created", actor_id, actor_name, "",
                {"settlement_id": settlement["id"], "export_batch_id": export_id,
                 "export_version": version, "content_sha256": digest, "row_count": len(rows),
                 "total_cents": total},
                key, db,
            )
            result = Repo.get_export(export_id, db)
            result["settlement_id"] = settlement["id"]
            return result

    @staticmethod
    def download_export(export_id):
        export = Repo.get_export(export_id)
        if not export:
            raise ValueError("工资支付清单不存在")
        content = Repo.get_export_content(export_id)
        if content is None:
            raise ValueError("工资支付清单文件不存在")
        return content

    @staticmethod
    def upload_receipt(export_id, actor_user, idempotency_key, filename, content):
        key = _key(idempotency_key)
        content = bytes(content or b"")
        digest = _sha256(content)
        rows = _parse_receipt(content)
        actor_id, actor_name = _actor(actor_user)
        safe_filename = re.sub(r"[^A-Za-z0-9._-]", "_", str(filename or "receipt.csv"))[:120]
        with BaseService.transaction() as db:
            existing = Repo.get_receipt_by_key(key, db)
            if existing:
                if existing["export_batch_id"] != export_id or existing["content_sha256"] != digest:
                    raise PayrollConflictError("幂等键已用于不同的回执上传")
                return {**existing, "replayed": True}
            same_file = Repo.get_receipt_by_digest(export_id, digest, db)
            if same_file:
                return {**same_file, "replayed": True}

            export = Repo.get_export(export_id, db)
            if not export or export["status"] != "active":
                raise ValueError("只能为当前有效的支付清单上传回执")
            settlement = Repo.get_settlement(export["settlement_id"], db)
            if not settlement or settlement["status"] == "closed":
                raise ValueError("已结账工资不能再接收支付回执")

            valid_count = sum(1 for row in rows if row["validation_status"] == "valid")
            failed_count = len(rows) - valid_count
            status = "accepted" if valid_count else "validation_failed"
            receipt_batch_id = Repo.create_receipt_batch(
                export_id, status, safe_filename, digest, valid_count, failed_count,
                key, actor_id, actor_name, db,
            )
            for row in rows:
                Repo.insert_receipt_item(receipt_batch_id, row, db)
            Repo.mark_receipting(settlement["id"], db)
            batch = PayrollRepository.get_batch(settlement["batch_id"], db)
            _emit_event(
                batch["id"], "payroll_settlement_receipt_uploaded", actor_id, actor_name, "",
                {"settlement_id": settlement["id"], "export_batch_id": export_id,
                 "receipt_batch_id": receipt_batch_id, "content_sha256": digest,
                 "accepted_row_count": valid_count, "failed_row_count": failed_count},
                key, db,
            )
            return Repo.get_receipt_batch_detail(receipt_batch_id, db)

    @staticmethod
    def reconcile(settlement_id, actor_user, idempotency_key):
        key = _key(idempotency_key)
        actor_id, actor_name = _actor(actor_user)
        with BaseService.transaction() as db:
            existing = Repo.get_run_by_key(key, db)
            if existing:
                if existing["settlement_id"] != settlement_id:
                    raise PayrollConflictError("幂等键已用于其他工资对账")
                return {**existing, "items": Repo.list_reconciliation_items(existing["id"], db),
                        "replayed": True}
            settlement = Repo.get_settlement(settlement_id, db)
            if not settlement:
                raise ValueError("工资结算记录不存在")
            if settlement["status"] == "closed":
                raise ValueError("已结账工资不能重新对账")
            export_id = settlement.get("current_export_batch_id")
            export = Repo.get_export(export_id, db) if export_id else None
            if not export or export["status"] != "active":
                raise ValueError("没有当前有效的工资支付清单")

            items = Repo.export_items(export_id, db)
            receipt_items = Repo.receipt_items(export_id, db)
            resolutions = Repo.list_resolutions(settlement_id, export_id, db)
            receipt_digest = _receipt_digest(receipt_items, resolutions)
            excluded_ids = {
                int(row["receipt_item_id"]) for row in resolutions
                if row.get("receipt_item_id") is not None
                and row["resolution_code"] in ("exclude_duplicate", "exclude_unknown_reference")
            }
            accepted_name_ids = {
                int(row["receipt_item_id"]) for row in resolutions
                if row.get("receipt_item_id") is not None
                and row["resolution_code"] == "accept_name_mismatch"
            }
            expected_by_ref = {row["payment_reference"]: row for row in items}
            grouped = {}
            unknown = []
            invalid = []
            for receipt in receipt_items:
                if int(receipt["id"]) in excluded_ids:
                    continue
                if receipt["validation_status"] != "valid":
                    invalid.append(receipt)
                    continue
                if receipt["payment_reference"] not in expected_by_ref:
                    unknown.append(receipt)
                else:
                    grouped.setdefault(receipt["payment_reference"], []).append(receipt)

            version = Repo.next_reconciliation_version(settlement_id, db)
            expected_total = int(export["total_cents"])
            paid_total = 0
            findings = []

            def finding(export_item_id, reference, expected, paid, kind, blocking, detail):
                findings.append({
                    "export_item_id": export_item_id,
                    "payment_reference": reference,
                    "expected_cents": int(expected),
                    "successful_paid_cents": int(paid),
                    "difference_cents": int(expected) - int(paid),
                    "difference_type": kind,
                    "blocking": int(bool(blocking)),
                    "detail_json": _json(detail),
                })

            for export_item in items:
                reference = export_item["payment_reference"]
                expected = int(export_item["payable_cents"])
                receipts = grouped.get(reference, [])
                successes = [row for row in receipts if row["payment_status"] == "success"]
                identity_valid = []
                for receipt in successes:
                    number_mismatch = (
                        bool(export_item["employee_no_snapshot"])
                        and receipt["employee_no_snapshot"] != export_item["employee_no_snapshot"]
                    )
                    name_mismatch = (
                        bool(export_item["employee_name_snapshot"])
                        and receipt["employee_name_snapshot"] != export_item["employee_name_snapshot"]
                    )
                    accepted_name = int(receipt["id"]) in accepted_name_ids
                    if number_mismatch or (name_mismatch and not accepted_name):
                        finding(
                            export_item["id"], reference, expected, int(receipt["paid_cents"] or 0),
                            "employee_mismatch", True,
                            {"receipt_item_id": receipt["id"], "employee_no_mismatch": number_mismatch,
                             "employee_name_mismatch": name_mismatch},
                        )
                    else:
                        identity_valid.append(receipt)

                paid_for_item = sum(int(row["paid_cents"] or 0) for row in identity_valid)
                paid_total += paid_for_item
                if len(identity_valid) > 1:
                    for duplicate in identity_valid[1:]:
                        finding(
                            export_item["id"], reference, expected, int(duplicate["paid_cents"] or 0),
                            "duplicate_success", True,
                            {"receipt_item_id": duplicate["id"], "first_success_receipt_item_id": identity_valid[0]["id"]},
                        )
                if expected != paid_for_item and not (
                    expected > 0 and not identity_valid and any(
                        row["payment_status"] in ("failed", "returned") for row in receipts
                    )
                ):
                    kind = "missing_receipt" if paid_for_item == 0 and expected else (
                        "underpaid" if paid_for_item < expected else "overpaid"
                    )
                    finding(
                        export_item["id"], reference, expected, paid_for_item, kind, True,
                        {"employee_no": export_item["employee_no_snapshot"],
                         "employee_name": export_item["employee_name_snapshot"]},
                    )
                elif expected > 0 and not identity_valid and receipts:
                    finding(
                        export_item["id"], reference, expected, 0, "failed_payment", True,
                        {"payment_statuses": sorted({row["payment_status"] for row in receipts})},
                    )
                elif expected > 0 and not identity_valid and not receipts:
                    finding(
                        export_item["id"], reference, expected, 0, "missing_receipt", True,
                        {"employee_no": export_item["employee_no_snapshot"],
                         "employee_name": export_item["employee_name_snapshot"]},
                    )

            for receipt in unknown:
                finding(
                    None, receipt["payment_reference"], 0, 0, "unknown_reference", True,
                    {"receipt_item_id": receipt["id"], "payment_status": receipt["payment_status"]},
                )
            known_refs = set(expected_by_ref)
            for receipt in invalid:
                if (
                    not receipt["payment_reference"]
                    or receipt["payment_reference"] not in known_refs
                ):
                    finding(
                        None, receipt["payment_reference"], 0, 0, "unknown_reference", True,
                        {"receipt_item_id": receipt["id"], "validation_error": receipt["validation_error"]},
                    )
                elif receipt["payment_reference"] in known_refs and not grouped.get(receipt["payment_reference"]):
                    finding(
                        expected_by_ref[receipt["payment_reference"]]["id"],
                        receipt["payment_reference"],
                        int(expected_by_ref[receipt["payment_reference"]]["payable_cents"]),
                        0, "invalid_amount", True,
                        {"receipt_item_id": receipt["id"], "validation_error": receipt["validation_error"]},
                    )

            difference = expected_total - paid_total
            blocking_count = sum(row["blocking"] for row in findings)
            status = "reconciled" if difference == 0 and blocking_count == 0 else "difference_pending"
            run_id = Repo.create_reconciliation_run(
                settlement_id, export_id, version, status, expected_total, paid_total,
                difference, blocking_count, receipt_digest, key, actor_id, actor_name,
                findings, db,
            )
            Repo.update_reconciliation_summary(
                settlement_id,
                "reconciled" if status == "reconciled" else "difference_pending",
                paid_total, difference, blocking_count, run_id, db,
            )
            batch = PayrollRepository.get_batch(settlement["batch_id"], db)
            _emit_event(
                batch["id"], "payroll_settlement_reconciled", actor_id, actor_name, "",
                {"settlement_id": settlement_id, "export_batch_id": export_id,
                 "reconciliation_run_id": run_id, "run_version": version,
                 "status": status, "expected_total_cents": expected_total,
                 "successful_paid_cents": paid_total, "difference_cents": difference,
                 "blocking_count": blocking_count, "receipt_digest": receipt_digest},
                key, db,
            )
            result = Repo.run_detail(run_id, db)
            return result

    @staticmethod
    def resolve_difference(item_id, actor_user, data):
        actor_id, actor_name = _actor(actor_user)
        code = str(data.get("resolution_code") or "").strip()
        reason = str(data.get("resolution_reason") or "").strip()
        key = _key(data.get("idempotency_key"))
        if not reason:
            raise ValueError("处理差异必须填写原因")
        receipt_item_id = data.get("receipt_item_id")
        try:
            receipt_item_id = int(receipt_item_id) if receipt_item_id is not None else None
        except (TypeError, ValueError) as exc:
            raise ValueError("receipt_item_id 无效") from exc
        with BaseService.transaction() as db:
            previous = Repo.get_resolution_by_key(key, db)
            if previous:
                if previous["reconciliation_item_id"] != item_id:
                    raise PayrollConflictError("幂等键已用于其他差异处理")
                return {**previous, "replayed": True}
            item = Repo.get_reconciliation_item_context(item_id, db)
            if not item:
                raise ValueError("对账差异不存在")
            settlement = Repo.get_settlement(item["settlement_id"], db)
            if not settlement or settlement["status"] == "closed":
                raise ValueError("已结账工资不能处理差异")
            if settlement.get("latest_reconciliation_run_id") != item["run_id"]:
                raise ValueError("只能处理最新对账运行中的差异")
            detail = json.loads(item["detail_json"] or "{}")
            if code == "exclude_duplicate":
                if item["difference_type"] != "duplicate_success":
                    raise ValueError("只有重复成功回执可以排除")
                expected_receipt_id = detail.get("receipt_item_id")
            elif code == "accept_name_mismatch":
                if item["difference_type"] != "employee_mismatch" or detail.get("employee_no_mismatch"):
                    raise ValueError("只有工号一致的姓名差异可以确认")
                expected_receipt_id = detail.get("receipt_item_id")
            elif code == "exclude_unknown_reference":
                if item["difference_type"] != "unknown_reference":
                    raise ValueError("只有未知支付引用可以排除")
                expected_receipt_id = detail.get("receipt_item_id")
            else:
                raise ValueError("差异处理类型无效")
            if receipt_item_id is None:
                receipt_item_id = expected_receipt_id
            if receipt_item_id != expected_receipt_id:
                raise ValueError("处理记录与差异来源不匹配")
            receipt = Repo.get_receipt_item_export(receipt_item_id, db)
            if not receipt or receipt["export_batch_id"] != item["export_batch_id"]:
                raise ValueError("差异回执来源无效")
            Repo.create_resolution(
                item_id, receipt_item_id, code, reason, key, actor_id, actor_name, db
            )
            Repo.mark_receipting(item["settlement_id"], db)
            batch = PayrollRepository.get_batch(settlement["batch_id"], db)
            _emit_event(
                batch["id"], "payroll_settlement_difference_resolved", actor_id, actor_name,
                reason, {"settlement_id": item["settlement_id"], "reconciliation_item_id": item_id,
                         "receipt_item_id": receipt_item_id, "resolution_code": code},
                key, db,
            )
            return {"ok": True, "reconciliation_item_id": item_id, "resolution_code": code}

    @staticmethod
    def close(settlement_id, actor_user, data):
        actor_id, actor_name = _actor(actor_user)
        key = _key(data.get("idempotency_key"))
        reason = str(data.get("close_reason") or "").strip()
        if not reason:
            raise ValueError("结账必须填写说明")
        try:
            expected_version = int(data.get("row_version"))
        except (TypeError, ValueError) as exc:
            raise ValueError("缺少有效的 row_version") from exc
        with BaseService.transaction() as db:
            existing = Repo.get_close_record_by_key(key, db)
            if existing:
                if existing["settlement_id"] != settlement_id:
                    raise PayrollConflictError("幂等键已用于其他工资结账")
                return {**existing, "replayed": True}
            settlement = Repo.get_settlement(settlement_id, db)
            if not settlement:
                raise ValueError("工资结算记录不存在")
            if settlement["status"] == "closed":
                raise ValueError("工资结算已经结账")
            if int(settlement["row_version"]) != expected_version:
                raise PayrollConflictError("工资结算版本冲突，请刷新后重试")
            run = Repo.latest_run(settlement_id, db)
            export_id = settlement.get("current_export_batch_id")
            export = Repo.get_export(export_id, db) if export_id else None
            if (
                settlement["status"] != "reconciled" or not run
                or run["status"] != "reconciled" or run["export_batch_id"] != export_id
                or not export or export["status"] != "active"
            ):
                raise ValueError("只有最新对账完全通过的工资结算可以结账")
            receipts = Repo.receipt_items(export_id, db)
            resolutions = Repo.list_resolutions(settlement_id, export_id, db)
            if _receipt_digest(receipts, resolutions) != run["receipt_digest"]:
                raise ValueError("回执或差异处理记录已变化，请重新对账")
            if int(run["expected_total_cents"]) != int(run["successful_paid_cents"]) or run["blocking_count"]:
                raise ValueError("工资应付与成功支付不一致，不能结账")
            close_digest = _sha256(_json({
                "settlement_id": settlement_id,
                "export_batch_id": export_id,
                "reconciliation_run_id": run["id"],
                "expected_total_cents": run["expected_total_cents"],
                "successful_paid_cents": run["successful_paid_cents"],
                "receipt_digest": run["receipt_digest"],
            }).encode("utf-8"))
            close_record_id = Repo.create_close_record(
                settlement_id, export_id, run["id"], run["expected_total_cents"],
                run["successful_paid_cents"], close_digest, reason, key,
                actor_id, actor_name, db,
            )
            if Repo.mark_closed(settlement_id, expected_version, db) != 1:
                raise PayrollConflictError("工资结算版本冲突，请刷新后重试")
            batch = PayrollRepository.get_batch(settlement["batch_id"], db)
            _emit_event(
                batch["id"], "payroll_settlement_closed", actor_id, actor_name, reason,
                {"settlement_id": settlement_id, "close_record_id": close_record_id,
                 "export_batch_id": export_id, "reconciliation_run_id": run["id"],
                 "close_digest": close_digest, "expected_total_cents": run["expected_total_cents"]},
                key, db,
            )
            return Repo.get_close_record_by_id(close_record_id, db)
