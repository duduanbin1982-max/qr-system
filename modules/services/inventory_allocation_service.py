"""Read-only product inventory allocation preview orchestration.

The preview intentionally does not reserve or post stock.  A later outbound
use case may consume the same immutable preview digest inside one transaction.
"""

import hashlib
import json
from decimal import Decimal

from modules import config
from modules.domain.errors import (
    ConflictError,
    InventoryAllocationPreviewDisabledError,
    InventoryAllocationValidationError,
    NotFoundError,
)
from modules.domain.inventory_allocation import (
    AllocationShortage,
    InventoryCandidate,
    allocate_inventory_sources,
)
from modules.repositories.inventory_product_repository import (
    InventoryProductRepository,
)
from modules.repositories.inventory_repository import InventoryRepository
from modules.repositories.audit_log_repository import AuditLogRepository
from modules.services import BaseService
from modules.services.inventory_posting_service import InventoryPostingService


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _decimal_text(value):
    decimal = Decimal(str(value))
    text = format(decimal, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


class InventoryAllocationService:
    @staticmethod
    def _ensure_enabled():
        if not config.INVENTORY_ALLOCATION_PREVIEW_ENABLED:
            raise InventoryAllocationPreviewDisabledError(
                "库存来源分配预览尚未启用"
            )

    @classmethod
    def preview(
        cls,
        product_id,
        quantity,
        *,
        mode="fifo",
        compatibility_key="",
        selected_inventory_ids=(),
        reason="",
        db=None,
    ):
        cls._ensure_enabled()
        try:
            product_id = int(product_id)
            requested = Decimal(str(quantity))
        except (TypeError, ValueError):
            raise InventoryAllocationValidationError("产品和申请数量格式无效")
        if product_id <= 0 or requested <= 0:
            raise InventoryAllocationValidationError("产品和申请数量必须大于零")
        mode = (mode or "fifo").strip().lower()
        compatibility_key = (compatibility_key or "").strip()
        reason = (reason or "").strip()
        if mode not in {"fifo", "manual"}:
            raise InventoryAllocationValidationError("分配模式必须为 fifo 或 manual")
        if mode == "manual" and not selected_inventory_ids:
            raise InventoryAllocationValidationError("人工分配必须选择库存来源")
        product = InventoryProductRepository.get_product(product_id, db=db)
        if not product:
            raise NotFoundError("产品不存在")
        rows = InventoryProductRepository.list_allocation_candidates(
            product_id, compatibility_key=compatibility_key
            , db=db
        )
        if not compatibility_key:
            compatibility_keys = sorted({row["compatibility_key"] for row in rows})
            if len(compatibility_keys) != 1:
                raise InventoryAllocationValidationError(
                    "产品存在多个兼容库存分组，请先选择兼容分组",
                    details={"compatibility_group_count": len(compatibility_keys)},
                )
            compatibility_key = compatibility_keys[0] if compatibility_keys else ""
            if compatibility_key:
                rows = InventoryProductRepository.list_allocation_candidates(
                    product_id, compatibility_key=compatibility_key
                    , db=db
                )
        candidates = tuple(
            InventoryCandidate(
                inventory_id=int(row["inventory_id"]),
                order_id=row["order_id"],
                order_no=row["order_no"] or "",
                available_quantity=Decimal(str(row["available_quantity"] or 0)),
                received_at=row["received_at"] or "",
                lot_no=row["lot_no"] or "",
                serial_no=row["serial_no"] or "",
                location=row["location"] or "",
                compatibility_key=row["compatibility_key"],
                manual_rank=(index + 1 if mode == "manual" else None),
            )
            for index, row in enumerate(rows)
        )
        selected = tuple(sorted({int(item) for item in selected_inventory_ids}))
        if mode == "manual":
            candidate_ids = {item.inventory_id for item in candidates}
            invalid = [item for item in selected if item not in candidate_ids]
            if invalid:
                raise InventoryAllocationValidationError(
                    "人工分配来源不属于当前产品或兼容分组",
                    details={"invalid_inventory_ids": invalid},
                )
        try:
            result = allocate_inventory_sources(
                candidates,
                requested,
                mode=mode,
                compatibility_key=compatibility_key,
                selected_inventory_ids=selected,
            )
        except AllocationShortage as exc:
            raise InventoryAllocationValidationError(
                "可用库存不足，无法生成完整分配预览",
                details={
                    "requested_quantity": _decimal_text(exc.requested),
                    "available_quantity": _decimal_text(exc.available),
                    "shortage": _decimal_text(exc.shortage),
                },
            )
        except ValueError as exc:
            raise InventoryAllocationValidationError(str(exc))

        items = [
            {
                "sequence_no": index,
                "inventory_id": item.inventory_id,
                "source_order_id": item.order_id,
                "order_no": item.order_no,
                "lot_no": item.lot_no,
                "serial_no": item.serial_no,
                "location": item.location,
                "allocated_quantity": _decimal_text(item.quantity),
            }
            for index, item in enumerate(result.items, start=1)
        ]
        request_payload = {
            "product_id": product_id,
            "compatibility_key": compatibility_key,
            "mode": mode,
            "requested_quantity": str(requested),
            "selected_inventory_ids": list(selected),
        }
        candidate_payload = [
            {
                "inventory_id": item.inventory_id,
                "order_id": item.order_id,
                "available_quantity": str(item.available_quantity),
                "received_at": item.received_at,
                "compatibility_key": item.compatibility_key,
            }
            for item in candidates
        ]
        return {
            "product": dict(product),
            "mode": mode,
            "compatibility_key": compatibility_key,
            "requested_quantity": _decimal_text(result.requested_quantity),
            "available_quantity": _decimal_text(result.available_quantity),
            "allocated_quantity": _decimal_text(sum((Decimal(i["allocated_quantity"]) for i in items), Decimal("0"))),
            "items": items,
            "request_digest": _digest(request_payload),
            "candidate_digest": _digest(candidate_payload),
            "preview_digest": _digest({"request": request_payload, "candidates": candidate_payload, "items": items}),
            "read_only": True,
        }

    @classmethod
    def outbound(
        cls,
        product_id,
        quantity,
        *,
        idempotency_key,
        operator_id=None,
        operator_name="",
        mode="fifo",
        compatibility_key="",
        selected_inventory_ids=(),
        reason="",
        preview_digest="",
        order_id=None,
        order_no="",
    ):
        if not config.INVENTORY_CROSS_ORDER_OUTBOUND_ENABLED:
            raise ConflictError("跨订单产品出库尚未启用")
        idempotency_key = (idempotency_key or "").strip()
        if not idempotency_key:
            raise InventoryAllocationValidationError("正式出库必须提供幂等键")
        preview_digest = (preview_digest or "").strip()
        if not preview_digest:
            raise InventoryAllocationValidationError("正式出库必须提供预览摘要")
        with BaseService.transaction() as txn:
            existing = InventoryRepository.find_allocation_run_by_idempotency(
                idempotency_key, db=txn
            )
            if existing:
                expected = cls._request_digest(
                    product_id, quantity, mode, compatibility_key,
                    selected_inventory_ids, reason, order_id, order_no,
                )
                if existing["request_digest"] != expected:
                    raise ConflictError("幂等键已用于其他库存分配")
                return cls._run_payload(existing, db=txn, idempotent=True)

            preview = cls.preview(
                product_id,
                quantity,
                mode=mode,
                compatibility_key=compatibility_key,
                selected_inventory_ids=selected_inventory_ids,
                reason=reason,
                db=txn,
            )
            if preview_digest != preview["preview_digest"]:
                raise ConflictError("库存预览已变化，请重新生成预览")
            request_digest = cls._request_digest(
                product_id, quantity, mode, compatibility_key,
                selected_inventory_ids, reason, order_id, order_no,
            )
            result_digest = _digest({"preview_digest": preview["preview_digest"], "items": preview["items"]})
            run_id = InventoryRepository.insert_allocation_run_txn(
                {
                    "idempotency_key": idempotency_key,
                    "request_digest": request_digest,
                    "preview_digest": preview["preview_digest"],
                    "result_digest": result_digest,
                    "product_id": int(product_id),
                    "compatibility_key": preview.get("compatibility_key", compatibility_key),
                    "mode": preview["mode"],
                    "requested_quantity": float(quantity),
                    "reason": reason,
                    "operator_id": operator_id,
                    "operator_name": operator_name,
                },
                txn,
            )
            for index, item in enumerate(preview["items"], start=1):
                movement = InventoryPostingService.post(
                    item["inventory_id"],
                    -float(item["allocated_quantity"]),
                    "out",
                    order_id=order_id,
                    order_no=order_no,
                    remark=reason or "产品视图跨订单出库",
                    operator_id=operator_id,
                    operator_name=operator_name,
                    lot_no=item.get("lot_no", ""),
                    serial_no=item.get("serial_no", ""),
                    source_type="inventory_allocation",
                    source_id=run_id,
                    idempotency_key=f"{idempotency_key}:movement:{index}",
                    db=txn,
                )
                InventoryRepository.insert_allocation_item_txn(
                    {
                        "run_id": run_id,
                        "sequence_no": index,
                        "inventory_id": item["inventory_id"],
                        "source_order_id": item.get("source_order_id"),
                        "order_no": item.get("order_no", ""),
                        "lot_no": item.get("lot_no", ""),
                        "serial_no": item.get("serial_no", ""),
                        "location": item.get("location", ""),
                        "allocated_quantity": float(item["allocated_quantity"]),
                        "movement_id": movement["id"],
                        "balance_before": movement["balance_before"],
                        "balance_after": movement["balance_after"],
                    },
                    txn,
                )
            AuditLogRepository.enqueue_event_txn(
                operator_id,
                "inventory_allocation_outbound",
                "inventory_allocation_run",
                run_id,
                {"product_id": product_id, "quantity": quantity, "mode": mode, "idempotency_key": idempotency_key},
                db=txn,
                request_id=idempotency_key,
            )
            saved = InventoryRepository.find_allocation_run(run_id, db=txn)
            return cls._run_payload(saved, db=txn, idempotent=False)

    @staticmethod
    def _request_digest(product_id, quantity, mode, compatibility_key, selected_inventory_ids, reason, order_id, order_no):
        return _digest({
            "product_id": int(product_id), "quantity": _decimal_text(quantity),
            "mode": (mode or "fifo").strip().lower(), "compatibility_key": compatibility_key or "",
            "selected_inventory_ids": sorted({int(item) for item in selected_inventory_ids}),
            "reason": reason or "", "order_id": order_id, "order_no": order_no or "",
        })

    @staticmethod
    def _run_payload(run, *, db, idempotent):
        if not run:
            raise NotFoundError("库存分配运行不存在")
        payload = dict(run)
        payload["items"] = [dict(item) for item in InventoryRepository.list_allocation_items(run["id"], db=db)]
        payload["idempotent_replay"] = idempotent
        return payload

    @classmethod
    def list_runs(cls, *, product_id=None, page=1, limit=50):
        rows, total = InventoryRepository.list_allocation_runs(
            product_id=product_id, page=page, limit=limit
        )
        return {"items": [dict(row) for row in rows], "total": total, "page": max(int(page), 1), "limit": max(1, min(int(limit), 200))}

    @classmethod
    def reverse(
        cls,
        run_id,
        *,
        idempotency_key,
        operator_id=None,
        operator_name="",
        reason="",
    ):
        if not config.INVENTORY_CROSS_ORDER_OUTBOUND_ENABLED:
            raise ConflictError("跨订单产品出库尚未启用")
        idempotency_key = (idempotency_key or "").strip()
        if not idempotency_key:
            raise InventoryAllocationValidationError("撤销必须提供幂等键")
        with BaseService.transaction() as txn:
            original = InventoryRepository.find_allocation_run(run_id, db=txn)
            if not original:
                raise NotFoundError("库存分配运行不存在")
            if original["mode"] == "reversal":
                raise InventoryAllocationValidationError("不能撤销一条撤销运行")
            prior_reversal = InventoryRepository.find_reversal_run(run_id, db=txn)
            if prior_reversal:
                if prior_reversal["idempotency_key"] == idempotency_key:
                    return cls._run_payload(prior_reversal, db=txn, idempotent=True)
                raise ConflictError("该库存分配已经撤销，不能重复撤销")
            existing = InventoryRepository.find_allocation_run_by_idempotency(
                idempotency_key, db=txn
            )
            if existing:
                if existing["reversal_of_run_id"] != run_id:
                    raise ConflictError("幂等键已用于其他撤销操作")
                return cls._run_payload(existing, db=txn, idempotent=True)
            original_items = InventoryRepository.list_allocation_items(run_id, db=txn)
            result_items = [
                {
                    "inventory_id": item["inventory_id"],
                    "allocated_quantity": item["allocated_quantity"],
                    "source_order_id": item["source_order_id"],
                    "order_no": item["order_no_snapshot"],
                    "lot_no": item["lot_no"],
                    "serial_no": item["serial_no"],
                    "location": item["location_snapshot"],
                }
                for item in original_items
            ]
            request_digest = _digest({"reversal_of_run_id": run_id, "reason": reason or ""})
            preview_digest = original["preview_digest"]
            result_digest = _digest({"reversal_of_run_id": run_id, "items": result_items})
            reversal_id = InventoryRepository.insert_allocation_run_txn(
                {
                    "idempotency_key": idempotency_key,
                    "request_digest": request_digest,
                    "preview_digest": preview_digest,
                    "result_digest": result_digest,
                    "product_id": original["product_id"],
                    "compatibility_key": original["compatibility_key"],
                    "mode": "reversal",
                    "requested_quantity": original["requested_quantity"],
                    "reason": reason or "撤销库存来源分配",
                    "operator_id": operator_id,
                    "operator_name": operator_name,
                    "reversal_of_run_id": run_id,
                },
                txn,
            )
            for index, item in enumerate(result_items, start=1):
                movement = InventoryPostingService.post(
                    item["inventory_id"],
                    float(item["allocated_quantity"]),
                    "in",
                    order_id=item["source_order_id"],
                    order_no=item["order_no"],
                    remark=reason or "撤销产品视图跨订单出库",
                    operator_id=operator_id,
                    operator_name=operator_name,
                    lot_no=item["lot_no"],
                    serial_no=item["serial_no"],
                    source_type="inventory_allocation_reversal",
                    source_id=reversal_id,
                    idempotency_key=f"{idempotency_key}:movement:{index}",
                    reversal_of_id=original_items[index - 1]["movement_id"],
                    db=txn,
                )
                InventoryRepository.insert_allocation_item_txn(
                    {
                        "run_id": reversal_id,
                        "sequence_no": index,
                        "inventory_id": item["inventory_id"],
                        "source_order_id": item["source_order_id"],
                        "order_no": item["order_no"],
                        "lot_no": item["lot_no"],
                        "serial_no": item["serial_no"],
                        "location": item["location"],
                        "allocated_quantity": item["allocated_quantity"],
                        "movement_id": movement["id"],
                        "balance_before": movement["balance_before"],
                        "balance_after": movement["balance_after"],
                    },
                    txn,
                )
            AuditLogRepository.enqueue_event_txn(
                operator_id,
                "inventory_allocation_reversal",
                "inventory_allocation_run",
                reversal_id,
                {"reversal_of_run_id": run_id, "idempotency_key": idempotency_key},
                db=txn,
                request_id=idempotency_key,
            )
            return cls._run_payload(
                InventoryRepository.find_allocation_run(reversal_id, db=txn),
                db=txn,
                idempotent=False,
            )
