# Brooks-debt Task 1：统一工具链

## 范围与状态

- 实施日期：2026-10-15，Asia/Shanghai。
- 从实施时核实的 GitHub `master` 创建分支；基线为 Task 0 / PR #99 的合并提交 `3b8487a019494937700e02be1a78ebbae23a535f`。
- 独立分支：`codex/brooks-debt-task1-toolchain`。
- 对应台账：D07 工具链不一致。本地实现、验证和正式 diff 审核已完成，已提交、推送并创建 PR #100。本修复提交时等待远端复验和合并，D07 尚未关闭，未标记为生产已发布。
- 本阶段固定前端构建/测试工具链，不升级应用依赖，不更改业务代码、数据库、附件、架构例外或发布授权边界。

## 版本选择及执行入口

统一使用 **Node 24.22.0 / npm 11.19.1**，使用官方 Node 发行包自带的 npm。原有 `.nvmrc` 和 `.node-version` 均已受 Git 跟踪，原值为 `20.20.2`；本次更新其内容，并非补建缺失文件。原 `package.json` 声明 Node `>=20.19 <21`、npm `10.8.2`，与本机全局 Node `25.2.1` / npm `11.6.2` 不一致。

选择受支持的 Node 24 LTS，而不是扩大 engines 范围以忽略不匹配。官方发行索引记录本次选定版本发布于 2026-10-14，LTS 名称为 Krypton；官方支持计划中 Node 20 已于 2026-04-30 结束支持，Node 24 支持至 2028-04-30。选型核对来源：

