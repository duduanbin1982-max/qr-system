# 全量架构审计修复 Task 0–1 基线与验收契约

## 基线

- 生产只读核实提交：`56aea9265e285b9a7ac663fe3868af7a1f89209c`
- 修复分支：`codex/deployment-fact-safe-rollback`
- 数据库版本：V096
- 生产服务只读核实：`qr-system.service=active`
- 审计基线：后端 `1690 passed`、前端单元 `333 passed`、浏览器 E2E `24/25`
- 本阶段不得连接生产数据库执行写入、停服、重启或文件替换。

## Task 0 行为保护

1. 最终备份必须在业务写入围栏建立后生成。
2. 新版本启动并通过健康检查时，围栏仍必须生效。
3. 围栏生效时：
   - API 的 `POST/PUT/PATCH/DELETE` 返回 `503 deployment_write_fenced`；
   - Flask 数据库连接启用 SQLite `query_only`；
   - `/api/health` 保持可读，并明确返回 `write_fenced=true` 和部署幂等键。
4. 自动回退前必须先保存失败现场数据库、附件和前端发布文件。
5. 自动回退仅允许发生在写入围栏仍然有效、生产写入从未放行的阶段。
6. 一旦 manifest 记录 `release_authorized`，旧数据库备份不得再被自动覆盖回生产库。
7. 围栏证据缺失、损坏、幂等键不匹配或目标提交不匹配时必须 fail closed。

## Task 1 实现边界

- `modules/deployment_write_fence.py`：运行时只读解析围栏；损坏证据视为围栏开启。
- `modules/app_extensions.py`：HTTP 写请求阻断。
- `modules/db.py`：围栏下连接启用 `PRAGMA query_only=ON`。
- `modules/app.py`：健康接口公开围栏状态。
- `scripts/deployment_manifest.py`：围栏状态机、事实水位、附件清单、失败现场和恢复授权。
- `deploy.sh`：围栏建立后停服和最终备份；围栏下启动验收；授权后才开放写入。
- `scripts/rollback-deployment.sh`：围栏下恢复和验收，成功后才解除围栏。

## 发布前验收门禁

- 部署、生产操作和特征测试全部通过。
- `bash -n` 和 Python 编译检查通过。
- 后端全量、前端单元、构建、API facade、导入环和 E2E 全部重新执行。
- 在临时目录演练以下两条路径：
  1. 围栏内失败：保存失败现场后允许恢复最终备份；
  2. 正式放行后失败：自动破坏性恢复被拒绝，保留现场并转人工受控恢复。
- 本阶段单独 PR，不混入库存、排程或绩效重构。

## 本地实施验证结果

- 后端全量：`1701 passed`。
- 前端单元：`333 passed`。
- 部署与回退专项：`41 passed`（后续补充回退授权持久化失败注入后为 `42 passed`）。
- API facade、前端导入环、生产构建、Shell 语法、Python 编译和 `git diff --check`：通过。
- 浏览器 E2E：`24/25`；唯一失败为基线已存的库存移动端冻结列遮挡详情操作，与本阶段部署围栏和回退修复无代码交集。
- 在该 E2E 基线问题单独修复前，本分支不得进入生产发布。
