# Task 4：稳定运维入口与验证

日期：2026-10-13。

工作树：`.worktrees/architecture-task4-operations-facade`。
分支：`codex/architecture-task4-operations-facade`。
Git 基线：`970b99817897fdf395999ffe3f6c0167e919123f`。

## 稳定入口

建立 `modules/application/operations_facade.py`，脚本通过 `OperationsFacade` 和稳定 DTO 操作系统。
应用层组合迁移、排程、运行环境、绩效、预检及部署适配器，内部实现不向脚本返回。
Facade 导入不会初始化 Flask、读取配置、打开数据库或运行迁移。

| 操作 | 安全及兼容边界 |
| --- | --- |
| 精确工时预检 | 只读源连接，SQLite online backup 到临时副本，保留原报告字段 |
| 迁移计划 | 只读连接，仅返回不可变版本与描述，不泄漏迁移 callback |
| 显式迁移步骤重放 | 保留调用方事务与旧 user_version 更新规则 |
| 副本回放与影子试排 | 自动清理的独立副本，源数据不写入 |
| 部署验收 | 检查健康、完整 SHA、schema、完整性和外键 |
| 回退检查 | 对比数据库逻辑事实摘要与明确捕获的附件摘要 |
| E2E 应用启动 | Facade 内启动，不向脚本返回 Flask app |
| 绩效验收环境 | 受限上下文与普通设置字典，不返回 Flask app |
| 受控业务和审计操作 | 保留脚本原有显式授权、幂等和操作人检查 |

副本复制拒绝源与目标相同、已有目标和符号链接目标，保留 WAL 中已提交事实；
复制失败清理本次新建的副本。预检与 V092–V094 回放使用统一复制入口。
V094 看板与动态重排验收支持最新 schema 且最低版本为 V094，避免在 V096 上总被旧等号检查阻断。

原有脚本中低层文件、SQLite 连接及脚本间依赖仍由运维安全逻辑管理；
本阶段收敛的是应用内部 Service/Repository/Migration/Bootstrap 依赖，
没有重新设计所有运维 SQL 或放松生产写入授权。
修复工时、迁移和切换工具保留原参数与安全检查。

## 迁移范围

约 38 个 Python 脚本以及 `deploy.sh`、`scripts/build.sh` 的应用内部调用完成替换，
包括精确工时、迁移计划、E2E、V091–V094 回放、节点运维、绩效和工资历史、
工序版本、权限目录、受控代码发布等入口。

部署脚本的围栏、停服、最终备份、附件处理、迁移、前端发布、提交标记、重启、
健康验收及失败回退顺序保持原有契约。仅替换内部入口，未执行脚本。

新增架构门禁递归扫描 `scripts/**/*.py`，同时检查内嵌 Python、嵌套导入和 shell 入口。
故意违规 fixture 必须被阻断。门禁由 `npm run check:architecture` 调用。
移除 Repository 或迁移内部模块的直接导入，无白名单放行旧脚本。

## 验证证据

全量后端：1796 passed，耗时 493.86 秒。
日志：`data/task4-backend-final.log`；最后副本复制入口补强由下述 26 项定向测试再次验证。

- 部署、受控代码发布、节点/工序运维与 Facade 定向回归：189 passed。
- 统一预检副本复制之后的 Facade 与脚本边界定向测试：26 passed。
- 架构检查：30 passed。
- API facade：34 namespaces / 455 domain methods。
- 前端导入环：219 files / 532 edges。
- 前端单元测试：55 files / 339 passed。
- 最终 E2E：25/25 passed；其前置生产构建通过。
- `bash -n deploy.sh scripts/build.sh`、Python 编译和 `git diff --check` 通过。
- 覆盖只读源、WAL 复制、拒绝覆盖、符号链接、嵌套开关恢复、稳定 DTO、
  延迟初始化、独立试排、生产事实摘要不变、附件漂移检测和框架上下文隔离。

本地运行环境：Node v25.2.1、npm 11.6.2；工程声明 Node >=20.19 <21。
本地构建与测试实际通过，但合并前 CI/发布环境仍应按工程声明验证；
此次未改 package.json 或生产运行时。

日志保存在本地忽略的 `data/task4-*.log`。

## 交付与后续

本阶段只完成本地实施与验证，未提交、推送、创建 PR，未连接或修改生产数据库及附件。
没有运行生产 `--apply`、发布、功能开关切换、停服或重启。
Task 3 与 Task 4 是独立分支；分别审核、提交和合并后仍需在合并基线上复核。
生产部署需要针对实际合并 SHA 重新只读核实参数并单独授权。
提交不得包含 `.brooks-lint-history.json`、历史 Task 0 报告、`.tmp-*` 或临时部署脚本。
