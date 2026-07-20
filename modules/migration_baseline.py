"""Baseline migration for new and unversioned legacy databases."""

import bcrypt
import json
import sqlite3

from modules.config import PREDEFINED_ROLES
from modules.migration_helpers import add_column_if_missing, create_unique_index
from modules.order_focus_config import (
    COMPLETION_FOCUS_DEFAULT_SETTINGS,
    COMPLETION_FOCUS_MODE_KEY,
    COMPLETION_FOCUS_TAIL_PCT_KEY,
)
from modules.permission_catalog import infer_page_permissions
def m001_baseline(db):
    """Full initial schema + all subsequent migrations as one atomic step."""
    db.execute("PRAGMA foreign_keys=OFF")
    db.execute("PRAGMA journal_mode=WAL")

    """初始化数据库表结构和默认数据
    
    使用 PRAGMA user_version 跟踪迁移版本。
    仅当版本号落后时才执行新增迁移，避免每次启动全量执行。
    """
    db.row_factory = sqlite3.Row
    

    add_column_if_missing(db, "product_items", "version", "INTEGER DEFAULT 1")

    db.execute("PRAGMA foreign_keys=OFF")  # OFF to avoid FK conflicts on existing data during CREATE TABLE IF NOT EXISTS

    add_column_if_missing(db, "orders", "product_code", "TEXT DEFAULT ''")
    add_column_if_missing(db, "orders", "deleted_at", "TEXT DEFAULT NULL")
    add_column_if_missing(db, "orders", "deleted_by", "INTEGER DEFAULT NULL")
    add_column_if_missing(db, "work_records", "serial_no", "TEXT DEFAULT ''")
    add_column_if_missing(db, "users", "password_version", "INTEGER DEFAULT 1")

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

    add_column_if_missing(db, "orders", "deleted_at", "TEXT DEFAULT NULL")
    add_column_if_missing(db, "orders", "deleted_by", "INTEGER DEFAULT NULL")
    add_column_if_missing(db, "processes", "category", 'TEXT DEFAULT "结构件"')
    add_column_if_missing(db, "products", "category", 'TEXT DEFAULT "结构件"')
    add_column_if_missing(db, "products", "price", "REAL DEFAULT 0")
    add_column_if_missing(db, "products", "route_id", "INTEGER DEFAULT NULL")
    db.execute('CREATE INDEX IF NOT EXISTS idx_products_route ON products(route_id)')

    routes = db.execute('SELECT id FROM process_routes').fetchall()
    for (rid,) in routes:
        route_processes = set(r[0] for r in db.execute(
            'SELECT process_id FROM process_route_items WHERE route_id = ?', (rid,)
        ).fetchall())
        if not route_processes:
            continue

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
    db.execute('CREATE INDEX IF NOT EXISTS idx_route_prices_route ON route_prices(route_id)')

    add_column_if_missing(db, "roles", "permissions", 'TEXT DEFAULT ""')
    add_column_if_missing(db, "roles", "level", "INTEGER DEFAULT 1")

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

    add_column_if_missing(db, "users", "last_active", 'TEXT DEFAULT ""')
    for col, col_type in [('nickname','TEXT DEFAULT ""'), ('email','TEXT DEFAULT ""'), ('group_name','TEXT DEFAULT ""')]:
        add_column_if_missing(db, "users", col, col_type)
    add_column_if_missing(db, "users", "position_id", "INTEGER DEFAULT NULL")
    add_column_if_missing(db, "users", "marker", 'TEXT DEFAULT ""')
    add_column_if_missing(db, "users", "failed_login_count", "INTEGER DEFAULT 0")
    add_column_if_missing(db, "users", "locked_until", "TEXT DEFAULT NULL")
    add_column_if_missing(db, "users", "must_change_password", "INTEGER DEFAULT 0")
    db.execute("UPDATE users SET must_change_password = 1 WHERE username IN ('admin','worker1','worker2','worker3','worker4') AND must_change_password = 0")

    # 登录尝试记录表（IP速率限制用）
    db.execute('''
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_la_ip_created ON login_attempts(ip_address, created_at)')

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
    db.execute('CREATE INDEX IF NOT EXISTS idx_ll_user_id ON login_logs(user_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_ll_username ON login_logs(username)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_ll_created ON login_logs(created_at DESC)')

    db.execute("DELETE FROM login_logs WHERE created_at < datetime('now','localtime','-30 days')")

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
    db.execute('CREATE INDEX IF NOT EXISTS idx_us_token ON user_sessions(token)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_us_user_id ON user_sessions(user_id)')

    db.execute("DELETE FROM user_sessions WHERE is_active = 0 AND created_at < datetime('now','localtime','-7 days')")

    create_unique_index(db, "idx_processes_name", "processes", "name")
    create_unique_index(db, "idx_positions_name", "positions", "name")
    create_unique_index(db, "idx_role_groups_name", "role_groups", "name")

    db.execute('CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action)')

    # ============================================================
    # Migration 12: Basic UNIQUE constraints — 防止业务数据重复
    # ============================================================
    # 去重：删除重复行（保留 id 最小的），避免后续建 UNIQUE INDEX 失败
    db.execute("DELETE FROM customers WHERE id NOT IN (SELECT MIN(id) FROM customers GROUP BY name) AND name != ''")
    db.execute("UPDATE users SET employee_no = NULL WHERE employee_no = ''")

    # 先删除与唯一索引同名的普通索引（避免 IF NOT EXISTS 冲突）
    for drop_idx in ['idx_customers_name', 'idx_suppliers_name', 'idx_materials_name']:
        db.execute(f'DROP INDEX IF EXISTS {drop_idx}')

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
        create_unique_index(db, f"idx_{tbl}_{col}", tbl, col)

    # 组合唯一索引
    for tbl, cols in [
        ('order_processes', 'order_id, process_id'),
        ('process_route_items', 'route_id, process_id'),
        ('user_roles', 'user_id, role_id'),
    ]:
        col_label = cols.replace(', ', '_').replace(',', '_')
        create_unique_index(db, f"idx_{tbl}_{col_label}", tbl, cols)

    # 系统设置默认种子数据
    default_settings = {
        'company_name': '', 'contact': '', 'phone': '', 'address': '', 'description': '',
        'default_password': '123456', 'approval_enabled': '1', 'auto_order_no': '', 'page_size': '20',
        COMPLETION_FOCUS_MODE_KEY: COMPLETION_FOCUS_DEFAULT_SETTINGS[COMPLETION_FOCUS_MODE_KEY],
        COMPLETION_FOCUS_TAIL_PCT_KEY: COMPLETION_FOCUS_DEFAULT_SETTINGS[COMPLETION_FOCUS_TAIL_PCT_KEY],
    }
    for k, v in default_settings.items():
        db.execute('INSERT OR IGNORE INTO system_settings (key, value) VALUES (?,?)', (k, v))

    old_orders = db.execute(
        "SELECT id FROM orders WHERE deleted_at IS NOT NULL AND deleted_at < datetime('now','localtime','-90 days')"
    ).fetchall()
    for (oid,) in old_orders:
        for tbl in ['work_records','scrap_records','rework_records','quality_inspections',
                    'material_consumptions','order_processes','product_items','order_attachments']:
            db.execute(f'DELETE FROM {tbl} WHERE order_id = ?', (oid,))
        db.execute('DELETE FROM orders WHERE id = ?', (oid,))

    db.commit()




MIGRATIONS = [
    (1, "Core schema v1-v11: tables, indexes, seed data", m001_baseline),
]
