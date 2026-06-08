# 扫码报工生产管理系统 v2.0

基于 Flask + SQLite 的生产管理二维码扫码报工系统，支持订单管理、工序流转、质量检验、实时大屏看板。

## 技术栈

| 层级 | 技术 |
|---|---|
| 后端 | Python 3.12 / Flask 3.0 / Gunicorn |
| 数据库 | SQLite (WAL模式) |
| 前端 | Vue 3 (CDN) / Vanilla JS / Chart.js |
| 扫码 | jsQR + BarcodeDetector 双引擎 |
| 部署 | PM2 + Nginx / Docker |

## 快速开始

### 方式一：Docker（推荐）

```bash
# 构建并启动
docker-compose up -d

# 带 Nginx 反向代理
docker-compose --profile with-nginx up -d

# 访问
https://localhost:3000
```

### 方式二：手动部署

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 设置 SECRET_KEY

# 生成 SSL 证书（如无）
openssl req -x509 -newkey rsa:2048 -keyout server.key -out server.crt -days 3650 -nodes

# 启动（开发）
python3 server.py

# 启动（生产 - PM2）
pm2 start ecosystem.config.cjs
```

## 项目结构

```
qr-system/
├── modules/
│   ├── app.py              # Flask 应用实例
│   ├── db.py               # 数据库初始化/迁移
│   ├── config.py            # 配置常量
│   ├── cache_utils.py       # TTL 缓存装饰器
│   ├── export_utils.py      # Excel 导出工具
│   ├── middleware/           # 中间件
│   │   ├── auth.py          # 认证/权限
│   │   ├── error_handler.py # 全局错误处理
│   │   ├── request_tracker.py # 请求追踪
│   │   ├── rate_limit.py    # 速率限制
│   │   ├── validate.py      # JSON Schema 验证
│   │   └── helpers.py       # 辅助函数
│   └── routes/              # API 路由
│       ├── auth.py          # 登录/登出
│       ├── orders.py        # 订单 CRUD
│       ├── scan.py          # 扫码报工 + QR 生成
│       ├── dashboard.py     # 仪表盘
│       ├── board.py         # 大屏看板
│       ├── reports.py       # 统计报表
│       ├── exports.py       # Excel 导出
│       ├── notifications.py # 通知中心
│       ├── quality.py       # 质量检验
│       ├── inventory.py     # 库存管理
│       └── ...              # 其他路由
├── public/                  # 前端静态资源
│   ├── index-v2.html        # 主页面
│   ├── mobile.html          # 移动端扫码
│   ├── bigscreen.html       # 车间大屏
│   ├── board.html           # 生产看板
│   ├── audit-logs.html      # 操作日志
│   ├── batch-qr.html        # 批量QR码
│   ├── reports.html         # 报表页面
│   ├── sw.js / offline.html # PWA 离线支持
│   └── components/          # Vue 组件
├── scripts/
│   ├── db-maintenance.py    # 数据库维护（VACUUM/清理）
│   ├── backup-db.sh         # 数据库备份
│   └── heartbeat.sh         # 心跳检测
├── tests/                   # pytest 测试
├── data/                    # 数据库 + 备份 + 附件
├── logs/                    # 应用日志
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── ecosystem.config.cjs     # PM2 配置
├── nginx-qr-system.conf     # Nginx 配置（生产）
└── nginx-docker.conf        # Nginx 配置（Docker）
```

## API 端点

### 认证
- `POST /api/auth/login` - 登录
- `POST /api/auth/logout` - 登出
- `GET /api/auth/me` - 当前用户信息

### 核心业务
- `GET/POST /api/orders` - 订单列表/创建
- `GET/PUT/DELETE /api/orders/:id` - 订单详情/更新/删除
- `POST /api/scan/report` - 扫码报工
- `GET /api/scan/qr/:order_id` - 生成订单 QR 码

### 看板 & 报表
- `GET /api/dashboard` - 仪表盘数据
- `GET /api/dashboard/board` - 大屏看板数据
- `GET /api/export/orders` - 导出订单 Excel
- `GET /api/export/work-records` - 导出报工记录 Excel

### 系统
- `GET /api/health` - 健康检查
- `GET /api/notifications` - 通知列表
- `GET /api/notifications/unread-count` - 未读通知数
- `GET /api/logs` - 操作日志

## 运维命令

```bash
# PM2 管理
pm2 status                # 查看状态
pm2 restart qr-system     # 重启
pm2 logs qr-system        # 查看日志

# 数据库维护
python3 scripts/db-maintenance.py  # 手动维护
sqlite3 data/production.db ".backup data/backups/manual.db"  # 手动备份

# 健康检查
curl -sk https://127.0.0.1/api/health

# 运行测试
cd tests && python3 -m pytest test_core_flow.py -v
```

## Cron 定时任务

| 时间 | 任务 |
|---|---|
| 每5分钟 | 心跳检测 `scripts/heartbeat.sh` |
| 每天2:00 | 数据库维护 `scripts/db-maintenance.py` |
| 每天3:00 | 数据库备份 `scripts/backup-db.sh` |

## 架构演进历史

| 版本 | 主要变更 |
|---|---|
| P0 | Nginx SSL / SECRET_KEY / PM2 / 安全头 |
| P1 | CORS / logrotate / 健康检查 / 心跳 |
| P2 | 附件文件系统 / 备份验证 / pytest |
| P3 | PWA / 扫码乐观锁 / Dashboard 缓存 |
| P4 | 代码清理 / RequestTracker / Excel导出 / DB索引 |
| P5 | 通知中心 / 操作日志UI / 扫码增强 / 批量QR |
| P6 | Docker / 大屏增强 / DB自动维护 |
