"""Order process assignment and synchronization helpers."""

from modules.repositories.order_repository import OrderRepository


class OrderProcessSyncService:
    """Keeps order-process route/list synchronization out of OrderService."""

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
        new_process_ids = sorted(set(int(process_id) for process_id in process_ids))
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
