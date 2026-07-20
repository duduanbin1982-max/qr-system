import json

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
            "username", "password", "name", "role", "status",
            "password_version", "employee_no",
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
