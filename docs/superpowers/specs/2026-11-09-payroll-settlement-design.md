# 工资结算闭环与审计下钻设计

日期：2026-11-09
状态：已确认，待实施计划
开发基线：GitHub master 287b4f791b265e6a4ec738e560b7da5da4272605

## 1. 背景

现有工资核算已经具备版本化工资批次、员工与来源快照、异常双人处理、补差冲销、幂等生成、批次修订和不可变事件。当前正式导出仍是即时生成 CSV，没有持久化导出版本、财务支付回执、差异对账和最终结账锁定。

本设计将工资模块从“工资计算与确认”扩展到“财务交付、回执、对账和结账”，随后补齐审计异常规则与来源明细下钻。

## 2. 目标

1. 将每次财务支付清单作为不可变导出批次持久化。
2. 接收并持久化财务支付回执，支持失败后的后续回执重试。
3. 对工资应付与成功支付进行可重复、可追溯的差异对账。
4. 仅在最新对账完全通过时允许结账锁定。
5. 增加未审批、重复、跨期间和高偏差工资审计规则。
6. 允许从员工工资行下钻到报工、订单、工序、工价和调整来源。
7. 保持现有工资计算状态机与既有 API 兼容。

## 3. 非目标

1. 不保存银行卡号、开户行、收款账户或其他银行敏感信息。
2. 不直接调用银行 API 或自动发起付款。
3. 不在本批引入个税、社保或复杂薪酬规则引擎。
4. 不把工资结算能力抽象为跨模块通用财务平台。
5. 不修改已经锁定或确认的工资快照金额。
6. 不允许通过备注直接抹平金额差异。

## 4. 总体架构

现有 payroll_batches 继续表示工资计算与审批生命周期。新增独立工资结算子台账，使用 payroll_settlements 作为结算聚合根。

计算状态和结算状态保持分离：

- 计算状态：draft、exceptions_pending、review_pending、locked、confirmed、voided。
- 结算状态：未导出、已导出、回执处理中、差异待处理、已对账、已结账。

只有 confirmed 且未被后续版本替代的工资批次可以创建正式结算和导出。

## 5. 领域模型

### 5.1 payroll_settlements

每个工资批次最多一个结算聚合。主要字段：

- id
- batch_id，唯一外键
- status
- expected_total_cents
- successful_paid_cents
- difference_cents
- blocking_difference_count
- current_export_batch_id
- latest_reconciliation_run_id
- row_version
- created_by、created_by_name、created_at
- updated_at

状态允许值：

- exported
- receipting
- difference_pending
- reconciled
- closed

未创建结算记录时由 API 表示为 not_exported，不向数据库保存虚拟状态。

### 5.2 payroll_export_batches

保存每次导出的精确版本：

- settlement_id
- export_version
- status：active、superseded、cancelled
- row_count
- total_cents
- content_sha256
- csv_content_blob
- idempotency_key
- created_by、created_by_name、created_at
- superseded_at、superseded_by_export_id

约束：

- settlement_id 与 export_version 唯一。
- idempotency_key 唯一。
- 导出创建后内容、摘要、行数和金额不可更新。
- 已有有效回执后禁止替代当前导出。

### 5.3 payroll_export_items

每名员工一条支付清单快照：

- export_batch_id
- employee_line_id
- employee_id
- employee_no_snapshot
- employee_name_snapshot
- payable_cents
- payment_reference
- sequence_no
- created_at

payment_reference 在全库唯一，并且不依赖银行卡资料。建议格式由服务生成，不允许前端指定。

### 5.4 payroll_receipt_batches

每次回执上传均保留独立批次：

- export_batch_id
- status：accepted、validation_failed、superseded
- source_filename
- content_sha256
- accepted_row_count
- failed_row_count
- idempotency_key
- uploaded_by、uploaded_by_name、uploaded_at

不保存未知列或银行敏感字段。出现明确禁止的表头时，在持久化文件内容前拒绝整批上传。

