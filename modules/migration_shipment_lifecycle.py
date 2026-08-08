"""Auditable shipment lifecycle and payment-ledger migrations."""

from modules.migration_helpers import add_column_if_missing


def m052_shipment_lifecycle(db):
    for trigger in (
        "prevent_shipment_delete",
        "prevent_shipment_item_delete",
        "prevent_invalid_shipment_status_transition",
        "prevent_shipment_event_update",
        "prevent_shipment_event_delete",
    ):
        db.execute("DROP TRIGGER IF EXISTS " + trigger)

    shipment_columns = {
        "created_by_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        "created_by_name": "TEXT DEFAULT ''",
        "updated_at": "TEXT DEFAULT ''",
        "completed_by_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        "completed_by_name": "TEXT DEFAULT ''",
        "cancelled_by_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        "cancelled_by_name": "TEXT DEFAULT ''",
        "cancel_reason": "TEXT DEFAULT ''",
        "reversed_at": "TEXT DEFAULT ''",
        "reversed_by_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        "reversed_by_name": "TEXT DEFAULT ''",
        "reverse_reason": "TEXT DEFAULT ''",
        "received_at": "TEXT DEFAULT ''",
        "received_by_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        "received_by_name": "TEXT DEFAULT ''",
        "receiver_name": "TEXT DEFAULT ''",
        "receive_date": "TEXT DEFAULT ''",
        "version": "INTEGER NOT NULL DEFAULT 0",
        "legacy_imported": "INTEGER NOT NULL DEFAULT 0",
    }
    for column, definition in shipment_columns.items():
        add_column_if_missing(db, "shipments", column, definition)

    db.execute(
        "UPDATE shipments SET created_by_name=COALESCE(NULLIF(created_by_name,''),created_by,''), "
        "updated_at=COALESCE(NULLIF(updated_at,''),created_at,''), legacy_imported=1"
    )
    db.execute(
        "UPDATE shipment_items SET order_id=(SELECT i.order_id FROM inventory i "
        "WHERE i.id=shipment_items.inventory_id) "
        "WHERE order_id IS NULL AND EXISTS (SELECT 1 FROM inventory i "
        "WHERE i.id=shipment_items.inventory_id AND i.order_id IS NOT NULL)"
    )
    db.execute(
        "UPDATE shipment_items SET order_no=COALESCE((SELECT o.order_no FROM orders o "
        "WHERE o.id=shipment_items.order_id),'') "
        "WHERE order_id IS NOT NULL AND COALESCE(order_no,'')=''"
    )
    db.execute(
        "UPDATE shipment_items SET product_model=COALESCE(NULLIF(product_model,''),"
        "(SELECT i.product_model FROM inventory i WHERE i.id=shipment_items.inventory_id),'')"
    )
    db.execute(
        "UPDATE shipment_items SET product_name=COALESCE(NULLIF(product_name,''),"
        "(SELECT i.product_name FROM inventory i WHERE i.id=shipment_items.inventory_id),'')"
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS shipment_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_no TEXT NOT NULL UNIQUE,
            shipment_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            from_status TEXT DEFAULT '',
            to_status TEXT DEFAULT '',
            payload TEXT DEFAULT '{}',
            operator_id INTEGER,
            operator_name TEXT DEFAULT '',
            idempotency_key TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE RESTRICT,
            FOREIGN KEY (operator_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_shipment_events_idempotency "
        "ON shipment_events(idempotency_key) WHERE COALESCE(idempotency_key,'')!=''"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_shipment_events_shipment "
        "ON shipment_events(shipment_id, created_at, id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_shipment_items_order "
        "ON shipment_items(order_id, shipment_id)"
    )
    db.execute(
        "INSERT OR IGNORE INTO shipment_events "
        "(event_no,shipment_id,event_type,from_status,to_status,payload,operator_name,idempotency_key,created_at) "
        "SELECT 'SE-LEGACY-'||printf('%010d',id),id,'legacy_imported','',status,"
        "'{\"legacy\":true}',COALESCE(created_by_name,created_by,''),"
        "'shipment:'||id||':legacy-import',COALESCE(NULLIF(created_at,''),datetime('now','localtime')) "
        "FROM shipments"
    )

    db.execute(
        """
        CREATE TRIGGER prevent_shipment_delete
        BEFORE DELETE ON shipments
        BEGIN
            SELECT RAISE(ABORT, 'shipment documents are auditable; cancel or reverse them');
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER prevent_shipment_item_delete
        BEFORE DELETE ON shipment_items
        BEGIN
            SELECT RAISE(ABORT, 'shipment items are auditable and cannot be deleted');
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER prevent_invalid_shipment_status_transition
        BEFORE UPDATE OF status ON shipments
        WHEN OLD.status != NEW.status AND NOT (
            (OLD.status='pending' AND NEW.status IN ('completed','cancelled')) OR
            (OLD.status='completed' AND NEW.status IN ('received','reversed')) OR
            (OLD.status='received' AND NEW.status='reversed')
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid shipment status transition');
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER prevent_shipment_event_update
        BEFORE UPDATE ON shipment_events
        BEGIN
            SELECT RAISE(ABORT, 'shipment events are immutable');
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER prevent_shipment_event_delete
        BEFORE DELETE ON shipment_events
        BEGIN
            SELECT RAISE(ABORT, 'shipment events are immutable');
        END
        """
    )


def m053_shipment_payment_ledger(db):
    for trigger in (
        "prevent_shipment_payment_update",
        "prevent_shipment_payment_delete",
        "validate_shipment_payment_insert",
        "project_shipment_payment_insert",
        "protect_shipment_payment_projection",
        "refresh_shipment_payment_status",
    ):
        db.execute("DROP TRIGGER IF EXISTS " + trigger)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS shipment_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_no TEXT NOT NULL UNIQUE,
            shipment_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('receipt','refund','reversal')),
            amount REAL NOT NULL CHECK(amount > 0),
            payment_date TEXT NOT NULL,
            method TEXT DEFAULT '',
            remark TEXT DEFAULT '',
            operator_id INTEGER,
            operator_name TEXT DEFAULT '',
            idempotency_key TEXT DEFAULT '',
            reversal_of_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE RESTRICT,
            FOREIGN KEY (operator_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (reversal_of_id) REFERENCES shipment_payments(id) ON DELETE RESTRICT
        )
        """
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_shipment_payments_idempotency "
        "ON shipment_payments(idempotency_key) WHERE COALESCE(idempotency_key,'')!=''"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_shipment_payments_shipment "
        "ON shipment_payments(shipment_id, payment_date, id)"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_shipment_payments_reversal "
        "ON shipment_payments(reversal_of_id) "
        "WHERE type='reversal' AND reversal_of_id IS NOT NULL"
    )
    db.execute(
        "INSERT OR IGNORE INTO shipment_payments "
        "(payment_no,shipment_id,type,amount,payment_date,method,remark,operator_name,idempotency_key,created_at) "
        "SELECT 'PAY-LEGACY-'||printf('%010d',id),id,'receipt',paid_amount,"
        "COALESCE(NULLIF(payment_date,''),substr(COALESCE(NULLIF(completed_at,''),created_at),1,10)),"
        "COALESCE(payment_method,''),COALESCE(payment_remark,''),'legacy',"
        "'shipment:'||id||':legacy-payment',COALESCE(NULLIF(payment_date,''),completed_at,created_at) "
        "FROM shipments WHERE COALESCE(paid_amount,0)>0"
    )
    db.execute(
        """
        CREATE TRIGGER validate_shipment_payment_insert
        BEFORE INSERT ON shipment_payments
        BEGIN
            SELECT CASE
                WHEN NEW.type='reversal' AND (
                    NEW.reversal_of_id IS NULL OR
                    NOT EXISTS (
                        SELECT 1 FROM shipment_payments original
                        WHERE original.id=NEW.reversal_of_id
                          AND original.shipment_id=NEW.shipment_id
                          AND original.type IN ('receipt','refund')
                          AND ROUND(original.amount,2)=ROUND(NEW.amount,2)
                    )
                )
                THEN RAISE(ABORT, 'invalid shipment payment reversal')
                WHEN NEW.type!='reversal' AND NEW.reversal_of_id IS NOT NULL
                THEN RAISE(ABORT, 'only reversals may reference another payment')
                WHEN NEW.type='receipt' AND ROUND(
                    COALESCE((
                        SELECT SUM(CASE
                            WHEN p.type='receipt' THEN p.amount
                            WHEN p.type='refund' THEN -p.amount
                            WHEN p.type='reversal' AND original.type='receipt' THEN -p.amount
                            WHEN p.type='reversal' AND original.type='refund' THEN p.amount
                            ELSE 0 END)
                        FROM shipment_payments p
                        LEFT JOIN shipment_payments original ON original.id=p.reversal_of_id
                        WHERE p.shipment_id=NEW.shipment_id
                    ),0) + NEW.amount, 2
                ) > ROUND(COALESCE((
                    SELECT receivable_amount FROM shipments WHERE id=NEW.shipment_id
                ),0),2)
                THEN RAISE(ABORT, 'shipment receipt exceeds receivable amount')
                WHEN NEW.type='refund' AND ROUND(
                    COALESCE((
                        SELECT SUM(CASE
                            WHEN p.type='receipt' THEN p.amount
                            WHEN p.type='refund' THEN -p.amount
                            WHEN p.type='reversal' AND original.type='receipt' THEN -p.amount
                            WHEN p.type='reversal' AND original.type='refund' THEN p.amount
                            ELSE 0 END)
                        FROM shipment_payments p
                        LEFT JOIN shipment_payments original ON original.id=p.reversal_of_id
                        WHERE p.shipment_id=NEW.shipment_id
                    ),0) - NEW.amount, 2
                ) < 0
                THEN RAISE(ABORT, 'shipment refund exceeds received amount')
            END;
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER protect_shipment_payment_projection
        BEFORE UPDATE OF paid_amount, payment_status ON shipments
        WHEN ROUND(COALESCE(NEW.paid_amount,0),2) != ROUND(COALESCE((
            SELECT SUM(CASE
                WHEN p.type='receipt' THEN p.amount
                WHEN p.type='refund' THEN -p.amount
                WHEN p.type='reversal' AND original.type='receipt' THEN -p.amount
                WHEN p.type='reversal' AND original.type='refund' THEN p.amount
                ELSE 0 END)
            FROM shipment_payments p
            LEFT JOIN shipment_payments original ON original.id=p.reversal_of_id
            WHERE p.shipment_id=NEW.id
        ),0),2)
        OR COALESCE(NEW.payment_status,'unpaid') != CASE
            WHEN ROUND(COALESCE((
                SELECT SUM(CASE
                    WHEN p.type='receipt' THEN p.amount
                    WHEN p.type='refund' THEN -p.amount
                    WHEN p.type='reversal' AND original.type='receipt' THEN -p.amount
                    WHEN p.type='reversal' AND original.type='refund' THEN p.amount
                    ELSE 0 END)
                FROM shipment_payments p
                LEFT JOIN shipment_payments original ON original.id=p.reversal_of_id
                WHERE p.shipment_id=NEW.id
            ),0),2) <= 0 THEN 'unpaid'
            WHEN ROUND(COALESCE((
                SELECT SUM(CASE
                    WHEN p.type='receipt' THEN p.amount
                    WHEN p.type='refund' THEN -p.amount
                    WHEN p.type='reversal' AND original.type='receipt' THEN -p.amount
                    WHEN p.type='reversal' AND original.type='refund' THEN p.amount
                    ELSE 0 END)
                FROM shipment_payments p
                LEFT JOIN shipment_payments original ON original.id=p.reversal_of_id
                WHERE p.shipment_id=NEW.id
            ),0),2) >= ROUND(COALESCE(NEW.receivable_amount,0),2) THEN 'paid'
            ELSE 'partial'
        END
        BEGIN
            SELECT RAISE(ABORT, 'shipment payment projection must match ledger');
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER project_shipment_payment_insert
        AFTER INSERT ON shipment_payments
        BEGIN
            UPDATE shipments SET
                paid_amount=ROUND(COALESCE((
                    SELECT SUM(CASE
                        WHEN p.type='receipt' THEN p.amount
                        WHEN p.type='refund' THEN -p.amount
                        WHEN p.type='reversal' AND original.type='receipt' THEN -p.amount
                        WHEN p.type='reversal' AND original.type='refund' THEN p.amount
                        ELSE 0 END)
                    FROM shipment_payments p
                    LEFT JOIN shipment_payments original ON original.id=p.reversal_of_id
                    WHERE p.shipment_id=NEW.shipment_id
                ),0),2),
                payment_status=CASE
                    WHEN ROUND(COALESCE((
                        SELECT SUM(CASE
                            WHEN p.type='receipt' THEN p.amount
                            WHEN p.type='refund' THEN -p.amount
                            WHEN p.type='reversal' AND original.type='receipt' THEN -p.amount
                            WHEN p.type='reversal' AND original.type='refund' THEN p.amount
                            ELSE 0 END)
                        FROM shipment_payments p
                        LEFT JOIN shipment_payments original ON original.id=p.reversal_of_id
                        WHERE p.shipment_id=NEW.shipment_id
                    ),0),2) <= 0 THEN 'unpaid'
                    WHEN ROUND(COALESCE((
                        SELECT SUM(CASE
                            WHEN p.type='receipt' THEN p.amount
                            WHEN p.type='refund' THEN -p.amount
                            WHEN p.type='reversal' AND original.type='receipt' THEN -p.amount
                            WHEN p.type='reversal' AND original.type='refund' THEN p.amount
                            ELSE 0 END)
                        FROM shipment_payments p
                        LEFT JOIN shipment_payments original ON original.id=p.reversal_of_id
                        WHERE p.shipment_id=NEW.shipment_id
                    ),0),2) >= ROUND(COALESCE(receivable_amount,0),2) THEN 'paid'
                    ELSE 'partial'
                END,
                payment_date=NEW.payment_date,
                payment_method=NEW.method,
                payment_remark=NEW.remark,
                updated_at=datetime('now','localtime'),
                version=COALESCE(version,0)+1
            WHERE id=NEW.shipment_id;
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER refresh_shipment_payment_status
        AFTER UPDATE OF receivable_amount ON shipments
        BEGIN
            UPDATE shipments SET payment_status=CASE
                WHEN ROUND(COALESCE(paid_amount,0),2) <= 0 THEN 'unpaid'
                WHEN ROUND(COALESCE(paid_amount,0),2) >= ROUND(COALESCE(receivable_amount,0),2)
                    THEN 'paid'
                ELSE 'partial'
            END WHERE id=NEW.id;
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER prevent_shipment_payment_update
        BEFORE UPDATE ON shipment_payments
        BEGIN
            SELECT RAISE(ABORT, 'shipment payments are immutable');
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER prevent_shipment_payment_delete
        BEFORE DELETE ON shipment_payments
        BEGIN
            SELECT RAISE(ABORT, 'shipment payments are immutable');
        END
        """
    )


MIGRATIONS = [
    (52, "Add auditable shipment lifecycle and event history", m052_shipment_lifecycle),
    (53, "Add immutable shipment payment ledger", m053_shipment_payment_ledger),
]
