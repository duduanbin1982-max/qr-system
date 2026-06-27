"""
qr-system — 客户管理 Service 层

从 routes/customers.py 提取全部业务逻辑。
SQL 已迁移至 modules.repositories.customer_repository。
"""
from modules.services import BaseService
from modules.repositories.customer_repository import CustomerRepository
import logging

_logger = logging.getLogger(__name__)


class CustomerService:
    """客户管理业务逻辑。"""

    @staticmethod
    def list_customers(keyword=None, page=1, limit=100, tag=None):
        db = BaseService.db()
        where = "1=1"
        params = []
        if keyword:
            where += " AND (c.name LIKE ? OR c.contact LIKE ? OR c.phone LIKE ?)"
            params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
        if tag:
            where += " AND c.tags LIKE ?"
            params.append(f"%{tag}%")
        total = db.execute(f"SELECT COUNT(*) FROM customers c WHERE {where}", params).fetchone()[0]
        offset = (page - 1) * limit
        rows = db.execute(f"SELECT c.*, COUNT(o.id) as order_count, MAX(o.created_at) as last_order_date FROM customers c LEFT JOIN orders o ON o.customer_id = c.id AND o.deleted_at IS NULL WHERE {where} GROUP BY c.id ORDER BY c.id DESC LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
        return {"customers": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}

    @staticmethod
    def create_customer(data):
        """创建客户。Raises ValueError on empty name or duplicate."""
        name = data.get("name", "").strip()
        if not name:
            raise ValueError("客户名称不能为空")
        existing = CustomerRepository.find_by_name(name)
        if existing:
            raise ValueError("客户名称已存在")
        with BaseService.transaction() as txn:
            return CustomerRepository.insert({
                "name": name,
                "contact": data.get("contact", ""),
                "phone": data.get("phone", ""),
                "email": data.get("email", ""),
                "address": data.get("address", ""),
                "remark": data.get("remark", ""),
                "tags": data.get("tags", ""),
            }, db=txn)

    @staticmethod
    def update_customer(cid, data):
        """更新客户。Raises ValueError on empty/missing name or duplicate."""
        db = BaseService.db()
        if "name" in data:
            name = (data.get("name") or "").strip()
            if not name:
                raise ValueError("客户名称不能为空")
            existing = CustomerRepository.find_by_name_excluding(name, cid, db=db)
            if existing:
                raise ValueError("客户名称已存在")
            data["name"] = name

        sets = []
        params = []
        for field in ["name", "contact", "phone", "email", "address", "remark", "tags"]:
            if field in data:
                sets.append(f"{field} = ?")
                params.append(data[field])
        if not sets:
            raise ValueError("无更新内容")

        name_changed = "name" in data
        with BaseService.transaction() as txn:
            CustomerRepository.update(cid, sets, params, db=txn)
            # P0: Cascade customer name update to orders.customer
            if name_changed:
                CustomerRepository.cascade_name_to_orders(cid, data["name"], db=txn)

    @staticmethod
    def delete_customer(cid):
        """删除客户。活跃订单关联的客户受 FK 保护无法删除；软删除订单自动解除关联。"""
        db = BaseService.db()
        cust = CustomerRepository.find_by_id(cid, db=db)
        if not cust:
            raise ValueError("客户不存在")
        # 检查是否有活跃（未软删除）订单
        active = CustomerRepository.count_active_orders(cid, db=db)
        if active > 0:
            # 获取前 5 个订单号用于错误提示
            blocking = CustomerRepository.get_active_order_nos(cid, limit=5, db=db)
            order_list = ", ".join(blocking) if blocking else str(active)
            raise ValueError(f"无法删除：该客户有 {active} 个活跃订单（{order_list}...），请先处理订单")
        with BaseService.transaction() as txn:
            # 解除软删除订单的 customer_id 关联（保留 customer 字段以供审计）
            CustomerRepository.dissociate_soft_deleted_orders(cid, db=txn)
            CustomerRepository.delete(cid, db=txn)

    @staticmethod
    def get_customer_orders(cid, page=1, limit=50):
        """获取客户的订单历史（含工序详情和 extra_fields 解析）。"""
        import json
        db = BaseService.db()
        cust = CustomerRepository.find_by_id(cid, db=db)
        if not cust:
            raise ValueError("客户不存在")
        rows, total = CustomerRepository.get_orders(cid, page, limit, db=db)

        result = []
        for row in rows:
            o = dict(row)
            try:
                o["extra_fields"] = json.loads(o.get("extra_fields") or "{}")
            except (TypeError, json.JSONDecodeError):
                _logger.warning("invalid customer order extra_fields: order_id=%s", o.get("id"))
                o["extra_fields"] = {}
            procs = CustomerRepository.get_order_processes(o["id"], db=db)
            o["processes"] = [dict(p) for p in procs]
            result.append(o)
        return {"orders": result, "total": total, "page": page, "limit": limit}
