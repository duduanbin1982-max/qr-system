"""Order process assignment and synchronization helpers."""


class OrderProcessSyncService:
    """Keeps order-process route/list synchronization out of OrderService."""

    @staticmethod
    def assign_processes(db, order_id, route_id=None, process_ids=None):
        """Assign order processes from a route, explicit process list, or all active processes."""
        if route_id and not process_ids:
            route_items = db.execute(
                "SELECT pri.process_id, pri.seq_order, pri.required_audit "
                "FROM process_route_items pri WHERE pri.route_id = ? ORDER BY pri.seq_order",
                (route_id,)
            ).fetchall()
            for item in route_items:
                db.execute(
                    "INSERT INTO order_processes (order_id, process_id, seq_order, required_audit) "
                    "VALUES (?,?,?,?)",
                    (order_id, item["process_id"], item["seq_order"], item["required_audit"])
                )
            return

        if not process_ids:
            procs = db.execute(
                "SELECT id, seq_order FROM processes WHERE status = 'active' ORDER BY seq_order"
            ).fetchall()
            process_ids = [p["id"] for p in procs]

        for process_id in process_ids:
            proc = db.execute(
                "SELECT seq_order FROM processes WHERE id = ?",
                (process_id,),
            ).fetchone()
            if proc:
                db.execute(
                    "INSERT INTO order_processes (order_id, process_id, seq_order) VALUES (?,?,?)",
                    (order_id, process_id, proc["seq_order"])
                )

    @staticmethod
    def sync_processes(db, order_id, process_ids):
        """Synchronize explicit process list for an existing order."""
        new_process_ids = sorted(set(int(process_id) for process_id in process_ids))
        existing_procs = db.execute(
            "SELECT process_id FROM order_processes WHERE order_id = ?",
            (order_id,)
        ).fetchall()
        existing_ids = {row["process_id"] for row in existing_procs}
        remove_ids = [process_id for process_id in existing_ids if process_id not in new_process_ids]
        if remove_ids:
            placeholders = ",".join("?" for _ in remove_ids)
            db.execute(
                f"DELETE FROM order_processes WHERE order_id = ? AND process_id IN ({placeholders})",
                [order_id] + remove_ids
            )
        for process_id in new_process_ids:
            if process_id in existing_ids:
                continue
            proc = db.execute(
                "SELECT seq_order FROM processes WHERE id = ?",
                (process_id,),
            ).fetchone()
            if proc:
                db.execute(
                    "INSERT INTO order_processes (order_id, process_id, seq_order) VALUES (?,?,?)",
                    (order_id, process_id, proc["seq_order"])
                )
