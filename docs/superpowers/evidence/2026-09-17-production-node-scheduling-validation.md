# 生产节点排程 Task 13 发布验证证据

验证日期：2026-09-19（Asia/Shanghai）
工作分支：`codex/production-node-scheduling`
验证时的 `HEAD`：`a2673a1080f263df6b79f9b0ec820c4a765a82a6`

本证据记录对应 Task 13 的本地发布门禁。工作树仍包含 Task 1–13 的未提交
改动，因此当前 `HEAD` 只作为验证基线记录，不能被视为可直接部署的发布提交。

## 真实订单回放

使用脱敏、不可变的生产形状夹具，未复制客户名称、员工信息、账号、密码、
工资、附件或个人联系方式。夹具摘要：

- 夹具版本：`sanitized-production-node-replay/v1`；
- 订单数：3；
- 排程工序数：12；
- 排程数量：41；
- 节点数量：21；
- 夹具 SHA-256：
  `d9bc760620373da70937f0a4b2ea6b3baa32f6b0da8b6b421e3e2df207408bf2`；
- 标准工时、路线版本、工序版本、节点能力、工作日历、占用和停机均纳入
  输入摘要；
- 序列件保持同一生产节点，不允许跨节点拆分。

回放验收结果：

| 指标 | 结果 |
| --- | ---: |
| `core_node_count` | 21 |
| `scheduled_quantity` | 41 |
| `allocated_quantity` | 41 |
| `quantity_conservation_rate` | 1.0 |
| `serial_split_violations` | 0 |
| `exclusive_overlap_count` | 0 |
| `completed_fact_changes` | 0 |
| `unmapped_fact_count` | 0 |
| `latest_compat_mismatch_count` | 0 |
| `database_integrity` | `ok` |
| `foreign_key_error_count` | 0 |

## 测试和构建门禁

已执行并通过：

```text
python -m pytest -q tests/test_production_node_legacy_contracts.py \
  tests/test_production_node_migrations.py \
  tests/test_production_node_compatibility.py \
  tests/test_production_node_policy.py \
  tests/test_production_node_api.py \
  tests/test_production_node_scheduling.py \
  tests/test_production_node_batch_scheduling.py \
  tests/test_production_node_schedule_workflow.py \
  tests/test_production_node_dynamic_replan.py \
  tests/test_production_node_operations.py \
  tests/test_production_node_real_order_replay.py \
  tests/test_schedule_capacity.py \
  tests/test_schedule_dynamic_replan.py \
  tests/test_schedule_order_priority_v084.py \
  tests/test_schedule_standard_binding_v085.py
244 passed in 57.88s

python -m pytest -q
1546 passed in 347.64s

cd frontend && npm run test:unit
39 test files, 167 tests passed

cd frontend && npm run build
API facade check passed: 34 namespaces, 443 unique domain methods
Frontend import cycle check passed: 197 files, 493 internal edges
Vite production build passed

python -m compileall -q modules scripts
git diff --check
PASS
```

Task 13 还修复了一个实际发现的边界问题：能力约束匹配路径收到 SQLite
`Row` 时会调用 `.get()`。排程服务现在在进入节点能力策略前将订单和工序事实
规范化为 mapping，避免真实数据库路径与测试夹具路径行为不一致。

## 数据库、迁移和开关基线

- 当前迁移目录最新版本：`89`（V086–V089）；
- 默认生产节点开关全部关闭：

```text
PRODUCTION_NODE_QUERY_ENABLED=false
PRODUCTION_NODE_COMPAT_AUDIT_ENABLED=false
PRODUCTION_NODE_WRITE_ENABLED=false
PRODUCTION_NODE_ENGINE_ENABLED=false
LEGACY_PROCESS_LINE_WRITE_BLOCKED=false
```

- 没有执行生产数据库迁移、附件迁移、前端发布、停服、重启或任何功能开关
  切换；
- 没有连接或修改 `192.168.1.8`；
- 没有创建、推送或合并提交。

## 部署只读检查

执行：

```text
bash deploy.sh --check-only
```

结果为安全拒绝：`Deployment refused: Git worktree is not clean`。这是预期的
保护行为，因为本阶段按用户约束保留未提交改动；它证明部署脚本在脏工作树下
不会绕过发布门禁。

因此，当前状态是“本地验证通过、尚未形成可部署发布提交”。后续若要进入
提交、推送、PR、合并或生产部署，必须分别取得对应授权；生产节点五个开关阶段
仍需独立授权，不能由 Task 13 验证结果自动开启。
