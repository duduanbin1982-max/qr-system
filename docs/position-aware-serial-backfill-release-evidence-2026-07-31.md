# 岗位感知跨工序补报发布验收记录

## 发布信息

- 生产服务：`https://192.168.1.8`
- 发布日期：2026-07-31
- 数据库版本：47 -> 48
- 外置备份：`/home/dubin/.codex-backup/production_before_position_backfill_20260731.db`
- 备份 SHA-256：`256949d5164a2eb4aeaec17f4a357b1adee5e759bc4425fe43b5d015b7fc9df7`

## 数据库验证

- 迁移前后 `work_records` 均为 2960 条。
- 迁移前后 `serial_backfill` 均为 1 条。
- 版本 48 新增 `submit_position_id` 和 `submit_position_name`。
- 迁移前备份和迁移后生产库的 `PRAGMA integrity_check` 均为 `ok`。

## 回归验证

- 关键后端套件：53 passed。
- 完整后端套件：399 passed。
- 前端单元测试：38 passed。
- Vite 构建、API facade 检查和 import cycle 检查通过。
- 移动端 `mobile-order.js`、`mobile-auth.js`、`mobile-utils.js` 语法检查通过。

## 生产验收

- 首页、移动端、主 JS/CSS、审批页 JS/CSS 均返回 HTTP 200。
- Gunicorn 已平滑重载，`/api/health` 返回 `status=ok` 和 `db=connected`。
- 用户 `0703` 当前活动岗位为“喷漆工”，工序范围为 `223/喷漆`。
- 序列号 `26062502-002` 返回唯一补报候选“喷漆”，选择来源为 `position_auto`。
- 在生产数据库的临时副本中提交补报：记录为 `pending`，岗位快照为 `6/喷漆工`，实际完成时间为空，原因为空。
- 待审批记录显示操作员、喷漆工岗位、喷漆工序和申请时间。
- 审批前工件当前工序和订单喷漆完成数均未改变。
- 临时数据库已删除，生产库没有写入验收报工记录。

## 特定工件说明

`26062502-022` 已有用户 `0703` 的“喷漆”补报记录，且状态为已审批，因此当前不再返回喷漆补报候选。
