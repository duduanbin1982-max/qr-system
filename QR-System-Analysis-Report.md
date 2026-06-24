# 扫码报工生产管理系统 — 深度技术解析报告

> **生成时间**：2026-06-13  
> **系统版本**：v3 (Vite 5 + Vue 3 SFC)  
> **部署地址**：https://192.168.1.8/  
> **服务器**：Ubuntu 24.04.3 LTS (192.168.1.8)

---

## 一、系统架构总览

```
┌──────────────────────────────────────────────────────┐
│                    Nginx 1.24                        │
│   :80 → 301 HTTPS   :443 → proxy_pass :3000         │
│   /static/ → public/static/  (7天缓存)              │
├──────────────────────────────────────────────────────┤
│               Gunicorn (systemd)                     │
│   2 workers  |  bind 127.0.0.1:3000                 │
│   Python 3.12.3  |  Flask                           │
├──────────────────────────────────────────────────────┤
│                 SQLite (WAL 模式)                    │
│   /data/production.db  |  46 表  |  备份每日        │
├──────────────────────────────────────────────────────┤
│              Vite 5 + Vue 3 SFC                      │
│   26 组件  |  4 composables  |  485KB JS + 75KB CSS │
└──────────────────────────────────────────────────────┘
```

### 1.1 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| OS | Ubuntu LTS | 24.04.3 |
| Web Server | Nginx | 1.24.0 |
| 应用服务器 | Gunicorn + Flask | Python 3.12.3 |
| 数据库 | SQLite (WAL) | 3.x |
| 前端构建 | Vite | 8.0.16 |
| 前端框架 | Vue 3 SFC | Composition API |
| 进程管理 | systemd | qr-system.service |
| Node.js | 构建环境 | v20.20.2 |

### 1.2 部署架构

- **HTTPS**：自签证书 `/home/dubin/qr-system/server.crt`
- **安全头**：X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, HSTS
- **速率限制**：60 req/s per IP burst 20
- **文件上传**：最大 16MB
- **代理超时**：读写 120s
- **服务自启**：systemd enable + Restart=always

---

## 二、数据库分析

### 2.1 统计概览

| 指标 | 数值 |
|------|------|
| 总表数 | 46 |
| 有数据表 | 30 |
| 空表 | 16 |
| 核心业务表 | products(134), work_records(37), users(31), processes(27) |
| 日志/审计表 | audit_logs(1434), login_logs(118), user_sessions(469) |

### 2.2 核心业务表

| 表名 | 行数 | 说明 |
|------|------|------|
| `products` | 134 | 产品主数据（结构件+机加工） |
| `work_records` | 37 | 报工记录 |
| `users` | 31 | 用户（含管理员、普通员工） |
| `processes` | 27 | 工序定义 |
| `materials` | 19 | 物料/钢板 |
| `customers` | 9 | 客户信息 |
| `process_routes` | 11 | 工序路线（11条路线） |
| `process_route_items` | 45 | 路线-工序关联 |
| `process_prices` | 40 | 工序工价 |
| `route_prices` | 43 | 路线工价 |
| `orders` | 1 | 订单 |
| `product_items` | 6 | 产品明细/序列号 |

### 2.3 权限与角色表

| 表名 | 行数 | 说明 |
|------|------|------|
| `roles` | 5 | 角色定义 |
| `role_groups` | 3 | 角色组 |
| `user_roles` | 31 | 用户-角色关联 |
| `menu_permissions` | 20 | 菜单权限配置 |
| `positions` | 9 | 岗位定义 |
| `position_processes` | 18 | 岗位-工序关联 |

### 2.4 空表（已建但无数据）

| 表名 | 说明 | 原因 |
|------|------|------|
| `approval_records` | 审批记录 | 未启用审批流程 |
| `approval_config` | 审批配置 | 未配置 |
| `rework_records` | 返工记录 | 无返工发生 |
| `quality_inspections` | 质量检验 | 未启用 |
| `material_consumptions` | 物料消耗 | 未记录 |
| `scrap_records` | 报废记录 | 无报废 |
| `operation_logs` | 操作日志 | 系统用 audit_logs 代替 |
| `product_attachments` | 产品附件 | 未上传 |
| `user_processes` | 用户工序分配 | 未配置 |
| `order_remark_history` | 订单备注历史 | 无修改 |

---

## 三、后端 API 体系

### 3.1 模块路由清单（35 个路由文件，~100 个 API 端点）

