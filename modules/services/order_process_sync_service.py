"""Order process assignment and synchronization helpers."""

from modules.repositories.order_repository import OrderRepository
from modules.repositories.process_repository import ProcessRepository
from modules.repositories.route_repository import RouteRepository


class OrderProcessSyncService:
    """Keeps order-process route/list synchronization out of OrderService."""

    @staticmethod
    def normalize_process_ids(process_ids):
        return sorted(set(int(process_id) for process_id in process_ids))

    @staticmethod
    def _validate_active_processes(db, process_ids):
        normalized_ids = OrderProcessSyncService.normalize_process_ids(process_ids)
        rows = ProcessRepository.find_by_ids(normalized_ids, db=db)
        by_id = {row["id"]: row for row in rows}
        missing = [pid for pid in normalized_ids if pid not in by_id]
        if missing:
            raise ValueError("工序不存在：" + ", ".join(str(pid) for pid in missing))
        inactive = [row["name"] for row in rows if row["status"] != "active"]
        if inactive:
            raise ValueError("停用工序不能新增到订单：" + "、".join(inactive))
        return normalized_ids

    @staticmethod
    def validate_route_assignment(db, route_id):
        route = RouteRepository.find_route_by_id(route_id, db=db)
        if not route:
            raise ValueError("工艺路线不存在")
        if route["status"] != "active":
            raise ValueError("停用工艺路线不能分配给订单")
        items = RouteRepository.find_route_items_with_processes(route_id, db=db)
        if not items:
            raise ValueError("工艺路线没有工序，不能分配给订单")
        inactive = [item["process_name"] for item in items if item["process_status"] != "active"]
        if inactive:
            raise ValueError("工艺路线包含停用工序：" + "、".join(inactive))
        mismatched = [
            item["process_name"]
            for item in items
            if item["process_category"] != route["category"]
        ]
        if mismatched:
            raise ValueError("工艺路线与工序分类不一致：" + "、".join(mismatched))
        return items

    @staticmethod
    def prepare_update(db, order_id, current_route_id, data):
        """Normalize and validate a requested route or custom-process change."""
        route_changed = 'route_id' in data and data['route_id'] != current_route_id
        process_ids_changed = False
        if 'process_ids' in data:
            if 'route_id' in data:
                raise ValueError('不能同时修改工序路线和自定义工序')
            requested_process_ids = OrderProcessSyncService.normalize_process_ids(
                data['process_ids']
            )
            current_process_ids = {
                row['process_id']
                for row in OrderRepository.list_order_process_ids(order_id, db=db)
            }
            process_ids_changed = set(requested_process_ids) != current_process_ids
            added_process_ids = set(requested_process_ids) - current_process_ids
            if added_process_ids:
                OrderProcessSyncService._validate_active_processes(db, added_process_ids)
            data['process_ids'] = requested_process_ids
            if process_ids_changed:
                data['route_id'] = None
                route_changed = current_route_id is not None

        if route_changed and data.get('route_id') is not None:
            OrderProcessSyncService.validate_route_assignment(db, data['route_id'])

        if route_changed or process_ids_changed:
            work_record_count = OrderRepository.count_active_work_records(order_id, db=db)
            if work_record_count:
                raise ValueError(
                    f'订单已有 {work_record_count} 条报工记录，不能直接修改工序路线或工序'
                )
        return route_changed, process_ids_changed

    @staticmethod
    def assign_processes(db, order_id, route_id=None, process_ids=None):
        """Assign order processes from a route, explicit process list, or all active processes."""
        if route_id and not process_ids:
            OrderProcessSyncService.validate_route_assignment(db, route_id)
            OrderRepository.assign_processes_from_route(order_id, route_id, db=db)
            return

        if process_ids:
            normalized_ids = OrderProcessSyncService._validate_active_processes(db, process_ids)
            OrderRepository.assign_processes_from_list(order_id, normalized_ids, db=db)
            return

        OrderRepository.assign_all_active_processes(order_id, db=db)

    @staticmethod
    def sync_processes(db, order_id, process_ids):
        """Synchronize explicit process list for an existing order."""
        new_process_ids = OrderProcessSyncService.normalize_process_ids(process_ids)
        existing_procs = OrderRepository.list_order_process_ids(order_id, db=db)
        existing_ids = {row["process_id"] for row in existing_procs}

        added_process_ids = set(new_process_ids) - existing_ids
        if added_process_ids:
            OrderProcessSyncService._validate_active_processes(db, added_process_ids)

        remove_ids = [process_id for process_id in existing_ids if process_id not in new_process_ids]
        OrderRepository.delete_order_processes(order_id, remove_ids, db=db)

        for process_id in new_process_ids:
            if process_id in existing_ids:
                continue
            proc = OrderRepository.find_process_seq_order(process_id, db=db)
            if proc:
                OrderRepository.insert_order_process(
                    order_id, process_id, proc["seq_order"], db=db
                )

    @staticmethod
    def sync_route(db, order_id, route_id, route_items=None):
        """Synchronize one order to its selected route while preserving matching progress."""
        if route_items is None:
            route_items = OrderProcessSyncService.validate_route_assignment(db, route_id)
        route_process_ids = [item["process_id"] for item in route_items]
        existing_rows = OrderRepository.list_order_process_ids(order_id, db=db)
        existing_ids = {row["process_id"] for row in existing_rows}

        remove_ids = [process_id for process_id in existing_ids if process_id not in route_process_ids]
        OrderRepository.delete_order_processes(order_id, remove_ids, db=db)

        for item in route_items:
            process_id = item["process_id"]
            if process_id in existing_ids:
                OrderRepository.update_order_process_route_fields(
                    order_id,
                    process_id,
                    item["seq_order"],
                    item["required_audit"],
                    db=db,
                )
                continue
            OrderRepository.insert_order_process(
                order_id,
                process_id,
                item["seq_order"],
                item["required_audit"],
                db=db,
            )

    @staticmethod
    def apply_route(db, order_id, route_id, route_items=None):
        """Apply a validated route through the same order synchronization policy."""
        if route_items is None:
            route_items = OrderProcessSyncService.validate_route_assignment(db, route_id)
        work_record_count = OrderRepository.count_active_work_records(order_id, db=db)
        if work_record_count:
            raise ValueError(
                f'订单已有 {work_record_count} 条报工记录，不能重新应用工艺路线'
            )
        OrderRepository.update_form_fields(order_id, {"route_id": route_id}, db=db)
        OrderProcessSyncService.sync_route(
            db, order_id, route_id, route_items=route_items
        )
        return len(route_items)

    @staticmethod
    def clear_processes(db, order_id):
        """Clear the copied process list when an unreported order drops its route."""
        OrderRepository.delete_all_order_processes(order_id, db=db)
