"""
qr-system - Database Migration Framework (Brooks P3)
Extracted from init_db() - 12 versioned incremental migrations.
"""
import sqlite3, json, bcrypt
from modules.config import DB_PATH, PREDEFINED_ROLES
from modules.permission_catalog import infer_page_permissions, default_role_permission_additions
from modules.migration_schema_compat import ensure_current_schema_compat
from modules.migration_materials import ensure_material_planning_tables
from modules.order_focus_config import (
    COMPLETION_FOCUS_DEFAULT_SETTINGS,
    COMPLETION_FOCUS_MODE_KEY,
    COMPLETION_FOCUS_TAIL_PCT_KEY,
)

MIGRATIONS = []
LATEST_VERSION = 0

def migration(version, description):
    def decorator(fn):
        global LATEST_VERSION
        MIGRATIONS.append((version, description, fn))
        LATEST_VERSION = max(LATEST_VERSION, version)
        return fn
    return decorator



def _ensure_completion_focus_tables(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS order_completion_focus_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            detail TEXT DEFAULT '',
            expires_at TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_by INTEGER,
            created_by_name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            cancelled_by INTEGER,
            cancelled_at TEXT DEFAULT '',
            cancel_reason TEXT DEFAULT ''
        )
    """)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_focus_ex_order_status "
        "ON order_completion_focus_exceptions(order_id, status, expires_at)"
    )
    db.execute("""
        CREATE TABLE IF NOT EXISTS order_completion_focus_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            order_id INTEGER,
            process_id INTEGER,
            recommended_order_id INTEGER,
            recommended_order_no TEXT DEFAULT '',
            mode TEXT DEFAULT '',
            blocking INTEGER DEFAULT 0,
            bypass_allowed INTEGER DEFAULT 0,
            reason TEXT DEFAULT '',
            detail TEXT DEFAULT '',
            user_id INTEGER,
            user_name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_focus_events_order_created "
        "ON order_completion_focus_events(order_id, created_at DESC)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_focus_events_type_created "
        "ON order_completion_focus_events(event_type, created_at DESC)"
    )

