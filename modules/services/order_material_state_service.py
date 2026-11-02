"""Immutable snapshot and order-common consumption evidence without schema changes."""

import hashlib
import json
import math
from decimal import Decimal, InvalidOperation

from modules.audit_writer import AuditCommand, AuditWriter
from modules.domain.errors import ConflictError, NotFoundError
from modules.repositories.order_material_state_repository import (
    OrderMaterialStateRepository,
)


class OrderMaterialStateService:
    """Freeze order-common material obligations inside the stock transaction."""

    SNAPSHOT_ACTION = "material_order_snapshot_initialized"
    COMMON_ACTION = "material_order_common_basis"
    COMMON_SOURCE = "order_common_consumption"
    _ENVELOPE_FIELDS = (
        "event_id", "user_id", "action", "target_type", "target_id",
        "detail", "category", "severity", "mandatory", "schema_version",
        "redaction_version", "request_id",
    )

    @staticmethod
    def _transaction(db):
        if db is None or not db.in_transaction:
            raise ValueError("order material state requires the caller's transaction")

    @staticmethod
    def _conflict(code, message, order_id, **details):
        raise ConflictError(message, details={"code": code, "order_id": order_id, **details})

    @classmethod
    def _invalid(cls, order_id):
        cls._conflict(
            "MATERIAL_STATE_INVALID", "订单物料状态证据缺失、损坏或不一致，禁止自动扣料", order_id
        )

    @staticmethod
    def _event_id(action, order_id):
        return f"{action}:v1:{order_id}"

    @staticmethod
    def _json(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _seal(cls, payload):
        body = {key: value for key, value in payload.items() if key != "digest"}
        return {
            **body,
            "digest": hashlib.sha256(cls._json(body).encode("utf-8")).hexdigest(),
        }

    @classmethod
    def _strict_json(cls, raw):
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate evidence field")
                result[key] = value
            return result

        def invalid_constant(value):
            raise ValueError(f"invalid JSON number: {value}")

        return json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)

    @classmethod
    def _positive_id(cls, value, order_id):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            cls._invalid(order_id)
        return value

    @classmethod
    def _number(cls, value, order_id):
        try:
            if isinstance(value, bool):
                raise ValueError("boolean quantity")
            number = Decimal(str(value))
            stored = float(number)
            if (
                not number.is_finite() or number <= 0
                or not math.isfinite(stored) or stored <= 0
            ):
                raise ValueError("invalid quantity")
            return format(number.normalize(), "f")
        except (InvalidOperation, ValueError, TypeError, OverflowError):
            cls._invalid(order_id)

    @classmethod
    def _common_rows(cls, rows, order_id):
        if not isinstance(rows, (list, tuple)):
            cls._invalid(order_id)
        quantities = {}
        for raw in rows:
            try:
                row = dict(raw)
            except (TypeError, ValueError):
                cls._invalid(order_id)
            if row.get("process_id") is not None:
                cls._invalid(order_id)
            material_id = cls._positive_id(row.get("material_id"), order_id)
            quantity = Decimal(cls._number(row.get("quantity_per_unit"), order_id))
            quantities[material_id] = quantities.get(material_id, Decimal(0)) + quantity
        return [
            {
                "material_id": material_id,
                "scope": "order",
                "quantity_per_unit": cls._number(quantity, order_id),
            }
            for material_id, quantity in sorted(quantities.items())
        ]

    @classmethod
    def _read_event(cls, action, order_id, db):
        event_id = cls._event_id(action, order_id)
        live, archived = OrderMaterialStateRepository.event_records(event_id, db=db)
        envelopes = list(live)
        try:
            for archive in archived:
                envelope = cls._strict_json(archive["payload"])
                if not isinstance(envelope, dict) or envelope.get("event_id") != event_id:
                    cls._invalid(order_id)
                envelopes.append(envelope)
            canonical = None
            detail = None
            for envelope in envelopes:
                if any(key not in envelope for key in cls._ENVELOPE_FIELDS):
                    cls._invalid(order_id)
                if (
                    envelope["event_id"] != event_id
                    or envelope["action"] != action
                    or envelope["target_type"] != "order"
                    or type(envelope["target_id"]) is not int
                    or envelope["target_id"] != order_id
                    or type(envelope["schema_version"]) is not int
                    or envelope["schema_version"] != 1
                    or type(envelope["mandatory"]) is not int
                    or envelope["mandatory"] != 1
                    or type(envelope["redaction_version"]) is not int
                    or envelope["redaction_version"] != 1
                    or envelope["category"] != "inventory"
                ):
                    cls._invalid(order_id)
                payload = cls._strict_json(envelope["detail"])
                if (
                    not isinstance(payload, dict)
                    or type(payload.get("schema_version")) is not int
                    or payload.get("schema_version") != 1
                    or type(payload.get("order_id")) is not int
                    or payload.get("order_id") != order_id
                    or payload.get("digest") != cls._seal(payload)["digest"]
                ):
                    cls._invalid(order_id)
                identity = {
                    key: payload if key == "detail" else envelope[key]
                    for key in cls._ENVELOPE_FIELDS
                }
                if canonical is not None and identity != canonical:
                    cls._invalid(order_id)
                canonical, detail = identity, payload
            return detail
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            if isinstance(exc, ConflictError):
                raise
            cls._invalid(order_id)

    @classmethod
    def _write_event(cls, action, order_id, payload, user_id, db):
        try:
            AuditWriter.required(
                AuditCommand.create(
                    user_id, action, "order", order_id, cls._seal(payload),
                    event_id=cls._event_id(action, order_id),
                ),
                db=db,
            )
        except Exception as exc:
            # Preserve rollback without exposing storage constraints as business conflicts.
            raise RuntimeError("订单物料状态审计写入失败") from exc

    @classmethod
    def _snapshot_event(cls, order_id, db):
        event = cls._read_event(cls.SNAPSHOT_ACTION, order_id, db)
        if event is not None:
            if (
                set(event) != {
                    "schema_version", "order_id", "product_id", "row_count", "digest"
                }
                or type(event["row_count"]) is not int
                or event["row_count"] < 0
            ):
                cls._invalid(order_id)
            if event["product_id"] is not None:
                cls._positive_id(event["product_id"], order_id)
        return event

    @classmethod
    def assert_can_initialize(cls, order_id, db):
        """BOM copying is a one-time initialization, not a live recipe refresh."""
        cls._transaction(db)
        if (
            cls._snapshot_event(order_id, db) is not None
            or OrderMaterialStateRepository.snapshot_rows(order_id, db=db)
        ):
            cls._conflict(
                "MATERIAL_SNAPSHOT_ALREADY_INITIALIZED", "订单物料快照已生成，禁止重新复制配方",
                order_id,
            )

    @classmethod
    def mark_initialized(cls, order_id, product_id, row_count, db):
        cls._transaction(db)
        if cls._snapshot_event(order_id, db) is not None:
            return
        if OrderMaterialStateRepository.find_order(order_id, db=db) is None:
            raise NotFoundError("订单不存在")
        if type(row_count) is not int or row_count < 0:
            cls._invalid(order_id)
        if product_id is not None:
            cls._positive_id(product_id, order_id)
        if len(OrderMaterialStateRepository.snapshot_rows(order_id, db=db)) != row_count:
            cls._invalid(order_id)
        cls._write_event(
            cls.SNAPSHOT_ACTION, order_id,
            {
                "schema_version": 1, "order_id": order_id,
                "product_id": product_id, "row_count": row_count,
            },
            None, db,
        )

    @classmethod
    def assert_snapshot_known(cls, order_id, rows, db):
        cls._transaction(db)
        event = cls._snapshot_event(order_id, db)
        if not rows and event is None:
            cls._conflict(
                "MATERIAL_SNAPSHOT_UNKNOWN",
                "历史订单缺少物料快照完成证据，禁止回退实时产品配方", order_id,
            )

    @classmethod
    def _current_basis(cls, order_id, common_rows, work_record_id, db):
        order = OrderMaterialStateRepository.find_order(order_id, db=db)
        if order is None:
            raise NotFoundError("订单不存在")
        snapshot = OrderMaterialStateRepository.snapshot_rows(order_id, db=db)
        cls.assert_snapshot_known(order_id, snapshot, db)
        if any(row["process_id"] == 0 for row in snapshot):
            cls._invalid(order_id)
        actual = cls._common_rows(
            [row for row in snapshot if row["process_id"] is None], order_id
        )
        supplied = cls._common_rows(common_rows, order_id)
        if len(actual) != len(supplied) or any(
            left["material_id"] != right["material_id"]
            or not cls._same_quantity(
                left["quantity_per_unit"], right["quantity_per_unit"], order_id
            )
            for left, right in zip(actual, supplied)
        ):
            cls._conflict("STALE_INPUT", "订单通用物料配方已变化，请重新读取", order_id)
        if work_record_id is not None:
            cls._positive_id(work_record_id, order_id)
        return cls._seal({
            "schema_version": 1, "order_id": order_id,
            "order_quantity": cls._number(order["quantity"], order_id),
            "common_rows": actual, "work_record_id": work_record_id,
        })

    @classmethod
    def _allocations(cls, allocations, order_id):
        if not isinstance(allocations, (list, tuple)):
            cls._invalid(order_id)
        normalized = []
        for allocation in allocations:
            if not isinstance(allocation, dict) or set(allocation) != {
                "material_id", "quantity", "consumption_id", "log_id"
            }:
                cls._invalid(order_id)
            normalized.append({
                "material_id": cls._positive_id(allocation["material_id"], order_id),
                "quantity": cls._number(allocation["quantity"], order_id),
                "consumption_id": cls._positive_id(allocation["consumption_id"], order_id),
                "log_id": cls._positive_id(allocation["log_id"], order_id),
            })
        for key in ("material_id", "consumption_id", "log_id"):
            if len({row[key] for row in normalized}) != len(normalized):
                cls._invalid(order_id)
        return sorted(normalized, key=lambda row: row["material_id"])

    @classmethod
    def _same_quantity(cls, left, right, order_id):
        return math.isclose(
            float(cls._number(left, order_id)), float(cls._number(right, order_id)),
            rel_tol=1e-12, abs_tol=0,
        )

    @classmethod
    def _out_balance_matches(cls, log, order_id):
        balances = []
        for key in ("balance_before", "balance_after"):
            try:
                raw = log[key]
                if isinstance(raw, bool):
                    raise ValueError("boolean balance")
                value = Decimal(str(raw))
                stored = float(value)
                if (
                    not value.is_finite() or value < 0 or not math.isfinite(stored)
                    or (value > 0 and stored <= 0)
                ):
                    raise ValueError("invalid balance")
                balances.append(stored)
            except (InvalidOperation, ValueError, TypeError, OverflowError, KeyError):
                cls._invalid(order_id)
        before, after = balances
        quantity = float(cls._number(log["quantity"], order_id))
        # SQLite stores REAL balances, so subtraction can round at their magnitude.
        # Use representable steps at that magnitude; a fixed epsilon hides tiny losses.
        tolerance = 2 * max(math.ulp(before), math.ulp(after), math.ulp(quantity))
        return (
            quantity <= before and after <= before
            and abs((before - quantity) - after) <= tolerance
        )

    @classmethod
    def _validate_common_event(cls, event, order_id):
        if (
            not isinstance(event, dict)
            or set(event) != {
                "schema_version", "order_id", "order_quantity", "common_rows",
                "work_record_id", "allocations", "digest",
            }
            or type(event["schema_version"]) is not int
            or event["schema_version"] != 1
            or type(event["order_id"]) is not int
            or event["order_id"] != order_id
        ):
            cls._invalid(order_id)
        if event["work_record_id"] is not None:
            cls._positive_id(event["work_record_id"], order_id)
        if cls._number(event["order_quantity"], order_id) != event["order_quantity"]:
            cls._invalid(order_id)
        if not isinstance(event["common_rows"], list) or not isinstance(event["allocations"], list):
            cls._invalid(order_id)
        rows = []
        for row in event["common_rows"]:
            if not isinstance(row, dict) or set(row) != {
                "material_id", "scope", "quantity_per_unit"
            } or row["scope"] != "order":
                cls._invalid(order_id)
            rows.append({**row, "process_id": None})
        if cls._common_rows(rows, order_id) != event["common_rows"]:
            cls._invalid(order_id)
        if cls._allocations(event["allocations"], order_id) != event["allocations"]:
            cls._invalid(order_id)
        expected = {row["material_id"]: row for row in event["common_rows"]}
        if set(expected) != {row["material_id"] for row in event["allocations"]}:
            cls._invalid(order_id)
        for allocation in event["allocations"]:
            required = Decimal(event["order_quantity"]) * Decimal(
                expected[allocation["material_id"]]["quantity_per_unit"]
            )
            if not cls._same_quantity(required, allocation["quantity"], order_id):
                cls._invalid(order_id)

    @classmethod
    def _validate_consumptions(cls, event, order_id, db):
        cls._validate_common_event(event, order_id)
        allocations = event["allocations"]
        consumptions = {
            row["id"]: row for row in OrderMaterialStateRepository.consumptions(order_id, db=db)
        }
        sources = OrderMaterialStateRepository.source_logs(order_id, db=db)
        common_logs = [row for row in sources if row["source_type"] == cls.COMMON_SOURCE]
        if {row["id"] for row in common_logs} != {row["log_id"] for row in allocations}:
            cls._invalid(order_id)
        by_id = {
            row["id"]: row for row in OrderMaterialStateRepository.logs_by_ids(
                [row["log_id"] for row in allocations], db=db
            )
        }
        for allocation in allocations:
            consumption = consumptions.get(allocation["consumption_id"])
            log = by_id.get(allocation["log_id"])
            if consumption is None or log is None:
                cls._invalid(order_id)
            if consumption["status"] == "reversed":
                cls._conflict(
                    "COMMON_CONSUMPTION_REVERSED",
                    "订单通用物料已撤销，须经人工核实处理，禁止自动重扣",
                    order_id, consumption_id=consumption["id"],
                )
            originals = [
                row for row in sources
                if row["source_id"] == consumption["id"]
                and row["source_type"] in ("consumption", "auto_consumption", cls.COMMON_SOURCE)
            ]
            if (
                consumption["status"] != "active"
                or consumption["process_id"] is not None
                or consumption["source_work_record_id"] is not None
                or consumption["material_id"] != allocation["material_id"]
                or not cls._same_quantity(consumption["quantity"], allocation["quantity"], order_id)
                or len(originals) != 1
                or log["type"] != "out"
                or log["source_type"] != cls.COMMON_SOURCE
                or log["source_id"] != consumption["id"]
                or log["material_id"] != allocation["material_id"]
                or log["reversal_of_log_id"] is not None
                or not cls._same_quantity(log["quantity"], allocation["quantity"], order_id)
                or not cls._out_balance_matches(log, order_id)
                or any(row["source_type"] == "consumption_reversal"
                       and row["source_id"] == consumption["id"] for row in sources)
            ):
                cls._invalid(order_id)

    @classmethod
    def prepare_common_basis(cls, order_id, common_rows, work_record_id, db):
        cls._transaction(db)
        current = cls._current_basis(order_id, common_rows, work_record_id, db)
        existing = cls._read_event(cls.COMMON_ACTION, order_id, db)
        if existing is not None:
            cls._validate_consumptions(existing, order_id, db)
            if any(existing[key] != current[key] for key in ("order_quantity", "common_rows")):
                cls._conflict("STALE_INPUT", "订单数量或通用物料配方与扣料时已不一致", order_id)
            if work_record_id is not None and existing["work_record_id"] == work_record_id:
                cls._conflict(
                    "COMMON_CONSUMPTION_ALREADY_RECORDED", "该报工记录已处理订单通用物料",
                    order_id, work_record_id=work_record_id,
                    consumption_ids=[row["consumption_id"] for row in existing["allocations"]],
                )
            return None

        sources = OrderMaterialStateRepository.source_logs(order_id, db=db)
        if any(row["source_type"] == cls.COMMON_SOURCE for row in sources):
            cls._invalid(order_id)
        if current["common_rows"]:
            consumptions = OrderMaterialStateRepository.consumptions(order_id, db=db)
            if (
                any(row["source_type"] == "auto_consumption" for row in sources)
                or any(row["source_work_record_id"] is not None for row in consumptions)
                or OrderMaterialStateRepository.has_prior_approved_normal_report(
                    order_id, work_record_id, db=db
                )
            ):
                cls._conflict(
                    "LEGACY_AMBIGUOUS",
                    "历史报工或自动耗料无法证明通用物料尚未扣除，禁止自动补扣", order_id,
                )
        return current

    @classmethod
    def record_common_basis(cls, order_id, basis, allocations, user_id, db):
        cls._transaction(db)
        if cls._read_event(cls.COMMON_ACTION, order_id, db) is not None:
            cls._invalid(order_id)
        if not isinstance(basis, dict) or set(basis) != {
            "schema_version", "order_id", "order_quantity", "common_rows",
            "work_record_id", "digest",
        } or basis.get("digest") != cls._seal(basis)["digest"]:
            cls._invalid(order_id)
        event = cls._seal({
            **basis, "allocations": cls._allocations(allocations, order_id),
        })
        cls._validate_common_event(event, order_id)
        common_rows = [
            {**row, "process_id": None} for row in basis["common_rows"]
        ]
        if basis != cls._current_basis(order_id, common_rows, basis["work_record_id"], db):
            cls._conflict("STALE_INPUT", "订单物料冻结依据已变化", order_id)
        cls._validate_consumptions(event, order_id, db)
        cls._write_event(cls.COMMON_ACTION, order_id, event, user_id, db)

    @classmethod
    def assert_common_mutable(cls, order_id, db):
        cls._transaction(db)
        existing = cls._read_event(cls.COMMON_ACTION, order_id, db)
        if existing is not None:
            cls._validate_consumptions(existing, order_id, db)
            cls._conflict(
                "STALE_INPUT", "订单通用物料已冻结，禁止修改订单数量或通用配方", order_id
            )
        if any(
            row["source_type"] == cls.COMMON_SOURCE
            for row in OrderMaterialStateRepository.source_logs(order_id, db=db)
        ):
            cls._invalid(order_id)
