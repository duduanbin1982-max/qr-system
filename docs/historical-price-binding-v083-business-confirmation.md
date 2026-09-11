# V083 历史工价绑定：18 项业务确认表

文件：`historical-price-binding-v083-business-confirmation.csv`

## 填写规则

每一行必须填写以下两种结论之一：

1. **结算**：
   - `settlement_decision` 填 `settle`
   - `confirmed_unit_price_yuan` 填非负金额，例如 `0.200`
   - `confirmed_valid_from` 填历史报工允许追溯的生效时间
   - `confirmed_valid_to` 没有截止时间时留空
   - `confirmation_reason` 填业务依据

2. **不结算/零工价**：
   - `settlement_decision` 填 `no_settlement` 或 `zero_price`
   - `confirmed_unit_price_yuan` 填 `0`（两种结论都建议填 0，避免空值）
   - `confirmed_valid_from` 填本次历史处置的生效时间
   - `confirmation_reason` 必须说明“不结算”和“零工价”的业务含义

## 两种结论的区别

- `no_settlement`：该历史报工不进入应付工资计算；生成修订台账时应保留事实，但结算金额为 0，并显示“不结算”。
- `zero_price`：该工序属于应计入工资台账的事实，但确认单价为 0；显示“零工价”，与“不结算”在审计语义上不能混用。

## 审批要求

- 每行填写 `operator_name/operator_id` 和 `approver_name/approver_id`。
- 不允许只填候选旧工价编号而不填写业务结论。
- `26072701 / 加工分体下端面` 必须单独确认，不能引用相似路线。
- `SB81直壳生产流程` 的 7 项候选工价从 2026-08-01 才生效，是否追溯到 2026-06/07 的历史报工必须明确写在 `confirmation_reason` 中。
- 填写完成后不要直接改生产库；将文件交回后，先做格式、订单覆盖、有效期和金额非负校验，再生成受控 V083 批准清单。