### 5.5 payroll_receipt_items

允许字段：

- payment_reference
- employee_no_snapshot
- employee_name_snapshot
- paid_cents
- payment_status：success、failed、processing、returned
- paid_at
- external_transaction_no
- failure_reason
- validation_status
- validation_error
- row_number

成功金额只统计 validation_status 有效且 payment_status 为 success 的记录。历史回执不可更新或删除。

### 5.6 payroll_reconciliation_runs

每次运行读取固定的导出版本和截至当时的回执集合：

- settlement_id
- export_batch_id
- run_version
- status：difference_pending、reconciled
- expected_total_cents
- successful_paid_cents
- difference_cents
- blocking_count
- receipt_digest
- idempotency_key
- executed_by、executed_by_name、executed_at

### 5.7 payroll_reconciliation_items

逐支付引用保存：

- reconciliation_run_id
- export_item_id
- payment_reference
- expected_cents
- successful_paid_cents
- difference_cents
- difference_type
- blocking

对账运行和逐项结果创建后不可修改。差异处理通过独立追加记录表达。

差异类型：

- missing_receipt
- underpaid
- overpaid
- duplicate_success
- unknown_reference
- employee_mismatch
- failed_payment
- invalid_amount

### 5.8 payroll_reconciliation_resolutions

保存对非金额类差异的追加式处理决定：

- reconciliation_item_id
- receipt_item_id
- resolution_code：exclude_duplicate、accept_name_mismatch、exclude_unknown_reference
- resolution_reason
- idempotency_key
- resolved_by、resolved_by_name、resolved_at

解决记录不可更新或删除。增加解决记录后必须重新运行对账；历史对账运行不随解决记录变化。少付、多付、缺少回执和失败付款不允许通过解决记录消除。

### 5.9 payroll_close_records

一个结算只能存在一条结账记录：

- settlement_id，唯一
- export_batch_id
- reconciliation_run_id
- expected_total_cents
- successful_paid_cents
- close_digest
- close_reason
- idempotency_key
- closed_by、closed_by_name、closed_at

结账记录、对应导出、回执和对账结果全部不可修改或删除。

## 6. 状态机与约束

主流程：

    not_exported
      -> exported
      -> receipting
      -> difference_pending
      -> reconciled
      -> closed

允许行为：

1. confirmed 工资批次创建第一个导出后进入 exported。
2. 上传至少一批有效回执后进入 receipting。
3. 对账存在阻断差异时进入 difference_pending。
4. 最新对账应付等于有效成功支付且无阻断差异时进入 reconciled。
5. 结账事务重新校验最新导出、回执摘要和对账结果后进入 closed。

禁止行为：

1. 非 confirmed、已 voided 或已被修订替代的工资批次不得创建结算。
2. 已存在有效回执后不得生成替代导出版本。
3. 回执不得引用非当前导出版本的 payment_reference。
4. 差异待处理时不得结账。
5. closed 后不得新增导出、回执、对账或修改结算记录。
6. 金额差异不得通过人工备注直接清零。

## 7. CSV 合同

### 7.1 财务支付清单

固定字段顺序：

1. payment_reference
2. payroll_month
3. payroll_version
4. employee_no
5. employee_name
6. payable_amount

文件使用 UTF-8 BOM。所有文本字段执行 CSV 公式注入防护。金额由整数分转换为固定两位小数。

### 7.2 财务支付回执

固定接收字段：

1. payment_reference
2. employee_no
3. employee_name
4. paid_amount
5. payment_status
6. paid_at
7. external_transaction_no
8. failure_reason

禁止表头包括银行卡号、卡号、开户行、银行账号、收款账号及其英文等价字段。禁止表头出现时整批拒绝，不保存文件内容。其他未声明字段不持久化。

## 8. API

查询：

