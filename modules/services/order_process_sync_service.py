"""Order process assignment and synchronization helpers."""

from modules.repositories.order_repository import OrderRepository


class OrderProcessSyncService:
    """Keeps order-process route/list synchronization out of OrderService."""

    @staticmethod
    def normalize_process_ids(process_ids):
        return sorted(set(int(process_id) for process_id in process_ids))

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
            data['process_ids'] = requested_process_ids
            if process_ids_changed:
                data['route_id'] = None
                route_changed = current_route_id is not None

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
            OrderRepository.assign_processes_from_route(order_id, route_id, db=db)
            return

        if process_ids:
            OrderRepository.assign_processes_from_list(order_id, process_ids, db=db)
            return

        OrderRepository.assign_all_active_processes(order_id, db=db)

    @staticmethod
    def sync_processes(db, order_id, process_ids):
        """Synchronize explicit process list for an existing order."""
        new_process_ids = OrderProcessSyncService.normalize_process_ids(process_ids)
        existing_procs = OrderRepository.list_order_process_ids(order_id, db=db)
        existing_ids = {row["process_id"] for row in existing_procs}

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
    def sync_route(db, order_id, route_id):
        """Synchronize one order to its selected route while preserving matching progress."""
        route_items = OrderRepository.list_route_items(route_id, db=db)
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
    def clear_processes(db, order_id):
        """Clear the copied process list when an unreported order drops its route."""
        OrderRepository.delete_all_order_processes(order_id, db=db)
