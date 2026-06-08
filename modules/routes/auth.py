"""
qr-system — 认证路由：登录、登出、用户信息
"""
import hashlib
import bcrypt
import secrets
from datetime import datetime, timedelta
from flask import request, jsonify, g

from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth, get_user_permissions, audit_log
from modules.middleware.validate import validate_json
from modules.middleware.helpers import get_json_body


def _lock_minutes(fail_count):
    """渐进式锁定时间（分钟）"""
    thresholds = [(20, 1440), (15, 120), (10, 30), (5, 5)]
    for threshold, minutes in thresholds:
        if fail_count >= threshold:
            return minutes
    return 5


@app.route('/api/auth/login', methods=['POST'])
@validate_json('login')
def login():
    data = get_json_body()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return jsonify({'error': '请输入用户名和密码'}), 400

    db = get_db()
    ip = request.remote_addr or '127.0.0.1'
    ua = request.headers.get('User-Agent', '')[:200]  # 截断防止过长

    # --- 第1层：IP速率限制（15次/分钟）---
    rate_cutoff = (datetime.now() - timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S')
    rate_count = db.execute(
        'SELECT COUNT(*) FROM login_attempts WHERE ip_address = ? AND created_at > ?',
        (ip, rate_cutoff)
    ).fetchone()[0]
    if rate_count >= 15:
        db.execute('INSERT INTO login_logs (username, ip_address, success, fail_reason, user_agent) VALUES (?,?,0,?,?)',
                   (username, ip, 'rate_limited', ua))
        db.commit()
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429

    # --- 第2层：账户锁定检查 ---
    user = db.execute('SELECT * FROM users WHERE username = ? AND status = "active"', (username,)).fetchone()
    if not user:
        # 用户不存在也记录IP尝试，但不暴露用户存在性
        db.execute('INSERT INTO login_attempts (ip_address) VALUES (?)', (ip,))
        db.execute('INSERT INTO login_logs (username, ip_address, success, fail_reason, user_agent) VALUES (?,?,0,?,?)',
                   (username, ip, 'user_not_found', ua))
        db.commit()
        return jsonify({'error': '用户名或密码错误'}), 400

    if user['locked_until']:
        try:
            lock_time = datetime.strptime(user['locked_until'], '%Y-%m-%d %H:%M:%S')
            if datetime.now() < lock_time:
                remaining = int((lock_time - datetime.now()).total_seconds())
                db.execute('INSERT INTO login_logs (username, user_id, ip_address, success, fail_reason, user_agent) VALUES (?,?,?,0,?,?)',
                           (username, user['id'], ip, 'locked', ua))
                db.commit()
                return jsonify({'error': f'账户已锁定，请 {remaining} 秒后再试'}), 429
        except (ValueError, TypeError):
            pass  # 无效的锁定时间，忽略

    # --- 密码验证 (version: 1=SHA256, 2=bcrypt) ---
    pw_version = user['password_version'] if 'password_version' in user.keys() else 1
    password_ok = False
    if pw_version == 1:
        # 旧 SHA-256 验证
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        if user['password'] == pw_hash:
            password_ok = True
            # 透明升级到 bcrypt
            try:
                new_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                db.execute('UPDATE users SET password = ?, password_version = 2 WHERE id = ?',
                           (new_hash, user['id']))
            except Exception:
                pass  # 升级失败不影响登录
    elif pw_version == 2:
        # bcrypt 验证
        try:
            password_ok = bcrypt.checkpw(password.encode(), user['password'].encode())
        except Exception:
            password_ok = False

    if not password_ok:
        # 记录失败尝试
        db.execute('INSERT INTO login_attempts (ip_address) VALUES (?)', (ip,))
        fail_count = (user['failed_login_count'] or 0) + 1
        if fail_count >= 5:
            lock_until = (datetime.now() + timedelta(minutes=_lock_minutes(fail_count))).strftime('%Y-%m-%d %H:%M:%S')
            db.execute('UPDATE users SET failed_login_count = ?, locked_until = ? WHERE id = ?',
                       (fail_count, lock_until, user['id']))
        else:
            db.execute('UPDATE users SET failed_login_count = ? WHERE id = ?',
                       (fail_count, user['id']))
        db.execute('INSERT INTO login_logs (username, user_id, ip_address, success, fail_reason, user_agent) VALUES (?,?,?,0,?,?)',
                   (username, user['id'], ip, 'wrong_password', ua))
        db.commit()
        remaining_attempts = max(5 - fail_count, 0)
        if remaining_attempts > 0:
            return jsonify({'error': f'用户名或密码错误（还剩 {remaining_attempts} 次机会）'}), 400
        return jsonify({'error': '用户名或密码错误，账户已锁定'}), 400

    # --- 登录成功：清零失败计数 + 解锁 + 生成token ---
    token = secrets.token_hex(32)
    db.execute('''UPDATE users SET token = ?, last_active = datetime("now","localtime"),
                  failed_login_count = 0, locked_until = NULL WHERE id = ?''',
               (token, user['id']))
    db.execute('INSERT INTO user_sessions (user_id, token, ip_address, user_agent) VALUES (?,?,?,?)',
               (user['id'], token, ip, ua))
    db.execute('INSERT INTO login_logs (username, user_id, ip_address, success, user_agent) VALUES (?,?,?,1,?)',
               (username, user['id'], ip, ua))
    db.commit()

    u = dict(user)
    u['token'] = token
    del u['password']
    u['permissions'] = get_user_permissions(u)
    resp = jsonify({'user': u, 'must_change_password': bool(u.get('must_change_password', 0))})
    # Set httpOnly secure cookie (SameSite=Lax for CSRF protection)
    resp.set_cookie('qr_token', token, httponly=True,
                    samesite='Lax', max_age=86400*7, path='/')
    return resp


@app.route('/api/auth/logout', methods=['POST'])
@check_auth
def logout():
    db = get_db()
    db.execute('UPDATE users SET token = NULL WHERE id = ?', (g.current_user['id'],))
    db.execute('UPDATE user_sessions SET is_active = 0 WHERE token = ?', (g.token,))
    db.commit()
    resp = jsonify({'message': '已退出'})
    resp.set_cookie('qr_token', '', httponly=True, secure=True,
                    samesite='Lax', max_age=0, path='/')
    return resp


@app.route('/api/auth/sessions', methods=['GET'])
@check_auth
def list_sessions():
    """当前用户的所有活跃会话"""
    db = get_db()
    rows = db.execute('''
        SELECT id, ip_address, user_agent, is_active, created_at, last_active,
               (token = ?) as is_current
        FROM user_sessions
        WHERE user_id = ? AND is_active = 1
        ORDER BY created_at DESC
    ''', (g.token, g.current_user['id'])).fetchall()
    return jsonify({'sessions': [dict(r) for r in rows]})


@app.route('/api/auth/sessions/<int:sid>', methods=['DELETE'])
@check_auth
def delete_session(sid):
    """踢掉指定会话（只能踢自己的，或管理员踢任意）"""
    db = get_db()
    sess = db.execute('SELECT * FROM user_sessions WHERE id = ?', (sid,)).fetchone()
    if not sess:
        return jsonify({'error': '会话不存在'}), 404
    from modules.middleware.auth import has_permission
    if sess['user_id'] != g.current_user['id'] and not has_permission(g.current_user, 'users:edit'):
        return jsonify({'error': '无权限'}), 403
    db.execute('UPDATE user_sessions SET is_active = 0 WHERE id = ?', (sid,))
    # 同时清理 users.token 如果被踢的是当前token
    if sess['token']:
        db.execute('UPDATE users SET token = NULL WHERE token = ?', (sess['token'],))
    db.commit()
    return jsonify({'message': '会话已终止'})


@app.route('/api/auth/info', methods=['GET'])
@check_auth
def auth_info():
    u = dict(g.current_user)
    u.pop('password', None)
    u.pop('token', None)
    u.pop('failed_login_count', None)
    u.pop('locked_until', None)
    u.pop('password_version', None)
    u['permissions'] = get_user_permissions(g.current_user)
    return jsonify({'user': u, 'must_change_password': bool(u.get('must_change_password', 0))})


@app.route('/api/auth/change-password', methods=['POST'])
@check_auth
@validate_json('change_password')
def change_password():
    """修改当前用户密码（首次登录强制修改或主动修改）"""
    data = get_json_body()
    new_password = data.get('new_password', '').strip()
    if not new_password or len(new_password) < 6:
        return jsonify({'error': '新密码至少需要6位'}), 400
    
    db = get_db()
    pw_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    db.execute('UPDATE users SET password = ?, password_version = 2, must_change_password = 0 WHERE id = ?',
               (pw_hash, g.current_user['id']))
    db.commit()
    audit_log('change_password', 'user', g.current_user['id'])
    return jsonify({'message': '密码修改成功'})