| 模块 | 文件 | 核心端点 |
|------|------|----------|
| 认证 | `auth.py` | login, logout, sessions, reset-password |
| 用户 | `users.py` | CRUD, reset-password |
| 角色 | `roles.py` | role-groups CRUD, roles CRUD |
| 岗位 | `positions.py` | CRUD |
| 权限 | `audit_logs.py` | permissions, menu-permissions, batch-roles |
| 产品 | `products.py` | CRUD, search, route-pricing |
| 工序 | `processes.py` | CRUD, impact |
| 工序路线 | `process_routes.py` | CRUD, apply |
| 工价 | `prices.py` | process-prices CRUD, route-pricing |
| 订单 | `orders.py` | CRUD, next-no, attachments, remarks |
| 客户 | `customers.py` | CRUD, orders |
| 物料 | `materials.py` | CRUD, logs, consumptions |
| 扫码报工 | `scan_work.py` / `scan_qr.py` | scan, mobile/scan, qrcode, batch |
| 库存 | `inventory.py` | CRUD, stock-in, stock-out |
| 发货 | `shipments.py` | CRUD, draft |
| 统计 | `stats.py` | daily, worker, scrap, order-progress |
| 报表 | `reports.py` | production-trend, worker-efficiency, quality, order-analysis |
| 看板 | `board.py` | dashboard/board |
| 工作台 | `dashboard.py` | stats, trend |
| 追溯 | `trace.py` | trace/:code |
| 排程 | `schedule.py` | gantt |
| 审批 | `approvals.py` | pending, history, approve/reject |
| 返工 | `rework.py` | CRUD, stats, complete |
| 质检 | `quality.py` | inspections CRUD, stats, defect-pareto |
| 导入 | `imports.py` | preview, orders, products, customers, template |
| 导出 | `exports.py` | orders, work-records |
| 通知 | `notifications.py` | list, read, read-all |
| 邮件 | `email_reports.py` | test, daily, weekly |
| 系统 | `system.py` | health, backup, check-integrity |
| 进度 | `progress.py` | order progress, delivery-alerts |
| 设置 | `settings.py` | public, CRUD |
| 个人 | `personal_stats.py` | personal/stats |
| 密码 | `password_security.py` | auth/reset-password |

---

## 四、前端架构

### 4.1 构建体系

| 指标 | 值 |
|------|-----|
| 框架 | Vue 3 Composition API + Vite 5 |
| 组件数 | 26 个 SFC |
| Composables | useProduct, useOrder, useBoard, useSettings |
| Lib | api.js, auth.js, router.js, store.js |
| CSS | 75KB (全局统一样式，CSS 变量体系) |
| JS Bundle | 485KB gzip:120KB |
| 构建时间 | ~800ms |

### 4.2 26 个 Vue SFC 组件

| 组件 | 功能 | 状态 |
|------|------|------|
| `AppLayout.vue` | 全局布局 + 侧边栏 | ✅ |
| `LoginPage.vue` | 登录页 + 改密 | ✅ |
| `DashboardPage.vue` | 工作台（产量/订单/安全） | ✅ |
| `ProductionSettings.vue` | 生产管理（8 子模块 Tab） | ✅ |
| `BasicSettings.vue` | 基础设置（5 子模块 Tab） | ✅ |
| `SettingsPage.vue` | 系统设置 | ✅ |
| `OrderList.vue` | 订单管理 | ✅ |
| `CustomerList.vue` | 客户管理 | ✅ |
| `ProductList.vue` | 产品管理 | ✅ |
| `MaterialList.vue` | 物料管理 | ✅ |
| `UserList.vue` | 员工管理 | ✅ |
| `ProcessList.vue` | 工序管理 | ✅ |
| `RouteList.vue` | 工序路线 | ✅ |
| `PriceList.vue` | 工价管理 | ✅ |
| `InventoryList.vue` | 库存管理 | ✅ |
| `ShipmentList.vue` | 发货管理 | ✅ |
| `StatsPage.vue` | 统计报表 | ✅ |
| `ReportsPage.vue` | 数据分析 | ✅ |
| `BoardPage.vue` | 数据看板 | ✅ |
| `ScanReport.vue` | 扫码报工 | ✅ |
| `TracePage.vue` | 产品追溯 | ✅ |
| `ApprovalPage.vue` | 审批管理 | ✅ |
| `GanttChart.vue` | 生产排程 | ✅ |
| `ReworkList.vue` | 返工管理 | ✅ |
| `InspectionList.vue` | 质量检验 | ✅ |
| `WageList.vue` | 工资核算 | ✅ |

### 4.3 独立页面

| 文件 | 用途 | 说明 |
|------|------|------|
| `mobile.html` | 移动端扫码报工 | 手机浏览器访问 |
| `board.html` | 数据看板（独立） | 大屏/Kiosk 展示 |
| `bigscreen.html` | 大屏看板 | 更高分辨率 |
| `swagger-ui.html` | API 文档 | Swagger UI (默认禁用) |
| `offline.html` | 离线页面 | PWA 离线提示 |

---

## 五、安全体系

### 5.1 认证与授权

