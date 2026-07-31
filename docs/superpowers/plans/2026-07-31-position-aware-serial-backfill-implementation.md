# 按活动岗位匹配跨工序补报实施计划

## 目标

实现已批准的岗位感知补报规则：补报候选严格取“个人授权工序 ∩ 当前活动岗位工序 ∩ 当前订单可补报工序”；唯一候选自动选择，多候选人工选择，无候选不跨岗位回退。补报不再要求实际完成时间和原因，系统保存提交岗位快照供审批与追溯。

## 实施原则

- 后端候选计算与提交校验使用同一岗位规则，前端不作为安全边界。
- 正常报工现有岗位回退规则保持不变，严格岗位边界只作用于跨工序补报。
- 数据库迁移只增加可空字段，不删除历史字段和数据。
- 每项任务先补失败测试，再完成最小实现并提交独立变更。
- 服务器工作区已有其他未提交修改；实施时不得清理、覆盖或提交无关文件。

## 任务1：增加岗位快照迁移

**文件**

- 修改：`modules/migration_serial_backfill.py`
- 修改：`tests/test_migrations.py`

**步骤**

1. 在迁移测试中新增失败用例，断言下一版本迁移为 `work_records` 增加：
   - `submit_position_id INTEGER`
   - `submit_position_name TEXT NOT NULL DEFAULT ''`
2. 测试迁移可重复执行，并验证已有补报记录数量及历史字段不变。
3. 在 `migration_serial_backfill.py` 添加 `m048_position_aware_serial_backfill`，使用 `add_column_if_missing` 保证幂等。
4. 将迁移注册为版本48；运行迁移注册重复版本检查。

**验证**

```bash
pytest -q tests/test_migrations.py
python3 -c "from modules.migrations import LATEST_VERSION; assert LATEST_VERSION == 48"
```

**提交**

```text
feat: add serial backfill position snapshots
```

## 任务2：扩展领域命令与持久化链路

**文件**

- 修改：`modules/domain/work_report.py`
- 修改：`modules/services/scan_helper_service.py`
- 修改：`modules/services/work_report_writer.py`
- 修改：`modules/repositories/scan_repository.py`
- 修改：`tests/test_work_report_command.py`
- 修改：`tests/test_serial_backfill.py`

**步骤**

1. 先增加领域测试：`serial_backfill` 命令在没有 `actual_completed_at` 和 `backfill_reason` 时合法。
2. 增加岗位快照测试：补报命令接受 `submit_position_id`、`submit_position_name`；标准报工允许两者为空。
3. 从 `WorkReportCommand.__post_init__` 删除补报时间和原因必填检查，保留“仅支持序列号正常报工”的约束。
4. 为 `WorkReportCommand`、`from_submission`、`from_approved_record` 增加岗位快照字段。
5. 扩展 `ScanHelperService.insert_work_record` 和 `ScanRepository.insert_report_work_record` 参数及SQL，将岗位快照写入 `work_records`。
6. 扩展补报和审批相关查询，返回岗位快照；历史记录缺少快照时返回空值。
7. 确认审批通过后重建 `WorkReportCommand` 时仍能读取新字段，但岗位快照不参与工序推进逻辑。

**验证**

```bash
pytest -q tests/test_work_report_command.py tests/test_serial_backfill.py
```

**提交**

```text
feat: persist serial backfill position context
```

## 任务3：实现严格的岗位候选计算

**文件**

- 修改：`modules/services/process_order_service.py`
- 修改：`tests/test_process_order_service.py`

**先写测试**

1. 序列号模式，当前岗位只有一个可补报工序：仅该工序 `serial_backfill_reportable=true`，来源为 `position_auto`，候选数为1。
2. 当前岗位有两个可补报工序：两项可选，来源为 `position_manual`，候选数为2。
3. 个人有其他工序授权但当前岗位无匹配：所有补报标记为 `false`，来源为 `none`，不回退个人授权。
4. 未提供活动岗位范围：所有补报标记为 `false`，消息要求先选择岗位。
5. 已报工或待审批工序不计入候选。
6. 现有正常报工的 `authorization_auto/authorization_manual` 回退测试保持通过。

**实现**

