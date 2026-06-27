import json
import uuid

import bcrypt

from modules.config import PREDEFINED_ROLES


TEST_USER = "testrunner"
TEST_PASS = "Test@1234"
TEST_HASH = bcrypt.hashpw(TEST_PASS.encode(), bcrypt.gensalt()).decode()

WORKER_USER = "testworker"
WORKER_PASS = "Test@1234"
WORKER_HASH = bcrypt.hashpw(WORKER_PASS.encode(), bcrypt.gensalt()).decode()


def ensure_role(db, role_code):
    role_row = db.execute(
        "SELECT id FROM roles WHERE code = ? AND status = 'active' ORDER BY id LIMIT 1",
        (role_code,),
    ).fetchone()
    if role_row:
        return role_row["id"]

    role_def = PREDEFINED_ROLES[role_code]
    cursor = db.execute(
        "INSERT INTO roles (name, code, description, permissions, status, group_id, level) "
        "VALUES (?, ?, ?, ?, 'active', ?, ?)",
        (
            role_def["name"],
            role_def["code"],
            role_def["description"],
            json.dumps(role_def["permissions"], ensure_ascii=False),
            role_def.get("group_id"),
            role_def.get("level", 1),
        ),
    )
    return cursor.lastrowid


def ensure_user(db, username, password_hash, name, role, employee_no, group_name=None):
    existing = db.execute(
        "SELECT id FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if not existing:
        columns = [
            "username",
            "password",
            "name",
            "role",
            "status",
            "password_version",
            "employee_no",
        ]
        values = [username, password_hash, name, role, "active", 2, employee_no]
        if group_name is not None:
            columns.append("group_name")
            values.append(group_name)
        placeholders = ",".join("?" for _ in values)
        cursor = db.execute(
            f"INSERT INTO users ({','.join(columns)}) VALUES ({placeholders})",
            values,
        )
        user_id = cursor.lastrowid
    else:
        user_id = existing["id"]
        update_sql = (
            "UPDATE users SET password = ?, name = ?, role = ?, status = 'active', "
            "locked_until = NULL, failed_login_count = 0, password_version = 2, "
            "token = NULL, must_change_password = 0, employee_no = ?"
        )
        params = [password_hash, name, role, employee_no]
        if group_name is not None:
            update_sql += ", group_name = ?"
            params.append(group_name)
        update_sql += " WHERE id = ?"
        params.append(user_id)
        db.execute(update_sql, params)

    role_id = ensure_role(db, role)
    db.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
    db.execute(
        "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
        (user_id, role_id),
    )
    db.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))

    if role == "admin":
        db.execute("DELETE FROM login_attempts")
        db.execute("DELETE FROM login_logs")

    db.commit()
    return user_id


def ensure_test_order(db):
    db.execute("INSERT OR IGNORE INTO customers (id, name) VALUES (9999, 'Test Customer')")
    db.execute(
        "INSERT OR IGNORE INTO products (id, product_name, product_code, model, spec, category) "
        "VALUES (9999, 'Test Product', 'TEST-CODE-001', 'TEST', 'Standard', 'fixture')"
    )

    process = db.execute(
        "SELECT id FROM processes WHERE status = 'active' ORDER BY seq_order, id LIMIT 1"
    ).fetchone()
    if not process:
        cursor = db.execute(
            "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
            "VALUES (?, ?, ?, 1, 'active', datetime('now','localtime'))",
            ("Fixture Process", "pytest fixture process", "fixture"),
        )
        process_id = cursor.lastrowid
    else:
        process_id = process["id"]

    order_no = f"TEST-FIXTURE-{uuid.uuid4().hex[:8].upper()}"
    cursor = db.execute(
        "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
        "VALUES (?, 'Test Customer', 'Test Product', 'TEST-CODE-001', 10, 'pending', '')",
        (order_no,),
    )
    order_id = cursor.lastrowid
    db.execute(
        "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
        "VALUES (?, ?, 1, 'pending', 0, 0, 0)",
        (order_id, process_id),
    )
    db.commit()
    return order_id
