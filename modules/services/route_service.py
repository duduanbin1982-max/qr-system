"""
qr-system — 工序路线管理 Service 层（Repository-refactored）

从 routes/process_routes.py 提取全部业务逻辑。
"""
from modules.services import BaseService
from modules.repositories.route_repository import RouteRepository


class ProcessRouteService:
    """工序路线管理业务逻辑。"""

    @staticmethod
    def list_routes(category="", search="", limit=None, offset=0):
        """获取所有工序路线（含工序明细，批量预取避免 N+1）。"""
        sql = "SELECT * FROM process_routes"
        params = []
        conditions = []
        if category:
            conditions.append("category = ?")
            params.append(category)
        if search:
            conditions.append("name LIKE ? ESCAPE \"\\\"")
            safe_search = search.replace("%", "\\%").replace("_", "\\_")
            params.append("%" + safe_search + "%")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC"

        if limit:
            limit = max(1, min(int(limit), 200))
            total = RouteRepository.count_routes(conditions, params)
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = RouteRepository.list_routes_query(sql, params)
        else:
            rows = RouteRepository.list_routes_query(sql, params)
            total = len(rows)

        items_by_route = {}
        if rows:
            route_ids = [r["id"] for r in rows]
            items = RouteRepository.list_route_items(route_ids)
            for item in items:
                items_by_route.setdefault(item["route_id"], []).append(dict(item))

        result = []
        for r in rows:
            route = dict(r)
            route["processes"] = items_by_route.get(r["id"], [])
            result.append(route)
        return {"routes": result, "total": total}

    @staticmethod
    def create_route(data):
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("路线名称不能为空")

        processes = data.get("processes", [])
        if not processes:
            raise ValueError("工序列表不能为空")

        existing = RouteRepository.find_route_by_name(name)
        if existing:
            raise ValueError("路线名称【" + name + "】已存在")

        with BaseService.transaction() as txn:
            route_id = RouteRepository.insert_route_txn(
                name, data.get("description", ""), data.get("category", "结构件"), db=txn
            )
            pids = [p.get("process_id") for p in processes if p.get("process_id")]
            if pids:
                existing_ids = set(r["id"] for r in RouteRepository.find_existing_process_ids(pids, db=txn))
                for pid in pids:
                    if pid not in existing_ids:
                        raise ValueError("工序 ID " + str(pid) + " 不存在")
            for idx, p in enumerate(processes):
                pid = p.get("process_id")
                if not pid:
                    continue
                RouteRepository.insert_route_item_txn(
                    route_id, pid, idx, p.get("required_audit", 0), db=txn
                )
            return route_id

    @staticmethod
    def update_route(rid, data):
        route = RouteRepository.find_route_by_id(rid)
        if not route:
            raise ValueError("路线不存在")

        new_name = data.get("name", route["name"]).strip()
        if new_name != route["name"]:
            dup = RouteRepository.find_route_by_name(new_name)
            if dup and dup["id"] != rid:
                raise ValueError("路线名称【" + new_name + "】已存在")

        processes = data.get("processes")
        category = data.get("category", route["category"])

        with BaseService.transaction() as txn:
            RouteRepository.update_route_txn(new_name, data.get("description", route["description"]), category, rid, db=txn)
            if processes is not None:
                RouteRepository.delete_route_items_txn(rid, db=txn)
                pids = [p.get("process_id") for p in processes if p.get("process_id")]
                if pids:
                    existing_ids = set(r["id"] for r in RouteRepository.find_existing_process_ids(pids, db=txn))
                    for pid in pids:
                        if pid not in existing_ids:
                            raise ValueError("工序 ID " + str(pid) + " 不存在")
                for idx, p in enumerate(processes):
                    pid = p.get("process_id")
                    if not pid:
                        continue
                    RouteRepository.insert_route_item_txn(
                        rid, pid, idx, p.get("required_audit", 0), db=txn
                    )

    @staticmethod
    def delete_route(rid):
        route = RouteRepository.find_route_by_id(rid)
        if not route:
            raise ValueError("路线不存在")
        used = RouteRepository.count_orders_using_route(rid)
        if used["cnt"] > 0:
            raise ValueError("该路线已被 " + str(used["cnt"]) + " 个订单使用，无法删除")
        product_count = RouteRepository.count_products_using_route(rid)
        if product_count["cnt"] > 0:
            raise ValueError("该路线已被 " + str(product_count["cnt"]) + " 个产品引用，无法删除")
        with BaseService.transaction() as txn:
            RouteRepository.delete_route_items_txn(rid, db=txn)
            RouteRepository.delete_route_txn(rid, db=txn)
        return route["name"]

    @staticmethod
    def check_impact(rid):
        route = RouteRepository.find_route_name(rid)
        if not route:
            raise ValueError("Route not found")
        used = RouteRepository.count_orders_using_route(rid)["cnt"]
        return {"route_id": rid, "name": route["name"], "used_orders": used}

    @staticmethod
    def check_order_exists(order_id):
        order = RouteRepository.check_order_exists(order_id)
        if not order:
            raise ValueError("订单不存在或已删除")
        return order

    @staticmethod
    def apply_route(rid, order_id):
        route = RouteRepository.find_route_by_id(rid)
        if not route:
            raise ValueError("路线不存在")
        order = RouteRepository.check_order_exists(order_id)
        if not order:
            raise ValueError("订单不存在")

        with BaseService.transaction() as txn:
            existing_cnt = RouteRepository.count_work_records_for_order_txn(order_id, db=txn)
            if existing_cnt > 0:
                raise ValueError("该订单已有 " + str(existing_cnt) + " 条报工记录，无法重新应用路线")

            RouteRepository.update_order_route_txn(rid, order_id, db=txn)
            RouteRepository.delete_order_processes_txn(order_id, db=txn)
            items = RouteRepository.find_route_items_ordered(rid, db=txn)
            for item in items:
                RouteRepository.insert_order_process_txn(
                    order_id, item["process_id"], item["seq_order"], item["required_audit"], db=txn
                )
            return len(items)
