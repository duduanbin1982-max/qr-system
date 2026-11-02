"""
qr-system — 客户管理 Service 层

从 routes/customers.py 提取全部业务逻辑。
SQL 已迁移至 modules.repositories.customer_repository。
"""
from modules.audit_writer import AuditCommand, AuditWriter
from modules.domain.errors import ConflictError, NotFoundError
from modules.services import BaseService
from modules.repositories.customer_repository import (
    CustomerRepository,
    DuplicateCustomerNameError,
)
import logging

_logger = logging.getLogger(__name__)


class CustomerService:
    """客户管理业务逻辑。"""

    @staticmethod
    def _validate_actor_id(actor_id):
        if type(actor_id) is not int or actor_id <= 0:
            raise ValueError("客户操作必须提供有效操作人")

    @staticmethod
    def _write_required_audit(actor_id, action, cid, detail="", *, request_id, db):
        try:
            command = AuditCommand.create(
                actor_id,
                action,
                "customer",
                cid,
                detail,
                request_id=str(request_id or "")[:120],
            )
            AuditWriter.required(command, db=db)
        except Exception as exc:
            # Keep audit storage failures out of legacy ValueError/HTTP 400 paths.
            raise RuntimeError("客户操作审计写入失败") from exc

    @staticmethod
    def _normalize_tags(tags):
        normalized = []
        seen = set()
        for value in str(tags or "").replace("，", ",").split(","):
            tag = value.strip()
            if tag and tag not in seen:
                normalized.append(tag)
                seen.add(tag)
        return ",".join(normalized)

    @staticmethod
    def list_customers(
        keyword=None,
        page=1,
        limit=100,
        tag=None,
        *,
        include_order_stats=True,
        data_scope_pids=None,
    ):
        db = BaseService.db()
        where = "1=1"
        params = []
        if keyword:
            where += " AND (c.name LIKE ? OR c.contact LIKE ? OR c.phone LIKE ?)"
            params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
        if tag:
            where += (
                " AND INSTR("
                "',' || REPLACE(REPLACE(COALESCE(c.tags, ''), ' ', ''), '，', ',') || ',', "
                "',' || REPLACE(?, ' ', '') || ','"
                ") > 0"
            )
            params.append(tag)
        rows, total = CustomerRepository.list_with_order_stats(
            where,
            params,
            page,
            limit,
            include_order_stats=include_order_stats,
            data_scope_pids=data_scope_pids,
            db=db,
        )
        summary_row = CustomerRepository.summarize(
            where,
            params,
            include_order_stats=include_order_stats,
            data_scope_pids=data_scope_pids,
            db=db,
        )
        available_tags = set()
        for row in CustomerRepository.list_tag_values(db=db):
            for value in (row["tags"] or "").replace("，", ",").split(","):
                normalized = value.strip()
                if normalized:
                    available_tags.add(normalized)
        return {
            "customers": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
            "summary": dict(summary_row),
            "available_tags": sorted(available_tags),
        }

    @staticmethod
    def create_customer(data, *, actor_id, request_id=""):
        """创建客户。Raises ValueError on empty name or duplicate."""
        CustomerService._validate_actor_id(actor_id)
        name = data.get("name", "").strip()
        if not name:
            raise ValueError("客户名称不能为空")
        try:
            with BaseService.transaction() as txn:
                existing = CustomerRepository.find_by_name(name, db=txn)
                if existing:
                    raise ConflictError("客户名称已存在")
                cid = CustomerRepository.insert({
                    "name": name,
                    "contact": data.get("contact", ""),
                    "phone": data.get("phone", ""),
                    "email": data.get("email", ""),
                    "address": data.get("address", ""),
                    "remark": data.get("remark", ""),
                    "tags": CustomerService._normalize_tags(data.get("tags", "")),
                }, db=txn)
                CustomerService._write_required_audit(
                    actor_id,
                    "create_customer",
                    cid,
                    {"changed_fields": sorted(data)},
                    request_id=request_id,
                    db=txn,
                )
                return cid
        except DuplicateCustomerNameError as exc:
            raise ConflictError("客户名称已存在") from exc

    @staticmethod
    def update_customer(cid, data, *, actor_id, request_id=""):
        """更新客户。Raises ValueError on empty/missing name or duplicate."""
        CustomerService._validate_actor_id(actor_id)
        if "name" in data:
            name = (data.get("name") or "").strip()
            if not name:
                raise ValueError("客户名称不能为空")
            data["name"] = name
        if "tags" in data:
            data["tags"] = CustomerService._normalize_tags(data.get("tags"))

        sets = []
        params = []
        for field in ["name", "contact", "phone", "email", "address", "remark", "tags"]:
            if field in data:
                sets.append(f"{field} = ?")
                params.append(data[field])
        if not sets:
            raise ValueError("无更新内容")

        name_changed = "name" in data
        try:
            with BaseService.transaction() as txn:
                if not CustomerRepository.find_by_id(cid, db=txn):
                    raise NotFoundError("客户不存在")
                if name_changed:
                    existing = CustomerRepository.find_by_name_excluding(
                        data["name"],
                        cid,
                        db=txn,
                    )
                    if existing:
                        raise ConflictError("客户名称已存在")
                updated = CustomerRepository.update(cid, sets, params, db=txn)
                if updated != 1:
                    raise NotFoundError("客户不存在")
                if name_changed:
                    CustomerRepository.cascade_name_to_orders(cid, data["name"], db=txn)
                CustomerService._write_required_audit(
                    actor_id,
                    "update_customer",
                    cid,
                    {"changed_fields": sorted(data)},
                    request_id=request_id,
                    db=txn,
                )
        except DuplicateCustomerNameError as exc:
            raise ConflictError("客户名称已存在") from exc

    @staticmethod
    def delete_customer(cid, *, actor_id, request_id=""):
        """删除客户。活跃订单关联的客户受 FK 保护无法删除；软删除订单自动解除关联。"""
        CustomerService._validate_actor_id(actor_id)
        with BaseService.transaction() as txn:
            if not CustomerRepository.find_by_id(cid, db=txn):
                raise NotFoundError("客户不存在")
            if CustomerRepository.count_active_orders(cid, db=txn) > 0:
                raise ConflictError("无法删除：该客户存在关联订单，请先处理订单")
            # 解除软删除订单的 customer_id 关联（保留 customer 字段以供审计）
            CustomerRepository.dissociate_soft_deleted_orders(cid, db=txn)
            CustomerRepository.delete(cid, db=txn)
            CustomerService._write_required_audit(
                actor_id,
                "delete_customer",
                cid,
                request_id=request_id,
                db=txn,
            )

    @staticmethod
    def get_customer_orders(cid, page=1, limit=50, data_scope_pids=None):
        """获取客户的订单历史（含工序详情和 extra_fields 解析）。"""
        import json
        db = BaseService.db()
        cust = CustomerRepository.find_by_id(cid, db=db)
        if not cust:
            raise NotFoundError("客户不存在")
        rows, total = CustomerRepository.get_orders(
            cid,
            page,
            limit,
            data_scope_pids=data_scope_pids,
            db=db,
        )

        result = []
        for row in rows:
            o = dict(row)
            try:
                o["extra_fields"] = json.loads(o.get("extra_fields") or "{}")
            except (TypeError, json.JSONDecodeError):
                _logger.warning("invalid customer order extra_fields: order_id=%s", o.get("id"))
                o["extra_fields"] = {}
            procs = CustomerRepository.get_order_processes(
                o["id"],
                data_scope_pids=data_scope_pids,
                db=db,
            )
            o["processes"] = [dict(p) for p in procs]
            result.append(o)
        return {"orders": result, "total": total, "page": page, "limit": limit}