- GET /api/payroll/batches/{batch_id}/settlement
- GET /api/payroll/export-batches/{export_id}
- GET /api/payroll/export-batches/{export_id}/download
- GET /api/payroll/export-batches/{export_id}/receipt-batches
- GET /api/payroll/settlements/{settlement_id}/reconciliations/{run_id}

命令：

- POST /api/payroll/batches/{batch_id}/export-batches
- POST /api/payroll/export-batches/{export_id}/receipt-batches
- POST /api/payroll/settlements/{settlement_id}/reconciliations
- POST /api/payroll/reconciliation-items/{item_id}/resolve
- POST /api/payroll/settlements/{settlement_id}/close

所有命令要求 Idempotency-Key。状态更新要求 row_version。幂等键复用于不同业务参数时返回 409。并发版本冲突返回 409。验证错误返回 400，权限不足返回 403，不存在返回 404。

### 8.1 旧导出接口兼容

现有 GET /api/payroll/batches/{batch_id}/export 保留为兼容预览接口：

- locked 和 confirmed 批次仍可下载原有格式的工资清单预览。
- 该接口不创建正式 export batch，输出不得参与回执、对账或结账。
- 响应增加 X-Payroll-Export-Mode: preview，审计事件明确记录为 preview_export。
- 新前端不再把该接口展示为正式财务导出；正式支付清单只能通过结算 POST 接口创建。

这样既保留原有查看和下载能力，又防止旧 GET 请求绕过持久化结算流程。

## 9. 权限

- wages:view_all：查看结算摘要和对账结果。
- wages:export：生成、下载支付清单。
- wages:receipt：上传和查看支付回执。
- wages:reconcile：执行对账和处理非金额差异。
- wages:close：执行最终结账。

当前为单人维护模式，结账不要求第二个不同身份，但必须二次确认、填写结账说明并记录完整操作事件。

## 10. 前端设计

工资模块新增一个“导出对账”TAB，不增加四个平级 TAB。页面内部使用四步工作区：

1. 支付清单
2. 回执记录
3. 差异对账
4. 结账

顶部显示工资月份、批次版本、结算状态、应付金额、成功支付金额、差异金额和阻断数量。

关键交互：

- 仅展示 confirmed 且未被替代的工资批次。
- 导出区展示所有版本及当前有效版本。
- 回执上传后展示逐行成功与失败，不因单行失败隐藏其他结果。
- 差异区支持按差异类型、阻断状态和员工筛选。
- 结账按钮只有在最新对账为 reconciled 时启用。
- 结账确认框展示最终金额、导出版本、回执数量和对账运行版本。

## 11. 差异处理

1. 少付、多付、缺少回执和失败付款必须通过后续回执修复。
2. 重复成功回执可以排除无效记录，但必须填写原因。
3. payment_reference、工号和金额一致，仅姓名不一致时可确认元数据差异。
4. 未知 payment_reference 不计入支付金额，必须排除或重新上传正确回执。
5. 每次重新对账生成新运行记录，不覆盖历史。

## 12. 工资审计异常

新增 payroll_audit_findings，不扩展现有面向工价解析的 payroll_exceptions。

字段包括：batch_id、finding_type、severity、status、subject_type、subject_id、rule_version、snapshot_json、resolution_code、resolution_reason、resolved_by、resolved_at。

规则：

- pending_approval_work：截止时间内仍未审批，阻断。
- duplicate_serial_work：同订单、工序和非空序列号重复，阻断。
- duplicate_work_candidate：同员工、订单、工序、类型、数量和实际时间完全相同，人工复核。
- cross_period_work：按生产日 07:00 边界计算，actual_completed_at 与 created_at 属于不同工资期间时阻断并确定归属；actual_completed_at 为空时不产生该规则。
- high_payroll_deviation：取该员工最近三个未作废、未被替代的正式工资版本作为可比期间；本期偏离历史中位数至少 50%，且绝对差额至少 500 元时人工复核。

