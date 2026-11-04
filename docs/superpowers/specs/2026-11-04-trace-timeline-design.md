# 批次 E：生命周期时间线排序

用户已确认：以纯函数将订单创建、报工、质检、入库、发货转换为
`timestamp/kind/stable_id/label/payload` DTO；仅对新数组排序。

时间升序；相同时按订单、报工、质检、入库、发货及稳定 ID 排序。
同类重复 ID 保留，使用出现序号生成唯一渲染 key。缺失或无效时间排末尾，
显示“时间缺失”。无时区时间按生产时区 Asia/Shanghai（+08:00）解析，
显式时区按对应实际时刻比较。

沿用原时间字段优先级：订单/报工/入库 created_at；
质检 inspected_at 或 created_at；发货 completed_at 或 created_at。
序列号模式的库存、发货仅取 order_scope；报工独立卡片维持原集合顺序。
组件使用 computed，切换订单后重建展示。后端及 API 契约不变。

验证包含跨类型交错顺序、相同时间、缺失及无效时间、重复 ID、
输入不变性、订单切换和真实浏览器渲染。纯工具登记必须继续禁止
imports、browser state 和 HTTP transport，不放宽其他分层规则。
