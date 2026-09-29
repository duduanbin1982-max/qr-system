# 库存双视图 V096 发布与回退手册

## 发布前

1. 在生产副本执行 `python scripts/preflight_inventory_dual_view.py --db <只读副本> --limit 1000`。
2. `ok=true`、数据库版本至少 V096、完整性检查通过、外键违规为 0，才允许继续。
3. 确认四个库存开关首轮均为 `false`：查询、分配预览、跨订单出库、产品级阈值。
4. 对生产数据库、前端构建目录、`data/`、附件和审计证据做带 manifest 的最终备份。

## 灰度顺序

1. 先部署代码并重启，保持开关关闭；验收旧的按订单库存接口。
2. 仅开启 `INVENTORY_PRODUCT_QUERY_ENABLED`，验收产品编码汇总、身份异常和详情抽屉。
3. 再开启 `INVENTORY_ALLOCATION_PREVIEW_ENABLED`，验收只读预览、FIFO、人工来源、摘要哈希和缺口提示。
4. 业务确认后才可开启 `INVENTORY_CROSS_ORDER_OUTBOUND_ENABLED`；正式出库必须携带预览摘要和幂等键。
5. 最后按产品逐项配置 `INVENTORY_PRODUCT_THRESHOLD_ENABLED`，验收安全库存和双层预警。

## 回退

1. 关闭新增开关，保留审计日志、分配运行和附件。
2. 停服并恢复前端备份和部署前数据库；不得删除库存流水或分配证据。
3. 回退代码到部署前 SHA，启动服务并验收 `/api/inventory` 按订单视图。
4. 记录回退原因、备份 manifest、迁移日志和操作人/批准人。
