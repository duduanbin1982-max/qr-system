"""qr-system — 认证路由：登录、登出、用户信息（Service 层重构版）
所有 DB 操作委托给 AuthService，路由仅处理 HTTP 层面逻辑。
"""
import secrets
from datetime import datetime, timedelta
from flask import request, jsonify, g

from modules.app import app
from modules.middleware.audit import safe_audit_log
from modules.middleware.auth import check_auth, get_user_permissions, has_permission
from modules.middleware.validate import validate_json
from modules.middleware.helpers import get_json_body
from modules.constants import SECONDS_PER_DAY, SECONDS_PER_WEEK
from modules.services.auth_service import AuthService




@app.route("/api/auth/login", methods=["POST"])
@validate_json("login")
def login():
    data = get_json_body()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password:
        return jsonify({"error": "请输入用户名和密码"}), 400

    ip = request.remote_addr or "127.0.0.1"
    ua = request.headers.get("User-Agent", "")[:200]

    # --- 第1层：IP速率限制（15次/分钟）---
    rate_cutoff = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    if AuthService.get_login_rate(ip, rate_cutoff) >= 15:
        AuthService.insert_login_log(username, ip, ua, 0, fail_reason="rate_limited")
        return jsonify({"error": "请求过于频繁，请稍后再试"}), 429

    # --- 第2层：账户锁定检查 ---
    user = AuthService.find_user(username)
    if not user:
        AuthService.insert_login_attempt(ip)
        AuthService.insert_login_log(username, ip, ua, 0, fail_reason="user_not_found")
        return jsonify({"error": "用户名或密码错误"}), 400

    if user["locked_until"]:
        try:
            lock_time = datetime.strptime(user["locked_until"], "%Y-%m-%d %H:%M:%S")
            if datetime.now() < lock_time:
                remaining = int((lock_time - datetime.now()).total_seconds())
                AuthService.insert_login_log(username, ip, ua, 0, user_id=user["id"], fail_reason="locked")
                return jsonify({"error": f"账户已锁定，请 {remaining} 秒后再试"}), 429
        except (ValueError, TypeError):
            pass

    # --- 密码验证 ---
    password_ok = AuthService.check_password(user, password)

    # 透明升级旧 SHA256 到 bcrypt
    if password_ok:
        import bcrypt as _bcrypt
        stored = user["password"]
        if not (stored.startswith("$2b$") or stored.startswith("$2a$")):
            try:
                new_hash = _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()
                AuthService.upgrade_password(user["id"], new_hash)
            except Exception:
                pass

    if not password_ok:
        AuthService.insert_login_attempt(ip)
        fail_count = (user["failed_login_count"] or 0) + 1
        locked_until = None
        if fail_count >= 5:
            locked_until = (datetime.now() + timedelta(minutes=AuthService.lock_minutes(fail_count))).strftime("%Y-%m-%d %H:%M:%S")
        AuthService.update_login_failure(user["id"], fail_count, locked_until)
        AuthService.insert_login_log(username, ip, ua, 0, user_id=user["id"], fail_reason="wrong_password")
        remaining_attempts = max(5 - fail_count, 0)
        if remaining_attempts > 0:
            return jsonify({"error": f"用户名或密码错误（还剩 {remaining_attempts} 次机会）"}), 400
        return jsonify({"error": "用户名或密码错误，账户已锁定"}), 400

    # --- 登录成功 ---
    token = secrets.token_hex(32)
    AuthService.create_session(user["id"], token, ip, ua)
    AuthService.insert_login_log(username, ip, ua, 1, user_id=user["id"])

    u = dict(user)
    u["token"] = token
    del u["password"]
    u["role"] = AuthService.get_user_role_code(user["id"]) or u.get("role", "worker")
    u["permissions"] = get_user_permissions(u)

    resp = jsonify({"user": u, "must_change_password": bool(u.get("must_change_password", 0))})
    resp.set_cookie("qr_token", token, httponly=True, secure=True,
                    samesite="Strict", max_age=SECONDS_PER_DAY * 7, path="/")
    return resp


@app.route("/api/auth/logout", methods=["POST"])
@check_auth
def logout():
    AuthService.logout(g.current_user["id"], g.token)
    resp = jsonify({"message": "已退出"})
    resp.set_cookie("qr_token", "", httponly=True, secure=True,
                    samesite="Lax", max_age=0, path="/")
    return resp


@app.route("/api/auth/sessions", methods=["GET"])
@check_auth
def list_sessions():
    rows = AuthService.list_sessions(g.current_user["id"])
    sessions = [dict(r) for r in rows]
    for s in sessions:
        s["is_current"] = (s.get("token") == g.token if "token" in s else False)
    return jsonify({"sessions": sessions})


@app.route("/api/sessions", methods=["GET"])
@check_auth
def sessions_alias():
    return list_sessions()


@app.route("/api/auth/sessions/<int:sid>", methods=["DELETE"])
@check_auth
def delete_session(sid):
    sess = AuthService.find_session_by_id(sid)
    if not sess:
        return jsonify({"error": "会话不存在"}), 404
    if sess["user_id"] != g.current_user["id"] and not has_permission(g.current_user, "users:edit"):
        return jsonify({"error": "无权限"}), 403
    AuthService.delete_session(sid, sess["user_id"])
    return jsonify({"message": "会话已终止"})


@app.route("/api/auth/info", methods=["GET"])
@check_auth
def auth_info():
    u = dict(g.current_user)
    u.pop("password", None)
    u.pop("token", None)
    u.pop("failed_login_count", None)
    u.pop("locked_until", None)
    u.pop("password_version", None)
    u["role"] = AuthService.get_user_role_code(u["id"]) or u.get("role", "worker")
    u["permissions"] = get_user_permissions(g.current_user)
    return jsonify({"user": u, "must_change_password": bool(u.get("must_change_password", 0))})


@app.route("/api/auth/change-password", methods=["POST"])
@check_auth
@validate_json("change_password")
def change_password():
    data = get_json_body()
    new_password = data.get("new_password", "").strip()
    if not new_password or len(new_password) < 8:
        return jsonify({"error": "新密码至少需要6位"}), 400

    import bcrypt as _bcrypt
    pw_hash = _bcrypt.hashpw(new_password.encode(), _bcrypt.gensalt()).decode()
    AuthService.change_password(g.current_user["id"], pw_hash)

    if isinstance(g.current_user, dict):
        g.current_user["must_change_password"] = 0
    safe_audit_log("change_password", "user", g.current_user["id"])
    return jsonify({"message": "密码修改成功"})