1. 将补报的基础资格和岗位资格分开计算，便于生成准确错误提示。
2. 只有 `preferred_process_ids` 明确存在且包含目标工序时，补报岗位资格才成立。
3. 按工艺顺序生成补报候选，不改变 `current_process` 表示的工件真实当前工序。
4. 在订单上下文增加：
   - `serial_backfill_selection_source`
   - `serial_backfill_candidate_count`
   - `serial_backfill_message`
5. 严格岗位规则仅应用于 `serial_backfill_reportable`，不得改变正常报工的现有选择池。

**验证**

```bash
pytest -q tests/test_process_order_service.py
```

**提交**

```text
feat: scope serial backfill candidates to active position
```

## 任务4：接通移动扫码岗位上下文

**文件**

- 修改：`modules/services/mobile_scan_service.py`
- 修改：`tests/test_active_position.py`
- 修改：`tests/test_serial_backfill.py`
- 修改：`tests/test_scan_flow.py`

**步骤**

1. 扩展序列号补报夹具，为测试人员创建主岗位、第二岗位和对应 `position_processes` 映射。
2. 验证 `MobileScanService` 将当前活动岗位的 `process_ids` 传给候选计算。
3. 增加API测试：
   - 主岗位扫描返回唯一候选和 `position_auto`；
   - 当前岗位多工序返回 `position_manual`；
   - 切换活动岗位后重新扫描，候选同步变化；
   - 当前岗位无候选时不暴露其他岗位工序。
4. 保留响应中的 `position_context` 和 `order.active_position`，供移动端显示及切换。

**验证**

```bash
pytest -q tests/test_active_position.py tests/test_serial_backfill.py tests/test_scan_flow.py
```

**提交**

```text
feat: expose position-aware backfill scan state
```

## 任务5：提交时强制岗位校验并生成快照

**文件**

- 修改：`modules/services/serial_backfill_service.py`
- 修改：`modules/services/scan_report_service.py`
- 必要时修改：`modules/routes/scan_work.py`
- 修改：`tests/test_serial_backfill.py`
- 修改：`tests/test_scan_report_policy.py`

**先写测试**

1. 不传时间和原因的合法补报成功进入待审批。
2. 当前活动岗位包含目标工序时提交成功，并保存岗位ID和名称。
3. 个人有工序授权、但当前岗位不包含目标工序时提交失败。
4. 扫码后切换岗位，再提交旧候选时失败。
5. 未能解析活动岗位时失败并提示“请先选择当前岗位”。
6. 直接伪造岗位ID或岗位名称不能覆盖服务端快照。
7. 已报工或已有待审批记录继续被重复校验拦截。

**实现**

1. `SerialBackfillService.validate_submission` 内调用 `ActivePositionService.get_context(user)` 获取服务端活动岗位。
2. 校验目标工序同时属于个人授权和活动岗位 `process_ids`。
3. 删除 `reason`、`actual_completed_at` 参数及其必填/格式校验。
4. 返回可信的 `submit_position_id`、`submit_position_name`，由 `ScanReportService.prepare_submission` 写入命令数据。
5. 不接受请求体中的岗位快照作为可信值；即使客户端发送也必须覆盖为服务端值。
6. 保持所有补报 `need_approval=true`，不改变审批前不推进工件状态的行为。

**验证**

```bash
pytest -q tests/test_serial_backfill.py tests/test_scan_report_policy.py tests/test_scan_flow.py
```

**提交**

```text
feat: enforce active position on serial backfill submission
```

## 任务6：改造移动端自动选择与岗位切换

**文件**

- 修改：`public/js/mobile/mobile-utils.js`
- 修改：`public/js/mobile/mobile-auth.js`
- 修改：`public/js/mobile/mobile-order.js`
- 修改：`public/js/mobile/mobile-init.js`
- 修改：`public/mobile.html`
- 修改：`public/css/mobile.css`
- 修改：`public/sw.js`
- 修改：`tests/test_mobile_frontend_contracts.py`
- 修改或新增：`frontend/tests/e2e/mobile-scan.spec.js`

**步骤**

1. 保存最近一次有效扫码内容，供订单页切换岗位后重新查询。
2. 在订单确认页显示活动岗位；多岗位人员显示岗位选择控件。
3. 岗位切换成功后禁用旧提交状态，使用原扫码内容重新调用移动扫码接口；请求完成前显示加载状态。
4. 根据 `serial_backfill_selection_source` 处理：
   - `position_auto`：自动选中唯一候选，切换手动模式并滚动到候选；
   - `position_manual`：不默认选择，仅允许点击当前岗位候选；
   - `none`：禁用提交并显示服务端消息。
