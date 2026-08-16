"""Order process assignment and synchronization helpers."""

from modules.domain.errors import ConflictError
from modules.repositories.order_repository import OrderRepository
from modules.repositories.process_version_repository import ProcessVersionRepository
from modules.repositories.route_version_repository import RouteVersionRepository


class OrderProcessSyncService:
    """Freeze published master-data revisions into order business facts."""

    @staticmethod
    def normalize_process_ids(process_ids):
        return sorted(set(int(process_id) for process_id in process_ids))

    @staticmethod
    def _binding_from_process_version(version, *, seq_order=None, required_audit=0):
        return {
            "process_id": int(version["process_id"]),
            "process_version_id": int(version["id"]),
            "process_code_snapshot": version.get("process_code_snapshot") or "",
            "process_name_snapshot": version.get("name") or "",
            "process_category_snapshot": version.get("category") or "",
            "seq_order": int(
                version.get("seq_order", 0) if seq_order is None else seq_order
            ),
            "required_audit": int(required_audit or 0),
        }

    @staticmethod
    def _binding_from_route_item(item):
        return {
            "process_id": int(item["process_id"]),
            "process_version_id": int(item["process_version_id"]),
            "process_code_snapshot": item.get("process_code_snapshot") or "",
            "process_name_snapshot": item.get("process_name_snapshot") or "",
            "process_category_snapshot": item.get("process_category") or "",
            "seq_order": int(item.get("seq_order") or 0),
            "required_audit": int(item.get("required_audit") or 0),
        }

    @staticmethod
    def _resolve_process_bindings(db, process_ids):
        normalized_ids = OrderProcessSyncService.normalize_process_ids(process_ids)
        roots = ProcessVersionRepository.roots(normalized_ids, db=db)
        by_id = {int(root["id"]): root for root in roots}
        missing = [process_id for process_id in normalized_ids if process_id not in by_id]
        if missing:
            raise ValueError("工序不存在：" + ", ".join(str(pid) for pid in missing))

        retired = [
            root["name"]
            for root in roots
            if root.get("lifecycle_status") != "active"
        ]
        if retired:
            raise ConflictError("已退休工序不能新增到订单：" + "、".join(retired))

        unavailable = [
            root["name"]
            for root in roots
            if not root.get("current_version")
            or root["current_version"].get("status") != "published"
        ]
        if unavailable:
            raise ConflictError(
                "工序尚无已发布版本，不能新增到订单：" + "、".join(unavailable)
            )

        return [
            OrderProcessSyncService._binding_from_process_version(
                by_id[process_id]["current_version"]
            )
            for process_id in normalized_ids
        ]

    @staticmethod
    def _resolve_all_active_process_bindings(db):
        roots = ProcessVersionRepository.roots(db=db)
        process_ids = [
            root["id"]
            for root in roots
            if root.get("lifecycle_status") == "active" and root.get("status") == "active"
        ]
        return OrderProcessSyncService._resolve_process_bindings(db, process_ids)

    @staticmethod
    def _resolve_route_assignment(db, route_id, route_version_id=None):
        root = RouteVersionRepository.root(route_id, db=db)
        if root is None:
            raise ValueError("工艺路线不存在")
        if root.get("lifecycle_status") != "active":
            raise ConflictError("工艺路线已退休，不能分配给订单")

        version = (
            RouteVersionRepository.version(route_version_id, db=db)
            if route_version_id is not None
            else RouteVersionRepository.current_version(route_id, db=db)
        )
        if version is not None and int(version["process_route_id"]) != int(route_id):
            raise ValueError("路线版本不属于所选路线")
        if version is None or version.get("status") != "published":
            raise ConflictError("工艺路线尚无已发布版本，不能分配给订单")
        if not version.get("items"):
            raise ValueError("工艺路线没有工序，不能分配给订单")

        return {
            "route_id": int(route_id),
            "route_version_id": int(version["id"]),
            "route_name_snapshot": version.get("name") or "",
            "processes": [
                OrderProcessSyncService._binding_from_route_item(item)
                for item in version["items"]
            ],
        }

    @staticmethod
    def prepare_assignment(db, route_id=None, process_ids=None, route_version_id=None):
        if route_id:
            return OrderProcessSyncService._resolve_route_assignment(
                db, route_id, route_version_id=route_version_id
            )
        if process_ids:
            processes = OrderProcessSyncService._resolve_process_bindings(db, process_ids)
        else:
            processes = OrderProcessSyncService._resolve_all_active_process_bindings(db)
        return {
            "route_id": None,
            "route_version_id": None,
            "route_name_snapshot": "",
            "processes": processes,
        }

    @staticmethod
    def _validate_active_processes(db, process_ids):
        return OrderProcessSyncService._resolve_process_bindings(db, process_ids)

    @staticmethod
    def validate_route_assignment(db, route_id):
        return OrderProcessSyncService._resolve_route_assignment(db, route_id)["processes"]

    @staticmethod
    def prepare_update(db, order_id, current_route_id, data):
        """Normalize and validate a requested route or custom-process change."""
        route_changed = "route_id" in data and data["route_id"] != current_route_id
        process_ids_changed = False
        if "process_ids" in data:
            if "route_id" in data:
                raise ValueError("不能同时修改工序路线和自定义工序")
            requested_process_ids = OrderProcessSyncService.normalize_process_ids(
                data["process_ids"]
            )
            current_process_ids = {
                row["process_id"]
                for row in OrderRepository.list_order_process_ids(order_id, db=db)
            }
            process_ids_changed = set(requested_process_ids) != current_process_ids
            if process_ids_changed:
                OrderProcessSyncService._resolve_process_bindings(db, requested_process_ids)
                data.update(
                    {
                        "process_ids": requested_process_ids,
                        "route_id": None,
                        "route_version_id": None,
                        "route_name_snapshot": "",
                    }
                )
                route_changed = current_route_id is not None

        if route_changed:
            if data.get("route_id") is None:
                data.update({"route_version_id": None, "route_name_snapshot": ""})
            else:
                assignment = OrderProcessSyncService._resolve_route_assignment(
                    db, data["route_id"]
                )
                data.update(
                    {
                        "route_version_id": assignment["route_version_id"],
                        "route_name_snapshot": assignment["route_name_snapshot"],
                    }
                )

        if route_changed or process_ids_changed:
            work_record_count = OrderRepository.count_active_work_records(order_id, db=db)
            if work_record_count:
                raise ValueError(
                    f"订单已有 {work_record_count} 条报工记录，不能直接修改工序路线或工序"
                )
        return route_changed, process_ids_changed

    @staticmethod
    def _insert_binding(db, order_id, binding):
        OrderRepository.insert_order_process(
            order_id,
            binding["process_id"],
            binding["seq_order"],
            binding["required_audit"],
            process_version_id=binding["process_version_id"],
            process_code_snapshot=binding["process_code_snapshot"],
            process_name_snapshot=binding["process_name_snapshot"],
            process_category_snapshot=binding["process_category_snapshot"],
            db=db,
        )

    @staticmethod
    def assign_processes(
        db, order_id, route_id=None, process_ids=None, assignment=None
    ):
        """Assign exact published revisions to a newly created order."""
        assignment = assignment or OrderProcessSyncService.prepare_assignment(
            db, route_id=route_id, process_ids=process_ids
        )
        for binding in assignment["processes"]:
            OrderProcessSyncService._insert_binding(db, order_id, binding)
        return assignment

    @staticmethod
    def sync_processes(db, order_id, process_ids):
        """Synchronize explicit process roots and refresh exact current revisions."""
        bindings = OrderProcessSyncService._resolve_process_bindings(db, process_ids)
        new_process_ids = [binding["process_id"] for binding in bindings]
        existing_rows = OrderRepository.list_order_process_ids(order_id, db=db)
        existing_ids = {row["process_id"] for row in existing_rows}

        remove_ids = [process_id for process_id in existing_ids if process_id not in new_process_ids]
        OrderRepository.delete_order_processes(order_id, remove_ids, db=db)
        for binding in bindings:
            if binding["process_id"] in existing_ids:
                OrderRepository.update_order_process_route_fields(
                    order_id,
                    binding["process_id"],
                    binding["seq_order"],
                    binding["required_audit"],
                    binding["process_version_id"],
                    binding["process_code_snapshot"],
                    binding["process_name_snapshot"],
                    binding["process_category_snapshot"],
                    db=db,
                )
            else:
                OrderProcessSyncService._insert_binding(db, order_id, binding)

    @staticmethod
    def sync_route(db, order_id, route_id, route_version_id=None, assignment=None):
        """Synchronize an unreported order to one exact published route revision."""
        assignment = assignment or OrderProcessSyncService._resolve_route_assignment(
            db, route_id, route_version_id=route_version_id
        )
        bindings = assignment["processes"]
        route_process_ids = [binding["process_id"] for binding in bindings]
        existing_rows = OrderRepository.list_order_process_ids(order_id, db=db)
        existing_ids = {row["process_id"] for row in existing_rows}

        remove_ids = [process_id for process_id in existing_ids if process_id not in route_process_ids]
        OrderRepository.delete_order_processes(order_id, remove_ids, db=db)
        for binding in bindings:
            if binding["process_id"] in existing_ids:
                OrderRepository.update_order_process_route_fields(
                    order_id,
                    binding["process_id"],
                    binding["seq_order"],
                    binding["required_audit"],
                    binding["process_version_id"],
                    binding["process_code_snapshot"],
                    binding["process_name_snapshot"],
                    binding["process_category_snapshot"],
                    db=db,
                )
            else:
                OrderProcessSyncService._insert_binding(db, order_id, binding)
        OrderRepository.update_form_fields(
            order_id,
            {
                "route_id": assignment["route_id"],
                "route_version_id": assignment["route_version_id"],
                "route_name_snapshot": assignment["route_name_snapshot"],
            },
            db=db,
        )
        return assignment

    @staticmethod
    def apply_route(db, order_id, route_id, route_version_id=None):
        """Apply the current published route without crossing the transaction boundary."""
        assignment = OrderProcessSyncService._resolve_route_assignment(
            db, route_id, route_version_id=route_version_id
        )
        work_record_count = OrderRepository.count_active_work_records(order_id, db=db)
        if work_record_count:
            raise ValueError(
                f"订单已有 {work_record_count} 条报工记录，不能重新应用工艺路线"
            )
        OrderProcessSyncService.sync_route(
            db, order_id, route_id, assignment=assignment
        )
        return len(assignment["processes"])

    @staticmethod
    def clear_processes(db, order_id):
        """Clear copied process facts when an unreported order drops its route."""
        OrderRepository.delete_all_order_processes(order_id, db=db)