def _ensure_board_sessions_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS board_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )''')


def _column_exists(db, table, column):
    return any(row[1] == column for row in db.execute(f"PRAGMA table_info({table})"))


def _add_column_if_missing(db, table, column, definition):
    if not _column_exists(db, table, column):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")




@migration(1, "Core schema v1-v11: tables, indexes, seed data")
def m001_baseline(db):
    """Full initial schema + all subsequent migrations as one atomic step."""
    db.execute("PRAGMA foreign_keys=OFF")
    db.execute("PRAGMA journal_mode=WAL")

    """初始化数据库表结构和默认数据
    
    使用 PRAGMA user_version 跟踪迁移版本。
    仅当版本号落后时才执行新增迁移，避免每次启动全量执行。
    """
    db.row_factory = sqlite3.Row
    

    # P3: Add version column for optimistic locking
    try:
        db.execute("ALTER TABLE product_items ADD COLUMN version INTEGER DEFAULT 1")
        db.commit()
    except Exception as e:
        pass

    db.execute("PRAGMA foreign_keys=OFF")  # OFF to avoid FK conflicts on existing data during CREATE TABLE IF NOT EXISTS

    # 迁移 orders 表添加 product_code 列（如果不存在）
    try:
        db.execute("ALTER TABLE orders ADD COLUMN product_code TEXT DEFAULT ''")
        db.commit()
    except Exception:
        pass

    # 迁移 orders 软删除字段
    try:
        db.execute("ALTER TABLE orders ADD COLUMN deleted_at TEXT DEFAULT NULL")
    except Exception as e: pass
    try:
        db.execute("ALTER TABLE orders ADD COLUMN deleted_by INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:

        pass

    # 迁移 work_records 添加 serial_no 列（序列号防重复报工）
    try:
        db.execute("ALTER TABLE work_records ADD COLUMN serial_no TEXT DEFAULT ''")
        db.commit()
    except Exception:
        pass

    # 迁移 users 密码升级：password_version 列（1=SHA256, 2=bcrypt）
    try:
        db.execute("ALTER TABLE users ADD COLUMN password_version INTEGER DEFAULT 1")
        db.commit()
    except Exception:
        pass

    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'worker',
            employee_no TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            process_ids TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            token TEXT DEFAULT '',
            password_version INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        -- 产品序列号表
        CREATE TABLE IF NOT EXISTS product_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            serial_no TEXT UNIQUE NOT NULL,
            order_id INTEGER,
            order_no TEXT DEFAULT '',
            position_no INTEGER DEFAULT 0,
            qr_content TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            current_process_id INTEGER DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_product_items_order ON product_items(order_id);
        CREATE INDEX IF NOT EXISTS idx_product_items_serial ON product_items(serial_no);

        CREATE TABLE IF NOT EXISTS processes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT '结构件',
            seq_order INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT UNIQUE NOT NULL,
            customer TEXT DEFAULT '',
            product_name TEXT DEFAULT '',
            product_code TEXT DEFAULT '',
            quantity INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            scrapped INTEGER DEFAULT 0,
            rework INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            plan_start TEXT DEFAULT '',
            plan_end TEXT DEFAULT '',
            deadline TEXT DEFAULT '',
            extra_fields TEXT DEFAULT '{}',
            remark TEXT DEFAULT '',
            route_id INTEGER DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            deleted_at TEXT DEFAULT NULL,
            deleted_by INTEGER DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS order_processes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            seq_order INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            required_audit INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            scrapped INTEGER DEFAULT 0,
            rework INTEGER DEFAULT 0,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE
        );

            CREATE TABLE IF NOT EXISTS work_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                process_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                type TEXT DEFAULT 'normal',
                status TEXT DEFAULT 'pending',  -- pending, approved, rejected
                quantity INTEGER DEFAULT 0,
                serial_no TEXT DEFAULT '',
                remark TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_wr_user_created ON work_records(user_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_wr_dedup ON work_records(order_id, process_id, user_id, COALESCE(serial_no, ''));
        CREATE INDEX IF NOT EXISTS idx_wr_created ON work_records(created_at);
        CREATE INDEX IF NOT EXISTS idx_wr_user ON work_records(user_id);

        CREATE TABLE IF NOT EXISTS scrap_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            quantity INTEGER DEFAULT 0,
            reason TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS quality_inspections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            inspection_type TEXT NOT NULL DEFAULT 'first_article',
            inspector_id INTEGER,
            quantity_checked INTEGER DEFAULT 0,
            quantity_passed INTEGER DEFAULT 0,
            quantity_failed INTEGER DEFAULT 0,
            result TEXT DEFAULT 'pending',
            defect_category TEXT DEFAULT '',
            defect_quantity INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            inspected_at TEXT DEFAULT (datetime('now','localtime')),
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (inspector_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS rework_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            quantity INTEGER DEFAULT 0,
            reason TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- 订单附件表
        CREATE TABLE IF NOT EXISTS order_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            file_type TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            file_data BLOB,
            file_path TEXT DEFAULT '',
            uploaded_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_attachments_order ON order_attachments(order_id);

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            target_type TEXT DEFAULT '',
            target_id INTEGER DEFAULT 0,
            detail TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT DEFAULT '',
            action TEXT NOT NULL,
            target_type TEXT DEFAULT '',
            target_id INTEGER,
            detail TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS order_completion_focus_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            detail TEXT DEFAULT '',
            expires_at TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_by INTEGER,
            created_by_name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            cancelled_by INTEGER,
            cancelled_at TEXT DEFAULT '',
            cancel_reason TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_focus_ex_order_status
            ON order_completion_focus_exceptions(order_id, status, expires_at);

        -- 库存管理表
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_model TEXT UNIQUE NOT NULL,
            product_name TEXT DEFAULT '',
            specification TEXT DEFAULT '',
            quantity INTEGER DEFAULT 0,
            safe_stock INTEGER DEFAULT 0,
            location TEXT DEFAULT '',
            unit TEXT DEFAULT '件',
            remark TEXT DEFAULT '',
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS inventory_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inventory_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            order_id INTEGER,
            order_no TEXT DEFAULT '',
            remark TEXT DEFAULT '',
            operator_id INTEGER,
            operator_name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (inventory_id) REFERENCES inventory(id)
        );

        CREATE INDEX IF NOT EXISTS idx_inventory_model ON inventory(product_model);
        CREATE INDEX IF NOT EXISTS idx_inventory_logs_inventory ON inventory_logs(inventory_id);
        CREATE INDEX IF NOT EXISTS idx_inventory_logs_created ON inventory_logs(created_at);

        -- 物料管理表
        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            spec TEXT DEFAULT '',
            unit TEXT DEFAULT '件',
            quantity REAL DEFAULT 0,
            unit_price REAL DEFAULT 0,
            safe_stock REAL DEFAULT 0,
            location TEXT DEFAULT '',
            supplier_id INTEGER DEFAULT NULL,
            remark TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_materials_name ON materials(name);

        -- 物料消耗关联表
        CREATE TABLE IF NOT EXISTS material_consumptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER NOT NULL,
            order_id INTEGER,
            process_id INTEGER,
            quantity REAL NOT NULL DEFAULT 0,
            operator_id INTEGER,
            operator_name TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (material_id) REFERENCES materials(id),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (process_id) REFERENCES processes(id)
        );
        CREATE INDEX IF NOT EXISTS idx_mc_material ON material_consumptions(material_id);
        CREATE INDEX IF NOT EXISTS idx_mc_order ON material_consumptions(order_id);

        -- 物料出入库日志表
        CREATE TABLE IF NOT EXISTS material_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            quantity REAL NOT NULL,
            remark TEXT DEFAULT '',
            operator_id INTEGER,
            operator_name TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (material_id) REFERENCES materials(id)
        );
        CREATE INDEX IF NOT EXISTS idx_material_logs_material ON material_logs(material_id);
        CREATE INDEX IF NOT EXISTS idx_material_logs_created ON material_logs(created_at);

        -- 出库管理表
        CREATE TABLE IF NOT EXISTS shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_no TEXT UNIQUE NOT NULL,
            customer TEXT DEFAULT '',
            contact_person TEXT DEFAULT '',
            contact_phone TEXT DEFAULT '',
            address TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            total_quantity INTEGER DEFAULT 0,
            remark TEXT DEFAULT '',
            created_by TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            completed_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS shipment_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL,
            inventory_id INTEGER NOT NULL,
            product_model TEXT DEFAULT '',
            product_name TEXT DEFAULT '',
            quantity INTEGER DEFAULT 0,
            unit TEXT DEFAULT '件',
            remark TEXT DEFAULT '',
            FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE CASCADE,
            FOREIGN KEY (inventory_id) REFERENCES inventory(id)
        );
        CREATE INDEX IF NOT EXISTS idx_shipments_no ON shipments(shipment_no);
        CREATE INDEX IF NOT EXISTS idx_shipments_status ON shipments(status);
        CREATE INDEX IF NOT EXISTS idx_shipments_created ON shipments(created_at);
        CREATE INDEX IF NOT EXISTS idx_shipment_items_shipment ON shipment_items(shipment_id);

        -- 审核配置表
        CREATE TABLE IF NOT EXISTS approval_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_id INTEGER,  -- NULL means global config
            require_approval BOOLEAN DEFAULT 0,
            approver_role TEXT DEFAULT 'admin',
            approval_level INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE
        );

        -- 审核记录表
        CREATE TABLE IF NOT EXISTS approval_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_record_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',  -- pending/approved/rejected
            approver_id INTEGER,
            approver_name TEXT,
            comment TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (work_record_id) REFERENCES work_records(id)
        );

        -- 工艺路线模板表
        CREATE TABLE IF NOT EXISTS process_routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS process_route_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            seq_order INTEGER DEFAULT 0,
            is_required INTEGER DEFAULT 1,
            required_audit INTEGER DEFAULT 0,
            FOREIGN KEY (route_id) REFERENCES process_routes(id) ON DELETE CASCADE,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_route_items_route ON process_route_items(route_id);

        -- 客户管理表
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            address TEXT DEFAULT '',
            remark TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name);
        CREATE INDEX IF NOT EXISTS idx_customers_contact ON customers(contact);
        CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);

        -- 供应商管理表
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            address TEXT DEFAULT '',
            remark TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name);

        -- 产品管理表
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            model TEXT DEFAULT '',
            product_code TEXT DEFAULT '',
            spec TEXT DEFAULT '',
            style TEXT DEFAULT '',
            upper_opening TEXT DEFAULT '',
            plate_thickness TEXT DEFAULT '',
            weight REAL DEFAULT 0,
            category TEXT DEFAULT '结构件',
            price REAL DEFAULT 0,
            description TEXT DEFAULT '',
            route_id INTEGER DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (route_id) REFERENCES process_routes(id)
        );

        CREATE INDEX IF NOT EXISTS idx_products_name ON products(product_name);

        -- 产品附件表
        CREATE TABLE IF NOT EXISTS product_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            file_type TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            file_data BLOB,
            uploaded_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_product_attachments_product ON product_attachments(product_id);

        -- 订单表添加客户外键（兼容历史数据，允许NULL）
        CREATE TABLE IF NOT EXISTS _orders_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT UNIQUE NOT NULL,
            customer TEXT DEFAULT '',
            customer_id INTEGER DEFAULT NULL,
            product_name TEXT DEFAULT '',
            product_code TEXT DEFAULT '',
            quantity INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            scrapped INTEGER DEFAULT 0,
            rework INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            plan_start TEXT DEFAULT '',
            plan_end TEXT DEFAULT '',
            deadline TEXT DEFAULT '',
            extra_fields TEXT DEFAULT '{}',
            remark TEXT DEFAULT '',
            route_id INTEGER DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            deleted_at TEXT DEFAULT NULL,
            deleted_by INTEGER DEFAULT NULL,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        -- 迁移数据（如果新表不存在则创建）
        INSERT OR IGNORE INTO _orders_new (id, order_no, customer, customer_id, product_name, product_code, quantity, completed, scrapped, rework, status, plan_start, plan_end, deadline, extra_fields, remark, route_id, created_at, updated_at, deleted_at, deleted_by)
        SELECT id, order_no, customer, NULL, product_name,
               CASE WHEN extra_fields LIKE '%"product_code"%' THEN
                 substr(extra_fields, instr(extra_fields, '"product_code"') + 15,
                   instr(substr(extra_fields, instr(extra_fields, '"product_code"') + 15), '"') - 1)
               ELSE '' END,
               quantity, completed, scrapped, rework, status, plan_start, plan_end, deadline, extra_fields, remark, route_id, created_at, updated_at, deleted_at, deleted_by FROM orders;

        DROP TABLE IF EXISTS orders;
        ALTER TABLE _orders_new RENAME TO orders;

        CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
    ''')

    # 确保软删除字段存在（_orders_new 迁移可能覆盖）
    try:
        db.execute("ALTER TABLE orders ADD COLUMN deleted_at TEXT DEFAULT NULL")
    except Exception as e: pass
    try:
        db.execute("ALTER TABLE orders ADD COLUMN deleted_by INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:

        pass

    # 兼容旧数据库：添加 category 列（结构件/机加工）
    try:
        db.execute('ALTER TABLE processes ADD COLUMN category TEXT DEFAULT "结构件"')
    except Exception as e:
        pass
    try:
        db.execute('ALTER TABLE products ADD COLUMN category TEXT DEFAULT "结构件"')
    except Exception as e:
        pass
    try:
        db.execute('ALTER TABLE products ADD COLUMN price REAL DEFAULT 0')
    except Exception as e:
        pass
    try:
        db.execute('ALTER TABLE products ADD COLUMN route_id INTEGER DEFAULT NULL')
    except Exception as e:
        pass

    # 迁移后建索引
    try:
        db.execute('CREATE INDEX IF NOT EXISTS idx_products_route ON products(route_id)')
    except Exception as e:
        pass

    # 数据迁移：根据工价记录的工序集合推断产品路线
    try:
        routes = db.execute('SELECT id FROM process_routes').fetchall()
        for (rid,) in routes:
            route_processes = set(r[0] for r in db.execute(
                'SELECT process_id FROM process_route_items WHERE route_id = ?', (rid,)
            ).fetchall())
            if not route_processes:
                continue
    except Exception as e:
        pass

    # 角色组和角色权限表
    db.execute('''
        CREATE TABLE IF NOT EXISTS role_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            parent_id INTEGER DEFAULT NULL,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            permissions TEXT DEFAULT '',
            data_scope TEXT DEFAULT 'all'
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            group_id INTEGER,
            parent_id INTEGER DEFAULT NULL,
            level INTEGER DEFAULT 1,
            permissions TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS user_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            granted_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS menu_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page TEXT NOT NULL UNIQUE,
            permission TEXT NOT NULL DEFAULT '',
            label TEXT DEFAULT '',
            icon TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 999
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS position_processes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            FOREIGN KEY (position_id) REFERENCES positions(id) ON DELETE CASCADE,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
            UNIQUE(position_id, process_id)
        )
    ''')
    # 路线工价表（v4路线级工价）
    db.execute('''
        CREATE TABLE IF NOT EXISTS route_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            unit_price REAL NOT NULL DEFAULT 0,
            effective_date TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            remark TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (route_id) REFERENCES process_routes(id) ON DELETE CASCADE,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE RESTRICT,
            UNIQUE(route_id, process_id)
        )
    ''')
    try:
        db.execute('CREATE INDEX IF NOT EXISTS idx_route_prices_route ON route_prices(route_id)')
    except Exception as e:
        pass

    # 兼容旧数据库
    try:
        db.execute('ALTER TABLE roles ADD COLUMN permissions TEXT DEFAULT ""')
    except Exception as e: pass
    try:
        db.execute('ALTER TABLE roles ADD COLUMN level INTEGER DEFAULT 1')
    except sqlite3.OperationalError:

        pass

    # 初始化默认角色组和管理员角色
    db.execute('INSERT OR IGNORE INTO role_groups (id, name, description) VALUES (1, "系统管理组", "系统内置最高权限角色组")')
    db.execute('INSERT OR IGNORE INTO roles (id, name, code, description, group_id, level, permissions) VALUES (1, "系统管理员", "admin", "系统内置管理员，拥有全部权限", 1, 1, ?)',
               (json.dumps(PREDEFINED_ROLES['admin']['permissions']),))
    # 普通员工角色组
    db.execute('INSERT OR IGNORE INTO role_groups (id, name, description) VALUES (2, "普通员工组", "普通员工角色组")')
    db.execute('INSERT OR IGNORE INTO roles (id, name, code, description, group_id, level, permissions) VALUES (2, "普通员工", "worker", "普通工人，可进行报工操作", 2, 1, ?)',
               (json.dumps(PREDEFINED_ROLES['worker']['permissions']),))

    # 新增预置角色（生产主管、质检员、仓库管理员）
    for role_key in ['production_manager', 'qc_inspector', 'warehouse_keeper']:
        cfg = PREDEFINED_ROLES[role_key]
        db.execute('''INSERT OR IGNORE INTO roles (name, code, description, group_id, level, permissions)
                      VALUES (?,?,?,?,?,?)''',
                   (cfg['name'], cfg['code'], cfg['description'],
                    cfg['group_id'], cfg['level'], json.dumps(cfg['permissions'])))

    # 迁移：修复旧角色中 permissions 为空或非JSON的
    db.execute('''UPDATE roles SET permissions = ?
                  WHERE id = 1 AND (permissions IS NULL OR permissions = '' OR permissions = '""')''',
               (json.dumps(PREDEFINED_ROLES['admin']['permissions']),))
    db.execute('''UPDATE roles SET permissions = ?
                  WHERE id = 2 AND (permissions IS NULL OR permissions = '' OR permissions = '""')''',
               (json.dumps(PREDEFINED_ROLES['worker']['permissions']),))

    # 迁移：为旧角色补充 page:* 页面显示权限，保持升级后菜单/Tab 可见。
    for role in db.execute('SELECT id, permissions FROM roles').fetchall():
        try:
            permissions = json.loads(role['permissions'] or '[]')
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(permissions, list) or '*' in permissions:
            continue
        merged = list(dict.fromkeys(permissions + infer_page_permissions(permissions)))
        if merged != permissions:
            db.execute('UPDATE roles SET permissions = ? WHERE id = ?',
                       (json.dumps(merged, ensure_ascii=False), role['id']))

    # Prevent duplicate processes by enforcing UNIQUE on name
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_processes_name ON processes(name)')
    # Prevent duplicate positions by enforcing UNIQUE on name
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_name ON positions(name)')

    # Default processes
    default_processes = [
        ('下料', '原材料切割', 1),
        ('焊接', '焊接组装', 2),
        ('打磨', '表面打磨', 3),
        ('喷漆', '喷涂上色', 4),
        ('质检', '质量检验', 5),
        ('入库', '成品入库', 6),
    ]
    for name, desc, seq in default_processes:
        db.execute('INSERT OR IGNORE INTO processes (name, description, seq_order) VALUES (?,?,?)',
                   (name, desc, seq))

    # Default admin
    pw = bcrypt.hashpw('admin123'.encode(), bcrypt.gensalt()).decode()
    db.execute('INSERT OR IGNORE INTO users (username, password, name, role, password_version) VALUES (?,?,?,?,2)',
               ('admin', pw, '系统管理员', 'admin'))
    # Auto-assign admin to role 1 (系统管理员) via user_roles
    db.execute('''INSERT OR IGNORE INTO user_roles (user_id, role_id)
                  SELECT id, 1 FROM users WHERE username = 'admin' AND NOT EXISTS
                  (SELECT 1 FROM user_roles WHERE user_id = users.id AND role_id = 1)''')

    # Default workers
    workers = [
        ('worker1', '张三', '下料'),
        ('worker2', '李四', '焊接'),
        ('worker3', '王五', '打磨'),
        ('worker4', '赵六', '质检'),
    ]
    wp = bcrypt.hashpw('123456'.encode(), bcrypt.gensalt()).decode()
    for uname, name, pname in workers:
        db.execute('INSERT OR IGNORE INTO users (username, password, name, role, password_version) VALUES (?,?,?,?,2)',
                   (uname, wp, name, 'worker'))
    # Auto-assign workers to role 2 (普通员工) via user_roles
    db.execute('''INSERT OR IGNORE INTO user_roles (user_id, role_id)
                  SELECT id, 2 FROM users WHERE role = 'worker' AND NOT EXISTS
                  (SELECT 1 FROM user_roles WHERE user_id = users.id AND role_id = 2)''')

    # Add last_active column if missing
    try:
        db.execute('ALTER TABLE users ADD COLUMN last_active TEXT DEFAULT ""')
    except Exception as e:
        pass

    # Add v2 columns (nickname, email, group_name, position_id) if missing
    for col, col_type in [('nickname','TEXT DEFAULT ""'), ('email','TEXT DEFAULT ""'), ('group_name','TEXT DEFAULT ""')]:
        try:
            db.execute(f'ALTER TABLE users ADD COLUMN {col} {col_type}')
        except Exception as e:
            pass
    try:
        db.execute('ALTER TABLE users ADD COLUMN position_id INTEGER DEFAULT NULL')
    except Exception as e:
        pass
    try:
        db.execute('ALTER TABLE users ADD COLUMN marker TEXT DEFAULT ""')
    except Exception as e:
        pass

    # 暴力破解防护：登录失败计数 + 锁定时间
    try:
        db.execute('ALTER TABLE users ADD COLUMN failed_login_count INTEGER DEFAULT 0')
    except Exception as e:
        pass
    try:
        db.execute('ALTER TABLE users ADD COLUMN locked_until TEXT DEFAULT NULL')
    except Exception as e:
        pass

    # 首次登录强制修改密码标记
    try:
        db.execute('ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0')
    except Exception as e:
        pass
    # 标记默认密码账户需首次登录修改密码
    try:
        db.execute("UPDATE users SET must_change_password = 1 WHERE username IN ('admin','worker1','worker2','worker3','worker4') AND must_change_password = 0")
        db.commit()
    except Exception as e:
        pass

    # 登录尝试记录表（IP速率限制用）
    db.execute('''
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')
    try:
        db.execute('CREATE INDEX IF NOT EXISTS idx_la_ip_created ON login_attempts(ip_address, created_at)')
    except Exception as e:
        pass

    # 登录审计日志表（安全审计 + 异常检测 + 排障）
    db.execute('''
        CREATE TABLE IF NOT EXISTS login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            user_id INTEGER DEFAULT NULL,
            ip_address TEXT DEFAULT '',
            success INTEGER DEFAULT 0,
            fail_reason TEXT DEFAULT '',
            user_agent TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')
    try:
        db.execute('CREATE INDEX IF NOT EXISTS idx_ll_user_id ON login_logs(user_id)')
    except Exception as e: pass
    try:
        db.execute('CREATE INDEX IF NOT EXISTS idx_ll_username ON login_logs(username)')
    except Exception as e: pass
    try:
        db.execute('CREATE INDEX IF NOT EXISTS idx_ll_created ON login_logs(created_at DESC)')
    except sqlite3.OperationalError:

        pass

    # 清理 30 天前的登录日志
    try:
        db.execute("DELETE FROM login_logs WHERE created_at < datetime('now','localtime','-30 days')")
    except sqlite3.OperationalError:

        pass

    # 用户会话表（多设备登录 + 远程踢掉）
    db.execute('''
        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            ip_address TEXT DEFAULT '',
            user_agent TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            last_active TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    try:
        db.execute('CREATE INDEX IF NOT EXISTS idx_us_token ON user_sessions(token)')
    except Exception as e: pass
    try:
        db.execute('CREATE INDEX IF NOT EXISTS idx_us_user_id ON user_sessions(user_id)')
    except sqlite3.OperationalError:

        pass

    # 清理 7 天前的非活跃会话
    try:
        db.execute("DELETE FROM user_sessions WHERE is_active = 0 AND created_at < datetime('now','localtime','-7 days')")
    except sqlite3.OperationalError:

        pass

    # Add unique constraint on processes.name
    try:
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_processes_name ON processes(name)')
    except Exception as e:
        pass

    # Add unique constraint on positions.name
    try:
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_name ON positions(name)')
    except Exception as e:
        pass

    # Add unique constraint on role_groups.name
    try:
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_role_groups_name ON role_groups(name)')
    except Exception as e:
        pass

    # audit_logs 索引（性能优化）
    try:
        db.execute('CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action)')
    except Exception as e:
        pass

    # ============================================================
    # Migration 12: Basic UNIQUE constraints — 防止业务数据重复
    # ============================================================
    # 去重：删除重复行（保留 id 最小的），避免后续建 UNIQUE INDEX 失败
    for tbl, col in [
        ('customers', 'name'),
    ]:
        try:
            db.execute(f"DELETE FROM {tbl} WHERE id NOT IN (SELECT MIN(id) FROM {tbl} GROUP BY {col}) AND {col} != ''")
        except Exception:
            pass
    # users.employee_no: 空字符串 → NULL（SQLite UNIQUE 忽略 NULL）
    try:
        db.execute("UPDATE users SET employee_no = NULL WHERE employee_no = ''")
    except Exception:
        pass

    # 先删除与唯一索引同名的普通索引（避免 IF NOT EXISTS 冲突）
    for drop_idx in ['idx_customers_name', 'idx_suppliers_name', 'idx_materials_name']:
        try:
            db.execute(f'DROP INDEX IF EXISTS {drop_idx}')
        except Exception:
            pass

    # 单列唯一索引
    for tbl, col in [
        ('customers', 'name'),
        ('suppliers', 'name'),
        ('materials', 'name'),
        ('products', 'product_code'),
        ('positions', 'name'),
        ('process_routes', 'name'),
        ('users', 'employee_no'),
    ]:
        try:
            db.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS idx_{tbl}_{col} ON {tbl}({col})')
        except Exception:
            pass  # 存在重复数据则跳过

    # 组合唯一索引
    for tbl, cols in [
        ('order_processes', 'order_id, process_id'),
        ('process_route_items', 'route_id, process_id'),
        ('user_roles', 'user_id, role_id'),
    ]:
        col_label = cols.replace(', ', '_').replace(',', '_')
        try:
            db.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS idx_{tbl}_{col_label} ON {tbl}({cols})')
        except Exception:
            pass

    # 系统设置默认种子数据
    default_settings = {
        'company_name': '', 'contact': '', 'phone': '', 'address': '', 'description': '',
        'default_password': '123456', 'approval_enabled': '1', 'auto_order_no': '', 'page_size': '20',
        COMPLETION_FOCUS_MODE_KEY: COMPLETION_FOCUS_DEFAULT_SETTINGS[COMPLETION_FOCUS_MODE_KEY],
        COMPLETION_FOCUS_TAIL_PCT_KEY: COMPLETION_FOCUS_DEFAULT_SETTINGS[COMPLETION_FOCUS_TAIL_PCT_KEY],
    }
    for k, v in default_settings.items():
        db.execute('INSERT OR IGNORE INTO system_settings (key, value) VALUES (?,?)', (k, v))

    # 彻底清理 90 天前软删除的订单及其子表数据
    try:
        old_orders = db.execute(
            "SELECT id FROM orders WHERE deleted_at IS NOT NULL AND deleted_at < datetime('now','localtime','-90 days')"
        ).fetchall()
        for (oid,) in old_orders:
            for tbl in ['work_records','scrap_records','rework_records','quality_inspections',
                        'material_consumptions','order_processes','product_items','order_attachments']:
                db.execute(f'DELETE FROM {tbl} WHERE order_id = ?', (oid,))
            db.execute('DELETE FROM orders WHERE id = ?', (oid,))
    except Exception as e: pass

    db.commit()

    db.commit()



@migration(13, "Create board sessions table")
def m013_board_sessions(db):
    _ensure_board_sessions_table(db)
    db.commit()


@migration(14, "Create product BOM and order material tables")
def m014_material_planning_tables(db):
    ensure_material_planning_tables(db)
    db.commit()


@migration(15, "Add is_builtin column to roles")
def m015_roles_is_builtin(db):
    try:
        db.execute("ALTER TABLE roles ADD COLUMN is_builtin INTEGER DEFAULT 0")
    except Exception as e:
        pass
    db.execute("UPDATE roles SET is_builtin = 1 WHERE id IN (1, 2)")
    db.commit()


@migration(16, "Add approval missing columns (approver_role_2/3, processed_at, current_level)")
def m016_approval_columns(db):
    try:
        db.execute("ALTER TABLE approval_config ADD COLUMN approver_role_2 TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        db.execute("ALTER TABLE approval_config ADD COLUMN approver_role_3 TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        db.execute("ALTER TABLE approval_records ADD COLUMN processed_at TEXT")
    except Exception:
        pass
    try:
        db.execute("ALTER TABLE approval_records ADD COLUMN current_level INTEGER DEFAULT 1")
    except Exception:
        pass
    db.commit()



@migration(17, "Add indexes on approval_records and approval_config")
def m017_approval_indexes(db):
    db.execute("CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_records(status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_approval_work_record ON approval_records(work_record_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_approval_created ON approval_records(created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_approval_config_process ON approval_config(process_id)")
    db.commit()



@migration(18, "Add index on quality_attachments.inspection_id")
def m018_quality_attachments_index(db):
    exists = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='quality_attachments'"
    ).fetchone()
    if exists:
        db.execute("CREATE INDEX IF NOT EXISTS idx_qa_inspection_id ON quality_attachments(inspection_id)")
    db.commit()


@migration(19, "Add marker column to users")
def m019_users_marker(db):
    try:
        db.execute('ALTER TABLE users ADD COLUMN marker TEXT DEFAULT ""')
    except Exception:
        pass
    db.commit()


@migration(20, "Ensure board/material planning tables after legacy migration gap")
def m020_ensure_legacy_gap_tables(db):
    _ensure_board_sessions_table(db)
    ensure_material_planning_tables(db)
    db.commit()


@migration(21, "Backfill page permissions for existing roles")
def m021_backfill_page_permissions(db):
    for role in db.execute('SELECT id, permissions FROM roles').fetchall():
        try:
            permissions = json.loads(role['permissions'] or '[]')
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(permissions, list) or '*' in permissions:
            continue
        merged = list(dict.fromkeys(permissions + infer_page_permissions(permissions)))
        if merged != permissions:
            db.execute('UPDATE roles SET permissions = ? WHERE id = ?',
                       (json.dumps(merged, ensure_ascii=False), role['id']))
    db.commit()


@migration(22, "Ensure current schema compatibility columns")
def m022_current_schema_compat(db):
    ensure_current_schema_compat(db)
    db.commit()


@migration(23, "Add performance evaluation and improvement workflow")
def m023_performance_management(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS performance_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            year_month TEXT NOT NULL,
            role_type TEXT DEFAULT 'worker',
            output_qty INTEGER DEFAULT 0,
            report_count INTEGER DEFAULT 0,
            work_days INTEGER DEFAULT 0,
            scrap_qty INTEGER DEFAULT 0,
            rework_qty INTEGER DEFAULT 0,
            inspection_failed_qty INTEGER DEFAULT 0,
            output_score REAL DEFAULT 0,
            quality_score REAL DEFAULT 0,
            delivery_score REAL DEFAULT 0,
            discipline_score REAL DEFAULT 0,
            improvement_score REAL DEFAULT 0,
            total_score REAL DEFAULT 0,
            rank_no INTEGER DEFAULT 0,
            rank_total INTEGER DEFAULT 0,
            warning_level TEXT DEFAULT 'green',
            warning_reason TEXT DEFAULT '',
            status TEXT DEFAULT 'draft',
            generated_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, year_month),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_scores_month ON performance_scores(year_month)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_scores_user ON performance_scores(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_scores_warning ON performance_scores(warning_level)")
    db.execute("""
        CREATE TABLE IF NOT EXISTS performance_improvement_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            score_id INTEGER,
            user_id INTEGER NOT NULL,
            year_month TEXT NOT NULL,
            warning_level TEXT DEFAULT 'yellow',
            reason TEXT DEFAULT '',
            goal TEXT DEFAULT '',
            actions TEXT DEFAULT '',
            owner_id INTEGER,
            due_date TEXT DEFAULT '',
            status TEXT DEFAULT 'open',
            review_result TEXT DEFAULT '',
            review_notes TEXT DEFAULT '',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            closed_at TEXT DEFAULT '',
            FOREIGN KEY (score_id) REFERENCES performance_scores(id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_plans_user ON performance_improvement_plans(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_plans_month ON performance_improvement_plans(year_month)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_plans_status ON performance_improvement_plans(status)")
    db.commit()


@migration(24, "Deepen performance review scoring inputs")
def m024_performance_review_inputs(db):
    score_columns = {
        "discipline_deduction": "REAL DEFAULT 0",
        "discipline_reason": "TEXT DEFAULT ''",
        "improvement_deduction": "REAL DEFAULT 0",
        "improvement_reason": "TEXT DEFAULT ''",
        "manual_score": "REAL DEFAULT 0",
        "manual_comment": "TEXT DEFAULT ''",
        "score_details": "TEXT DEFAULT '{}'",
        "reviewed_by": "INTEGER",
        "reviewed_at": "TEXT DEFAULT ''",
    }
    for column, definition in score_columns.items():
        _add_column_if_missing(db, "performance_scores", column, definition)

    db.execute("""
        CREATE TABLE IF NOT EXISTS performance_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            year_month TEXT NOT NULL,
            discipline_deduction REAL DEFAULT 0,
            discipline_reason TEXT DEFAULT '',
            improvement_adjustment REAL DEFAULT 0,
            improvement_reason TEXT DEFAULT '',
            manual_score REAL DEFAULT 10,
            manual_comment TEXT DEFAULT '',
            reviewed_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(user_id, year_month),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_reviews_month ON performance_reviews(year_month)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_perf_reviews_user ON performance_reviews(user_id)")
    db.commit()


@migration(25, "Add process handoff quality reviews")
def m025_process_handoff_reviews(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS process_handoff_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            serial_no TEXT DEFAULT '',
            from_process_id INTEGER NOT NULL,
            to_process_id INTEGER NOT NULL,
            from_user_id INTEGER NOT NULL,
            evaluator_user_id INTEGER NOT NULL,
            source_work_record_id INTEGER,
            quantity INTEGER DEFAULT 1,
            rating INTEGER NOT NULL,
            issue_type TEXT DEFAULT '',
            comment TEXT DEFAULT '',
            status TEXT DEFAULT 'confirmed',
            confirmed_by INTEGER,
            confirmed_at TEXT DEFAULT '',
            confirm_note TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (from_process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (to_process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (from_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (evaluator_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (source_work_record_id) REFERENCES work_records(id) ON DELETE SET NULL,
            FOREIGN KEY (confirmed_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_handoff_reviews_month ON process_handoff_reviews(created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_handoff_reviews_from_user ON process_handoff_reviews(from_user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_handoff_reviews_status ON process_handoff_reviews(status)")
    db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_handoff_reviews_unique_serial
        ON process_handoff_reviews(order_id, serial_no, from_process_id, to_process_id)
        WHERE serial_no IS NOT NULL AND serial_no <> ''
    """)
    db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_handoff_reviews_unique_batch
        ON process_handoff_reviews(order_id, from_process_id, to_process_id, evaluator_user_id)
        WHERE serial_no IS NULL OR serial_no = ''
    """)
    db.commit()


@migration(26, "Grant performance permissions to management roles")
def m026_grant_performance_permissions(db):
    for role_code in ("production_manager", "qc_inspector", "warehouse_keeper"):
        additions = default_role_permission_additions(role_code)
        if not additions:
            continue
        row = db.execute("SELECT id, permissions FROM roles WHERE code = ?", (role_code,)).fetchone()
        if not row:
            continue
        try:
            permissions = json.loads(row["permissions"] or "[]")
        except (TypeError, json.JSONDecodeError):
            permissions = []
        if not isinstance(permissions, list) or "*" in permissions:
            continue
        merged = list(dict.fromkeys(permissions + additions))
        if merged != permissions:
            db.execute(
                "UPDATE roles SET permissions = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), row["id"]),
            )
    db.commit()


@migration(27, "Add quality inspection scoring fields")
def m027_quality_inspection_scoring(db):
    columns = {
        "score_total": "REAL DEFAULT 0",
        "score_detail_json": "TEXT DEFAULT '{}'",
        "defect_level": "TEXT DEFAULT ''",
        "defect_items_json": "TEXT DEFAULT '[]'",
        "suggested_result": "TEXT DEFAULT ''",
        "final_result": "TEXT DEFAULT ''",
        "override_reason": "TEXT DEFAULT ''",
    }
    for column, definition in columns.items():
        _add_column_if_missing(db, "quality_inspections", column, definition)
    db.commit()


@migration(28, "Add work time management tables")
def m028_work_time_management(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS work_time_standards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            product_code TEXT DEFAULT '',
            product_name TEXT DEFAULT '',
            route_id INTEGER,
            process_id INTEGER NOT NULL,
            standard_minutes_per_unit REAL NOT NULL DEFAULT 0,
            setup_minutes REAL DEFAULT 0,
            difficulty_factor REAL DEFAULT 1,
            effective_from TEXT DEFAULT '',
            effective_to TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            version INTEGER DEFAULT 1,
            remark TEXT DEFAULT '',
            created_by INTEGER,
            updated_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL,
            FOREIGN KEY (route_id) REFERENCES process_routes(id) ON DELETE SET NULL,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_standards_process ON work_time_standards(process_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_standards_product ON work_time_standards(product_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_standards_status ON work_time_standards(status)")

    db.execute("""
        CREATE TABLE IF NOT EXISTS work_time_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            order_no TEXT DEFAULT '',
            serial_no TEXT DEFAULT '',
            route_id INTEGER,
            route_name TEXT DEFAULT '',
            product_code TEXT DEFAULT '',
            product_name TEXT DEFAULT '',
            standard_missing INTEGER DEFAULT 0,
            process_id INTEGER NOT NULL,
            process_name TEXT DEFAULT '',
            user_id INTEGER NOT NULL,
            user_name TEXT DEFAULT '',
            standard_id INTEGER,
            source_work_record_id INTEGER,
            quantity INTEGER DEFAULT 1,
            standard_minutes REAL DEFAULT 0,
            start_time TEXT DEFAULT '',
            end_time TEXT DEFAULT '',
            pause_minutes REAL DEFAULT 0,
            actual_minutes REAL DEFAULT 0,
            effective_minutes REAL DEFAULT 0,
            status TEXT DEFAULT 'completed',
            abnormal_reason TEXT DEFAULT '',
            review_status TEXT DEFAULT 'approved',
            reviewed_by INTEGER,
            reviewed_at TEXT DEFAULT '',
            review_note TEXT DEFAULT '',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE SET NULL,
            FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (standard_id) REFERENCES work_time_standards(id) ON DELETE SET NULL,
            FOREIGN KEY (source_work_record_id) REFERENCES work_records(id) ON DELETE SET NULL,
            FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_user ON work_time_records(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_process ON work_time_records(process_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_order ON work_time_records(order_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_route_process ON work_time_records(route_id, process_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_standard_missing ON work_time_records(standard_missing)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_review ON work_time_records(review_status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_start ON work_time_records(start_time)")

    db.execute("""
        CREATE TABLE IF NOT EXISTS work_time_review_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            old_effective_minutes REAL DEFAULT 0,
            new_effective_minutes REAL DEFAULT 0,
            old_review_status TEXT DEFAULT '',
            new_review_status TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            reviewer_id INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (record_id) REFERENCES work_time_records(id) ON DELETE CASCADE,
            FOREIGN KEY (reviewer_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_review_logs_record ON work_time_review_logs(record_id)")

    for role_code in ("production_manager",):
        additions = default_role_permission_additions(role_code)
        if not additions:
            continue
        row = db.execute("SELECT id, permissions FROM roles WHERE code = ?", (role_code,)).fetchone()
        if not row:
            continue
        try:
            permissions = json.loads(row["permissions"] or "[]")
        except (TypeError, json.JSONDecodeError):
            permissions = []
        if not isinstance(permissions, list) or "*" in permissions:
            continue
        merged = list(dict.fromkeys(permissions + additions))
        if merged != permissions:
            db.execute(
                "UPDATE roles SET permissions = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), row["id"]),
            )
    db.commit()


def run_migrations(db=None):

    """Run all pending migrations in order."""
    own_db = db is None
    if own_db:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    try:
        current = db.execute("PRAGMA user_version").fetchone()[0]
        sorted_migs = sorted(MIGRATIONS, key=lambda m: m[0])
        executed = 0
        for ver, desc, fn in sorted_migs:
            if ver <= current:
                continue
            try:
                fn(db)
                db.execute(f"PRAGMA user_version = {ver}")
                db.commit()
                executed += 1
            except Exception as e:
                print(f"[Migration v{ver}] {desc} - FAILED: {e}")
                db.rollback()
                raise
        if executed:
            print(f"[Migration] Ran {executed} migration(s)")
        return executed
    finally:
        if own_db:
            db.close()


def init_db():
    """Thin wrapper - runs pending migrations."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        run_migrations(db)
    finally:
        db.close()


@migration(29, "Add completion focus event table")
def m029_completion_focus_events(db):
    _ensure_completion_focus_tables(db)
    for key, value in COMPLETION_FOCUS_DEFAULT_SETTINGS.items():
        db.execute('INSERT OR IGNORE INTO system_settings (key, value) VALUES (?,?)', (key, value))
    db.commit()


@migration(30, "Add work time record route and product snapshots")
def m030_work_time_record_snapshots(db):
    columns = {
        "route_id": "INTEGER",
        "route_name": "TEXT DEFAULT ''",
        "product_code": "TEXT DEFAULT ''",
        "product_name": "TEXT DEFAULT ''",
        "standard_missing": "INTEGER DEFAULT 0",
    }
    for column, definition in columns.items():
        _add_column_if_missing(db, "work_time_records", column, definition)
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_route_process ON work_time_records(route_id, process_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wt_records_standard_missing ON work_time_records(standard_missing)")
    db.commit()