| 层面 | 实现 |
|------|------|
| 登录 | 密码哈希 (bcrypt) + Session Token |
| 会话管理 | `user_sessions` 表，支持踢出 |
| 首次登录 | 强制修改密码 (`must_change_password`) |
| 密码策略 | 最少 8 位 |
| 账户锁定 | 连续失败锁定 |
| 闲置登出 | `session_idle_minutes` 可配置 |
| RBAC | 角色-权限-菜单三级控制 |
| 细粒度权限 | menu_permissions 按页面配置 |

### 5.2 网络安全

| 措施 | 配置 |
|------|------|
| HTTPS | 强制 HTTP→HTTPS 301 |
| HSTS | max-age=31536000 |
| CSP | style-src 'self' 'unsafe-inline' unpkg.com |
| XSS 防护 | X-XSS-Protection 头 |
| 速率限制 | 60 req/s |
| 文件上传 | 限制 16MB |

### 5.3 数据安全

| 措施 | 实现 |
|------|------|
| 自动备份 | 每日 03:00，保留在 `data/backups/` |
| 完整性检查 | `/api/system/check-integrity` |
| 审计日志 | `audit_logs` 表，1434 条记录 |
| 登录日志 | `login_logs` 表，118 条记录 |

---

## 六、核心业务流程

### 6.1 扫码报工主流程

```
管理员创建订单 → 生成二维码 → 工人扫码 → 手机端报工
                                          ↓
                            work_records 记录工序+数量
                                          ↓
                            审批(可选) → 统计报表 → 工资核算
```

### 6.2 模块依赖关系

```
基础数据层:  产品 → 工序 → 工序路线 → 工价
          客户 → 物料 → 岗位 → 角色

业务层:    订单（关联产品+客户+路线）
              ↓
          扫码报工（work_records）
              ↓
          库存管理 → 发货管理

管理层:    统计报表 → 数据分析 → 数据看板
          工资核算 → 审批管理 → 质量检验

系统层:    用户管理 → 角色管理 → 权限管理
          操作日志 → 系统设置
```

---

## 七、当前数据概览

| 类别 | 数量 |
|------|------|
| 产品 (结构件+机加工) | 134 |
| 工序 | 27 |
| 工序路线 | 11 |
| 工价记录 | 40 (工序) + 43 (路线) |
| 物料 | 19 |
| 客户 | 9 |
| 供应商 | 1 |
| 用户 | 31 |
| 角色 | 5 |
| 角色组 | 3 |
| 岗位 | 9 |
| 订单 | 1 |
| 报工记录 | 37 |
| 审计日志 | 1,434 |
| 登录日志 | 118 |

---

## 八、已知问题与风险

### 8.1 技术债务

| 级别 | 问题 | 影响 |
|------|------|------|
| 🔴 | Vite v3 迁移后部分功能未回归测试 | 某些边缘功能可能异常 |
| 🟡 | SQLite 单机，写串行化 | 不适合 50+ 并发 |
| 🟡 | Token 明文在 URL (看板) | 日志/历史泄露风险 |
| 🟡 | 6 个模块表空但路由存在 | 未经过实战验证 |
| 🟡 | `board_token` 无过期机制 | 长期泄露风险 |
| 🟢 | 自签证书 | 浏览器警告 |

### 8.2 缺失功能

| 功能 | 优先级 |
|------|--------|
| CI/CD 自动部署 | P1 |
| 自动化测试 | P1 |
| 看板 token 轮换 | P2 |
| scrap_records 写入 API | P2 |
| 审批流程完整配置 | P2 |

---

## 九、投入生产建议

### 9.1 当前可投产的场景

- ✅ 20-50 人车间规模
- ✅ 扫码报工核心流程
- ✅ 产品/订单/客户/物料基础管理
- ✅ 统计报表与工资核算
- ✅ 移动端扫码（mobile.html）
- ✅ 大屏看板（board.html）

### 9.2 投产前必做

- 🔴 **全模块端到端回归测试**（以真实数据走通全部流程）
- 🔴 **配置生产级 SSL 证书**（Let's Encrypt）
- 🔴 **确认每日备份正常运行**
- 🟡 **配置 systemd 开机自启**
- 🟡 **设置监控告警（磁盘/内存/服务）**

### 9.3 中远期演进

- 数据库迁移至 PostgreSQL（50+ 并发场景）
- 引入 Redis 缓存热数据
- Docker Compose 容器化
- 构建 CI/CD Pipeline
- 引入自动化测试套件

---

## 十、总结

该系统是一个**功能完整、架构清晰的中小型制造企业扫码报工系统**。覆盖了从产品定义、工序路线、订单管理、扫码报工、库存发货到统计核算的完整生产管理闭环。前端已迁移至 Vite 5 + Vue 3 SFC 现代构建体系，后端采用 Flask 模块化分层。当前处于投产前最后验证阶段，核心流程可用，边缘模块（审批/质检/返工等）待实战数据激活。