"""
qr-system — 工序路线管理 Service 层（Repository-refactored）

从 routes/process_routes.py 提取全部业务逻辑。
"""
from modules.domain.errors import ConflictError, NotFoundError
from modules.services import BaseService
from modules.repositories.route_repository import RouteRepository
from modules.services.master_data_impact_service import MasterDataImpactService
from modules.services.legacy_process_compatibility_service import (
    LegacyProcessCompatibilityService,
)
from modules.services.order_process_sync_service import OrderProcessSyncService


class ProcessRouteService:
    """工序路线管理业务逻辑。"""
    VALID_CATEGORIES = ("结构件", "机加工")

    @staticmethod
    def list_routes(
        category="", search="", limit=None, offset=0, selectable=False
    ):
        """获取所有工序路线（含工序明细，批量预取避免 N+1）。"""
        rows, total = RouteRepository.list_routes(category, search, limit, offset)

        items_by_route = {}
        usage_by_route = {}
        if rows:
            route_ids = [r["id"] for r in rows]
            items = RouteRepository.list_route_items(route_ids)
            usage_by_route = RouteRepository.get_route_usage_counts(route_ids)
            for item in items:
                items_by_route.setdefault(item["route_id"], []).append(dict(item))

        result = []
        for r in rows:
            route = dict(r)
            route["processes"] = items_by_route.get(r["id"], [])
            usage = usage_by_route.get(r["id"], {})
            route.update({
                "used_orders": usage.get("used_orders", 0),
                "used_products": usage.get("used_products", 0),
                "is_locked": usage.get("is_locked", False),
            })
            result.append(route)
        legacy = {
            "routes": result,
            "total": total,
            "summary": RouteRepository.get_route_summary(),
        }
        return LegacyProcessCompatibilityService.list_routes(
            legacy,
            category=category,
            search=search,
            limit=limit,
            offset=offset,
            selectable=selectable,
        )

    @staticmethod
    def _validate_category(category):
        if category not in ProcessRouteService.VALID_CATEGORIES:
            raise ValueError("工艺路线分类只能是结构件或机加工")
        return category

    @staticmethod
    def _validate_processes(processes, category, db, existing_process_ids=()):
        pids = [item.get("process_id") for item in processes if item.get("process_id")]
        if not pids:
            raise ValueError("工序列表不能为空")
        if len(pids) != len(set(pids)):
            raise ValueError("工艺路线中不能重复选择同一工序")
        rows = RouteRepository.find_existing_process_ids(pids, db=db)
        by_id = {row["id"]: row for row in rows}
        missing = [pid for pid in pids if pid not in by_id]
        if missing:
            raise NotFoundError("工序 ID " + ", ".join(str(pid) for pid in missing) + " 不存在")
        existing_ids = set(existing_process_ids)
        inactive = [
            by_id[pid]["name"] for pid in pids
            if by_id[pid]["status"] != "active" and pid not in existing_ids
        ]
        if inactive:
            raise ValueError("停用工序不能新增到工艺路线：" + "、".join(inactive))
        mismatched = [by_id[pid]["name"] for pid in pids if by_id[pid]["category"] != category]
        if mismatched:
            raise ValueError("工艺路线与工序分类不一致：" + "、".join(mismatched))
        return pids

    @staticmethod
    def _ensure_route_unreferenced(usage, action):
        if not usage["is_locked"]:
            return
        legacy_labels = {"orders": "订单", "products": "产品"}
        references = [
            f'{count} 个{legacy_labels.get(reference.business_key, reference.business_label)}'
            for reference, count in usage.get("reference_counts", ())
            if count and reference.impact_level != "internal"
        ]
        raise ConflictError(
            "该工序路线已被" + "、".join(references) + f"引用，无法{action}。"
            "请新建工序路线，并将后续订单或产品改用新路线"
        )

    @staticmethod
    def create_route(data):
        LegacyProcessCompatibilityService.require_legacy_write()
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("路线名称不能为空")

        processes = data.get("processes", [])
        if not processes:
            raise ValueError("工序列表不能为空")

        category = ProcessRouteService._validate_category(data.get("category", "结构件"))
        existing = RouteRepository.find_route_by_name(name)
        if existing:
            raise ConflictError("路线名称【" + name + "】已存在")

        with BaseService.transaction() as txn:
            ProcessRouteService._validate_processes(processes, category, txn)
            route_id = RouteRepository.insert_route_txn(
                name, data.get("description", ""), category, db=txn
            )
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
        LegacyProcessCompatibilityService.require_legacy_write()
        with BaseService.transaction() as txn:
            route = RouteRepository.find_route_by_id(rid, db=txn)
            if not route:
                raise NotFoundError("路线不存在")
            ProcessRouteService._ensure_route_unreferenced(
                RouteRepository.get_route_usage(rid, db=txn), "修改"
            )

            new_name = data.get("name", route["name"]).strip()
            if new_name != route["name"]:
                dup = RouteRepository.find_route_by_name(new_name, db=txn)
                if dup and dup["id"] != rid:
                    raise ConflictError("路线名称【" + new_name + "】已存在")

            processes = data.get("processes")
            category = ProcessRouteService._validate_category(
                data.get("category", route["category"])
            )
            existing_items = RouteRepository.find_route_items_ordered(rid, db=txn)
            existing_process_ids = {item["process_id"] for item in existing_items}
            processes_to_validate = processes if processes is not None else [
                {"process_id": item["process_id"]} for item in existing_items
            ]
            ProcessRouteService._validate_processes(
                processes_to_validate,
                category,
                txn,
                existing_process_ids=existing_process_ids,
            )
            RouteRepository.update_route_txn(new_name, data.get("description", route["description"]), category, rid, db=txn)
            if processes is not None:
                RouteRepository.delete_route_items_txn(rid, db=txn)
                for idx, p in enumerate(processes):
                    pid = p.get("process_id")
                    if not pid:
                        continue
                    RouteRepository.insert_route_item_txn(
                        rid, pid, idx, p.get("required_audit", 0), db=txn
                    )
        return {"synced_orders": 0, "skipped_orders": 0}

    @staticmethod
    def delete_route(rid):
        LegacyProcessCompatibilityService.require_legacy_write()
        with BaseService.transaction() as txn:
            route = RouteRepository.find_route_by_id(rid, db=txn)
            if not route:
                raise NotFoundError("路线不存在")
            ProcessRouteService._ensure_route_unreferenced(
                RouteRepository.get_route_usage(rid, db=txn), "删除"
            )
            RouteRepository.delete_route_items_txn(rid, db=txn)
            RouteRepository.delete_route_txn(rid, db=txn)
        return route["name"]

    @staticmethod
    def check_impact(rid):
        return MasterDataImpactService.route_impact(rid)

    @staticmethod
    def check_order_exists(order_id):
        order = RouteRepository.check_order_exists(order_id)
        if not order:
            raise NotFoundError("订单不存在或已删除")
        return order

    @staticmethod
    def apply_route(rid, order_id):
        version = LegacyProcessCompatibilityService.current_route_for_legacy_apply(rid)
        route_items = version.get("items") if version else None
        with BaseService.transaction() as txn:
            if not RouteRepository.find_route_by_id(rid, db=txn):
                raise NotFoundError("路线不存在")
            if not RouteRepository.check_order_exists(order_id, db=txn):
                raise NotFoundError("订单不存在")
            return OrderProcessSyncService.apply_route(
                txn, order_id, rid, route_items=route_items
            )
