#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫码报工生产管理系统 V2 — 入口文件
Flask + SQLite，内网部署。路由通过模块化装饰器注册。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import render_template, make_response, g
from modules.app import app
from modules.config import PUBLIC_DIR
from modules.db import close_db

# 注册 teardown 回调
app.teardown_appcontext(close_db)

# 加载路由模块（装饰器在 import 时自动注册 @app.route）
import modules.routes.auth        # login/logout/info
import modules.routes.dashboard
import modules.routes.board   # dashboard/board
import modules.routes.orders      # orders CRUD + batch + work-records
import modules.routes.customers   # customers CRUD + order history
import modules.routes.prices      # process-prices + route-prices + wages
import modules.routes.products    # products CRUD + import + attachments
import modules.routes.scan        # desktop scan + mobile H5 + QR codes
import modules.routes.reports     # stats + production trends + efficiency
import modules.routes.processes   # 工序管理
import modules.routes.users       # 用户管理
import modules.routes.order_attachments  # 订单附件
import modules.routes.settings    # 系统设置
import modules.routes.roles       # 角色组+角色管理
import modules.routes.audit_logs  # 操作日志+权限+用户角色
import modules.routes.inventory   # 库存管理
import modules.routes.shipments   # 出库管理
import modules.routes.process_routes  # 工序路线管理
import modules.routes.trace       # 产品追溯
import modules.routes.approvals   # 审批管理
import modules.routes.positions   # 岗位管理
import modules.routes.materials    # 物料管理
import modules.routes.schedule   # 生产排程
import modules.routes.rework     # 返工管理
import modules.routes.quality   # 质量检验
import modules.routes.stats     # 统计报表

import modules.routes.exports      # Excel export
import modules.routes.notifications  # 通百中心
import modules.routes.password_security  # 密码安全Bpassword policy
import modules.routes.imports         # CSV/Excel bulk import
import modules.routes.order_notes    # order remark history
import modules.routes.personal_stats # personal mobile stats
import modules.routes.email_reports  # email reports
import modules.routes.progress       # process progress + delivery alerts
import modules.routes.system         # health, backup, integrity checks
# CORS + OPTIONS 统一在 app.py 的 @app.after_request 中处理

# ============================================================
# Static files
# ============================================================
@app.route('/')
def index():
    resp = make_response(render_template('index-v2.html', nonce=getattr(g, 'csp_nonce', '')))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/<path:filename>')
def static_files(filename):
    """Serve static assets (js/, css/, vendor/, etc.) from PUBLIC_DIR.
    
    Safety: reject paths starting with 'api/' to prevent shadowing API routes.
    HTML files are rendered as Jinja2 templates for CSP nonce injection.
    """
    if filename.startswith('api/') or filename.startswith('api'):
        from flask import abort
        abort(404)
    try:
        if filename.endswith('.html'):
            resp = make_response(render_template(filename, nonce=getattr(g, 'csp_nonce', '')))
        else:
            resp = app.send_static_file(filename)
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    except Exception:
        from flask import abort
        abort(404)

# ============================================================
if __name__ == '__main__':
    from modules.db import init_db
    init_db()
    print('=== 扫码报工生产管理系统 V2 ===')
    import ssl
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain("server.crt", "server.key")
    app.run(host="0.0.0.0", port=3000, debug=False, ssl_context=ssl_ctx)