5. 删除实际完成时间和补报原因控件、校验和请求字段。
6. 补报确认框显示订单、序列号、当前岗位和目标工序。
7. 保留正常报工自动模式；跨工序补报永远不自动提交。
8. 更新移动端JS/CSS查询版本及Service Worker缓存版本。

**前端测试**

1. 用Playwright拦截扫码接口，覆盖唯一候选、多候选、无候选和岗位切换四种响应。
2. 断言唯一候选自动选中但 `mobileReport` 未自动调用。
3. 断言多候选未选择前按钮禁用。
4. 断言请求体不包含 `actual_completed_at`、`backfill_reason` 和客户端岗位快照。
5. 在390×844和360×640视口截图，确认工序标题、岗位控件、候选和提交按钮不重叠。

**验证**

```bash
pytest -q tests/test_mobile_frontend_contracts.py
npx playwright test frontend/tests/e2e/mobile-scan.spec.js --grep "position-aware serial backfill"
node --check public/js/mobile/mobile-order.js
node --check public/js/mobile/mobile-auth.js
```

**提交**

```text
feat: guide mobile backfill by active position
```

## 任务7：审批接口和页面显示岗位快照

**文件**

- 修改：`modules/repositories/approval_repository.py`
- 修改：`modules/services/approval_service.py`（仅在响应整形需要时）
- 修改：`frontend/src/views/ApprovalPage.vue`
- 修改：`tests/test_approval_service.py`
- 修改：`tests/test_approval_workflow.py`
- 新增或修改：`frontend/tests/unit/ApprovalPageBackfill.spec.js`

**步骤**

1. 审批仓储的待审批、历史和单记录查询返回 `submit_position_id/name`。
2. 新补报显示序列号、提交岗位和申请时间。
3. 新记录不渲染空的实际完成时间和原因。
4. 历史记录存在 `actual_completed_at` 或 `backfill_reason` 时继续只读显示。
5. 审批操作、批量审批和多级审批逻辑保持不变。

**验证**

```bash
pytest -q tests/test_approval_service.py tests/test_approval_workflow.py
npm run test:unit -- --run frontend/tests/unit/ApprovalPageBackfill.spec.js
```

**提交**

```text
feat: show backfill position snapshots in approvals
```

## 任务8：全量回归、生产迁移与真实验收

**变更前保护**

1. 记录相关文件的 `git status` 和差异，不处理无关脏文件。
2. 备份生产数据库到项目目录之外，并记录SHA-256。
3. 记录当前服务版本和移动端静态资源版本，准备应用与静态资源回滚包。

**全量验证**

```bash
pytest -q
npm run test:unit
npm run build
```

要求：全部通过；已知环境问题必须单独证明与本次变更无关，不得用忽略失败替代修复。

**发布顺序**

1. 停止写入窗口或进入短维护期。
2. 执行数据库迁移并验证 `PRAGMA user_version = 48`。
3. 验证 `work_records` 两个岗位快照字段存在，历史记录数量不变。
4. 部署后端代码并重启应用服务。
5. 部署移动端、审批页构建产物和Service Worker版本。
6. 检查HTML、JS、CSS和API均返回200，无控制台错误。

**真实验收**

使用 `0703 + 26062502-022` 验证：

1. 当前活动岗位为喷漆工时，唯一“喷漆”候选自动选中。
2. 页面不要求实际完成时间和原因。
3. 未点击提交前不会产生补报记录。
4. 提交后记录为待审批，工件当前工序仍为打磨。
5. 审批页显示操作员、喷漆工岗位快照、喷漆工序和申请时间。
6. 切换到不包含喷漆的岗位后，不能提交喷漆补报。

**回滚**

- 回滚应用和静态资源到发布前版本。
- 保留新增的两个可空数据库字段，不执行破坏性降级。
- 如迁移或数据校验异常，停止服务并使用外置数据库备份恢复。

## 完成标准

- 设计文档中的15项验收要求全部有自动化或真实环境证据。
- 后端不能通过直接请求绕过活动岗位边界。
- 新补报不再发送或要求实际完成时间、补报原因。
- 审批与历史查询可区分提交岗位，并兼容旧补报记录。
- 正常报工、审批、序列号推进和质量评价流程无回归。