重复候选的实际时间使用 actual_completed_at；为空时回退 created_at。序列号重复忽略 rejected 记录。无序列号候选必须在员工、订单、工序、类型、数量和实际时间精确到秒全部相同后才触发，避免使用宽泛时间窗口造成误报。

规则结果必须展示计算依据和规则版本，不使用黑盒评分。

## 13. 来源明细下钻

员工工资行增加“查看来源”。数据按需加载单个员工，不预加载整个批次。

抽屉分组：

- 正常报工
- 返工
- 奖金
- 补贴
- 扣款
- 冲销

每条明细展示来源记录 ID、实际时间、入库时间、订单、产品、路线、工序、数量、工价版本、单价、返工倍率、金额、解析方式和核定原因。底部显示工资批次事件时间线。

## 14. 数据库迁移

### 迁移 97

增加结算、导出、回执、对账、结账表以及相关索引、不可变触发器和新权限。迁移不得自动为历史 confirmed 批次创建导出；首次操作时按需创建 settlement。

### 迁移 98

增加 payroll_audit_findings、规则索引和不可变审计字段。历史批次不自动回填异常；新建或重算批次时运行规则。

迁移注册必须将线性版本链从 96 扩展到 98，并保持重复执行安全。

## 15. 事务和幂等

1. 导出创建在单一事务内固化 settlement、export batch、export items、CSV 和摘要。
2. 回执上传先进行禁止字段检查，再计算文件摘要并执行幂等检查。
3. 对账运行在事务内固定导出版本和回执摘要。
4. 结账事务重新读取最新状态、row_version、导出和对账摘要。
5. 所有命令将不可变事件写入 payroll_events，并包含实体 ID、版本和幂等键。

## 16. 测试策略

Python：

- 迁移 97/98 的注册、重复执行、约束和触发器。
- 导出版本、文件摘要、公式注入防护和幂等。
- 禁止银行敏感字段。
- 回执逐行验证、重复文件、失败重试和成功金额统计。
- 少付、多付、重复、未知引用和姓名不一致对账。
- 结账阻断、并发冲突、幂等结账和结账后不可变。
- 新异常规则与边界时间。
- 路由状态码、权限和审计事件。

前端：

- TAB 可见性与权限。
- 导出版本和下载。
- 回执逐行结果。
- 差异筛选和处理限制。
- 结账阻断和确认摘要。
- 来源抽屉的分组、金额和事件时间线。

E2E：

- 完整导出、回执、对账、结账路径。
- 部分失败后上传新回执并重新对账。
- 金额差异阻断结账。
- 重复命令不重复生成数据。

固定验证环境为 Node 24.22.0、npm 11.19.1 和项目 Python 测试环境，同时运行架构门禁、构建和 git diff --check。

## 17. 分批交付

### B1：结算闭环

实现迁移 97、持久化导出、回执、对账、结账锁定、导出对账 TAB 和专项测试。

### B2：审计异常规则

实现迁移 98、确定性异常规则、异常展示与处理测试。

### B3：来源明细下钻

实现员工来源抽屉、按需 API、事件时间线和前端/E2E 测试。

每个批次均执行：本地测试与 diff 审核、独立 PR、四项 CI、同 SHA 独立审核、明确授权合并、基于 Merge SHA 的发布预检、明确授权部署。

## 18. 验收标准

1. 任一工资导出均可按版本、内容摘要和操作人复现。
2. 回执失败不会阻断其他行，且后续重试不会覆盖历史。
3. 对账能准确解释每一分钱的应付、实付和差异。
4. 存在金额差异或阻断项时无法结账。
5. 结账后相关结算数据不可变。
6. 系统不保存任何银行卡、开户行或收款账号字段。
7. 新异常规则可解释、可定位来源并保留规则版本。
8. 员工工资可以下钻到报工、订单、工序、工价版本和调整来源。
9. 现有工资计算、审批、修订、我的工资和旧导出兼容性不回退。
