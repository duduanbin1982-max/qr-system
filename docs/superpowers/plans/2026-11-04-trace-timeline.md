# Trace Timeline Implementation Plan

**Goal:** 生命周期按实际时间稳定排序，保留原始 API 数据。

**Architecture:** `buildTraceTimeline(result)` 生成展示 DTO，新数组排序；
`TraceProductionHistory.vue` 使用 computed 消费。无 IO、无依赖导入的
纯函数登记为精确 presentation module。

**Tech Stack:** Vue 3、Vitest、Playwright；Node 24.22.0/npm 11.19.1。

## Global Constraints

- 仅批次 E 独立工作树；不提交、推送、部署。
- API 集合不变；序列号订单级集合范围不变。
- 缺失及无效时间末尾显示“时间缺失”；无时区时间为 +08:00。

## Task 1: DTO 与稳定排序

- [x] 新增 `frontend/tests/unit/traceTimeline.spec.js`，覆盖交错时间、
  时区等价、同时间类型/ID、重复 ID、缺失时间、冻结输入与序列号范围。
- [x] 执行 `npm run test:unit -- frontend/tests/unit/traceTimeline.spec.js`，
  确认缺少模块失败，再实现 `frontend/src/lib/traceTimeline.js`。
- [x] `buildTraceTimeline(result)` 返回含 timestamp（毫秒或 null）、
  kind、stable_id（字符串）、label、payload、key、time_label、ordinal 的数组。
  key 为 JSON 编码的类型/ID/出现序号。排序使用时间、类型、ID、出现序号。
- [x] 同命令验证通过。

## Task 2: 组件与分层约束

- [x] 新增 `frontend/tests/unit/TraceProductionHistory.spec.js`，验证交错显示、
  重复 key、原集合顺序和 setProps 切换响应性。
- [x] 生命周期改为单个 v-for，保留各类型的原展示信息。
- [x] 在 `frontend/scripts/check-frontend-layers.mjs` 登记该精确纯模块；
  `frontend/tests/architecture/frontend-layers.test.mjs` 补充合法消费和
  imports/browser state/HTTP transport 禁止用例。
- [x] 执行专项单测、全部前端单测、`npm run check:architecture` 与构建。

## Task 3: 浏览器回归

- [x] 在新增 `frontend/tests/e2e/trace-timeline.spec.js` 使用本地真实应用及受控追溯响应，
  验证三种跨类型顺序、同时间、缺失时间、重复 ID 和控制台 key 告警。
- [x] 本地隔离测试数据库、独立端口，执行
  `npm run test:e2e -- frontend/tests/e2e/trace.spec.js frontend/tests/e2e/trace-timeline.spec.js`。
- [x] 检查 diff、实际测试结果及工作树状态；交付后等待正式审核。

## 验证记录

- 初次运行纯函数单测因新模块不存在失败，随后实现通过。
- Node 24.22.0/npm 11.19.1，通过锁文件安装依赖。
- 最终前端单测：74 个文件，607 passed。
- 架构门禁通过：pytest 87 passed，工具链 21 passed，分层 106 passed。
- 浏览器 6 passed：4 个受控追溯响应场景和 2 个真实后端桌面/移动冒烟。
- E2E 测试使用 Vite 生产构建成功输出的静态文件；未执行后端全量 pytest。
- 数字 ID 精确排序，文本和缺失 ID 使用独立顺序，避免混合比较不传递。
- Python 微秒时间保留到排序数值，避免毫秒内事件误用 ID 决定次序。