- [Node 官方发行索引](https://nodejs.org/dist/index.json)
- [Node 官方支持计划](https://github.com/nodejs/Release/blob/main/schedule.json)
- [本次发行校验和](https://nodejs.org/dist/v24.22.0/SHASUMS256.txt)
- [npm package.json：engines 和 devEngines](https://docs.npmjs.com/cli/v11/configuring-npm/package-json)

本地验证使用单独解压的官方 Windows x64 发行包，只在验证进程 PATH 中选择该版本；未替换机器全局 Node/npm。压缩包 `node-v24.22.0-win-x64.zip` 的 SHA-256 与官方清单一致：`f9683a19877e12a9b167305c8db71040d812876359de21f0d2e97c3f321f80c3`。

| 入口 | 约束 |
|---|---|
| `.nvmrc`、`.node-version`、`engines`、`packageManager`、`devEngines` | Node/npm 精确版本一致，devEngines 不匹配为 error |
| `.npmrc` | `engine-strict=true`，覆盖忽略生命周期脚本的安装模式 |
| `check:toolchain` / `preinstall` | 无第三方依赖；验证配置、锁文件根元数据、实际 Node/npm；无需先安装项目依赖 |
| 开发、单测、架构检查、构建及预览 | 先检查实际工具链再执行对应命令 |
| `deploy.sh`、前端发布及 Playwright Shell 入口 | 在安装依赖、创建测试临时目录或安装浏览器前检查；`scripts/build.sh` 委托到受保护的前端发布入口 |
| `verify:frontend` | 统一运行工具链 fixture、架构/API/导入环/分层、全量前端、隔离 E2E 和生产构建 |
| GitHub Actions | Windows 与 Ubuntu 24.04 从 `.nvmrc` 选取版本，再运行锁文件安装及同一验证入口 |

CI 固定 Python `3.12.10` 和 pytest `9.0.3` 以满足现有架构及 E2E 服务依赖。首轮远端执行 Ubuntu 通过，Windows 在加载 `Asia/Shanghai` 时因缺少 `tzdata` 失败；原安装步骤只读取 `requirements.txt`，漏装了已有开发依赖。本次改为统一安装 `requirements-dev.txt`，复用其中的生产依赖、固定 pytest 和时区数据依赖。工作流 YAML、两平台矩阵及原验证入口已核对，本地以空 `PYTHONTZPATH` 验证应用时区能从 `tzdata` 包加载。本修复仍须由远端两平台检查确认，本地通过不替代远端 CI 结果。

第二轮远端运行 `38726912742` 中 Ubuntu 继续通过，Windows 已通过时区加载、架构门禁、前端单元测试和 E2E 构建，随后因 E2E 默认数据库路径 `/tmp/qr_system_e2e.db` 的父目录不存在而无法启动测试服务。CI 现显式将 `E2E_DB_PATH` 设置为 `${{ runner.temp }}/qr_system_e2e.db`，复用每个平台已有且按 job 隔离的临时目录；不依赖机器预先创建 `/tmp`。本次只调整 CI 环境，保留原 E2E 断言、用例数量、超时及生产代码。本地 Windows 使用新建临时目录中的原生绝对路径复验 `npm run test:e2e`：25 passed，0 failed / skipped，E2E 用时 1.7 分钟；日志为 `e2e-runner-temp.log`。工作流 YAML、双平台矩阵及临时路径配置验证通过，仍待新提交的远端双平台检查。

## 实际验证结果

下列均为本 Task 实际运行结果，未将 Task 0 的后端全量数重复计为本次结果。所有测试仅使用本地临时数据，没有连接生产主机。

| 检查 | 实际结果 |
|---|---|
| `npm ci --ignore-scripts --no-audit --no-fund` | 成功，安装 186 个包；无 EBADENGINE |
| 最终 `npm run test:toolchain` | 21 passed；0 failed / skipped / cancelled；18:55:41–18:55:45 |
| `E2E_PORT=4188 npm run verify:frontend` | 退出码 0；18:49:36–18:53:05 |
| 该入口的后端架构检查 | 32 passed |
| API facade | 34 namespaces / 455 unique domain methods |
| 前端导入环 | 219 个文件 / 532 条内部边，无环 |
| 前端分层 | fixture 34 passed；531 条边 / 127 条冻结历史边 |
| 全量前端单元测试 | 55 个文件 / 339 passed；0 failed / skipped / todo |
| E2E | 25 passed；0 failed / skipped，无失败重试；隔离数据库及静态目录 |
| 前端生产构建 | 成功，300 个模块；最终 Vite 构建 976 ms |
| 最终后端部署/API 契约复验 | `tests/test_deployment_contracts.py` 和 `tests/test_frontend_api_facade_contracts.py`：40 passed，0 failed / skipped；18:55:41–18:55:51 |
| Shell 语法和空白检查 | 五个修改的 Shell 脚本 `bash -n` 通过；`git diff --check` 通过 |

工具链 fixture 包含干净目录中无 node_modules 的 checker 运行，以及真实 `npm ci --ignore-scripts --offline` 负向测试。错误 Node/npm 在依赖删除之前返回失败，既有 node_modules 哨兵保持不变。独立实测还确认全局 Node 25.2.1 被 checker 拒绝，以及 Node 24.22.0 搭配旧 npm 11.6.2 的构建被 EBADDEVENGINES 阻断。

扩大范围的首轮契约检查执行了部署、运维脚本边界、API facade、bootstrap 和 code-only 发布测试，结果为 146 passed / 6 skipped / 1 failed。唯一失败是旧断言要求构建字符串直接以 API 检查开头；现调整为验证“工具链检查 → API 检查 → 原构建门禁 → Vite”，未删除 API 门禁。修正后包含该测试的两个相关文件已完整复验为上述 40 passed，其余未修改的契约测试未重复运行。六项 skip 均为既有 Linux 专用 bootstrap 持久化/回退演练测试，未增加 skip 或 xfail。

曾误用不存在的 `test_code_only_release_contracts.py` 文件名导致一次收集错误，未运行测试；已纠正为 `test_code_only_deployment.py` 后完成上述扩大范围检查。本 Task 未重新执行全量后端，Task 0 的 1894 passed / 6 skipped 仅为历史基线。

非失败提示保留：安装中既有 `glob@10.5.0` 弃用提示、单测中 jsdom `Window.open()` 未实现提示、E2E 中 NO_COLOR/FORCE_COLOR 环境提示。未通过隐藏提示或升级依赖消除它们。

## 锁文件与行为保护

锁文件只更新根 `engines` 元数据。对旧/新 JSON 去除该字段后进行深比较，结果一致；211 个锁定依赖条目及其版本、完整性和依赖关系均未变。逐项核对其 Node engines，均兼容 Node 24.22.0。

以下 Task 0 基线及行为样本保持原字节，不重录 golden、不扩展例外：

| 文件 | SHA-256 |
|---|---|
| `tests/schedule_capacity_behavior_v1.json` | `e7cbab5f52611d6dbca933ae80294cf61567392ffd585729f5d30596a6f21bd2` |
| `frontend/scripts/frontend-layer-baseline.json` | `b50285a2f086067687be024599a6963e6d2abc3459d29c4fa44d77c9c51423b9` |
| `docs/technical-debt/20261015-task0-baseline.md` | `d2dba687b494d001fd17ac7debbb2956fd237d5803c18aab7a1b3069bc5472c2` |
| Task 0 `verification.json` | `87433155f54c77b2bb1cf5f147fa8394948d20f7f2ce7572b208a3c884c8197a` |
| Task 0 `frontend-dependency-inventory.json` | `3091ac2fff0f04e522eed885284f530c6c68b72b65214b1185f38e4a3d9fca5c` |

## 交付与后续

原始日志和隔离发行包保存在 `C:/Users/dubin/Documents/生产管理系统升级版/.architecture-audits/20261015-task1-toolchain/`，不进入提交。关键日志为 `npm-ci.log`、`verify-frontend.log`、`toolchain-final.log`、`contracts.log`、`contracts-final.log`、`wrong-node.log` 和 `wrong-npm.log`。

Task 1 正式本地 diff 审核已通过，未发现阻断问题。审核覆盖本阶段全部 17 个文件，并复核新工作流、精确版本阻断、安装前失败和构建门禁顺序；审核阶段工具链测试 21 passed、部署/API 契约测试 40 passed，Shell 语法及空白检查通过。该轮本地审核时远端 CI 尚未运行，之后发现的 Windows 依赖缺失及修复已记录于上文。本 Task 未重跑全量后端，未将历史后端全量数计入本次。提交、推送、PR 和合并分别登记实际结果后再关闭 D07。后续 Task 2A–2F 使用同一精确工具链验证前端依赖迁移。

提交范围仅包含本 Task 的 17 个文件，排除 `.brooks-lint-history.json`、Task 0 报告、原始审计报告、`.tmp-*`、临时部署脚本、日志、构建产物和隔离运行时。代码及本次 CI 修复的提交、检查和合并结果以 PR #100 为准。本次未执行生产部署；原代码-only 发布边界、写入围栏、备份和回退流程不变。未来前端发布需要单独选择相同构建工具链并取得部署授权。
