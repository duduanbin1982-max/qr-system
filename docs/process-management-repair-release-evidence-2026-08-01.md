# 工艺管理模块修复发布记录

日期：2026-08-01
生产主机：`192.168.1.8` (`codex-8`)
项目：`/home/dubin/qr-system`

## 已实施

- 建立 28 张表的工序引用注册表，包含工时、质量评价、交接评价、用户授权、在制工件和工价历史等原遗漏引用。
- 新增 v49 数据库迁移和 `prevent_referenced_process_delete` 触发器；已引用工序只能停用，不能物理删除。
- `/api/process-routes/<id>/apply` 同时要求 `routes:edit` 和 `orders:edit`，并执行订单工序数据范围检查。
- 路线应用统一委托 `OrderProcessSyncService`，与订单编辑共用同一套校验和同步逻辑。
- 停用工序禁止新增到路线、岗位和订单；历史路线、岗位与在制订单保持可读和可继续流转。
- 工序和路线分类限定为“结构件”、“机加工”，路线分类为权威分类，路线内工序必须同类。
- 修复工序列表初次加载重试、工序总数、路线分类总数和节点总数。

## 备份与迁移

- 迁移前备份：`/home/dubin/qr-system/data/backups/production_20260801_072558.db`
- SHA-256：`a5964587de36bc88b8996718284ba5327351c7e683f0aebbddc0765174f1a7f3`
- 数据库版本：`48 -> 49`
- 工序数：`31 -> 31`
- `PRAGMA integrity_check`：`ok`
- 路线/工序分类不一致：`0`
- 发布前后 `foreign_key_check` 均为同一组 6 条用户/会话历史孤儿，本次迁移未新增外键错误。

## 验证结果

- 后端全量：`406 passed`
- 生产目录工艺相关定向：`44 passed`
- 前端全量：`15 files, 39 passed`
- API 门面检查：通过
- 前端 import-cycle 检查：通过
- Vite 生产构建：通过
- 生产 Service 冒烟：31 个工序、49 条路线、296 个路线节点，汇总一致
- `qr-system.service`：`active`
- `https://127.0.0.1/api/health`：`status=ok`
- 新构建的 `ProcessList` 和 `RouteList` 静态资源：HTTP 200

## 保留回滚点

- 代码回滚副本：`/home/dubin/qr-system/.process-fix-backup-20260801`
- 静态资源回滚副本：`/home/dubin/qr-system/.process-fix-static-backup-20260801/static`

生产管理员当前没有可用的已登录会话，因此未伪造会话或修改密码进行浏览器管理页验收。已用生产配置下的只读 Service 冒烟、静态资源 HTTP 检查和完整自动化回归替代。
