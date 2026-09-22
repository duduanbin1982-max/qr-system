# 生产排程 Task 2：生产只读副本证据

**执行日期：** 2026-09-22（Asia/Shanghai）
**目标主机：** `192.168.1.8`（SSH 别名 `codex-8`）
**生产目录：** `/home/dubin/qr-system`
**生产数据库：** `/home/dubin/qr-system/data/production.db`

## 只读复核

| 项目 | 复核前 | 复核后 |
|---|---|---|
| 生产代码提交 | `f161654c3754e5ee33b0ac62883e7369e97b830f` | `f161654c3754e5ee33b0ac62883e7369e97b830f` |
| `PRAGMA user_version` | `90` | `90` |
| `PRAGMA quick_check` | `ok` | `ok` |
| `production.db` SHA-256 | `d3a9ba5e4783bf4fea863be618aeacad46ce89e30533beecbf2ce9a29b9aacfe` | `d3a9ba5e4783bf4fea863be618aeacad46ce89e30533beecbf2ce9a29b9aacfe` |

复核前后提交、数据库版本、完整性和文件摘要一致，证明本次操作没有写入生产数据库或代码目录。

## 副本审计方式

1. 使用 `scp -p` 将生产 `production.db` 读取到本地临时副本；
2. 在本地副本执行 V091 迁移；
3. 运行 `scripts/preflight_schedule_precision.py --limit 1000`；
4. 仅在本地副本生成排程事实和工时覆盖审计；
5. 生产主机未执行迁移、写入、停服、重启、配置修改或附件操作。

## 审计产物

- [Task 2 真实工时审计报告](../.tmp-production-scheduling-task2-20260922/report/production-scheduling-task2-real-work-time-audit-20260922.md)
- [工时覆盖 CSV 明细](../.tmp-production-scheduling-task2-20260922/report/work-time-coverage-audit.csv)
- [工时覆盖 JSON 明细](../.tmp-production-scheduling-task2-20260922/report/work-time-coverage-audit.json)

## 结果摘要

- 活动订单：95；工序：664；
- 内部可评估工序：386；匹配：386；覆盖率：100%；
- 产品/路线版本/工序版本绑定命中：386；版本绑定覆盖率：100%；
- 缺失标准工时：0；节点/日历/其他阻断：0；
- 外协/非排程：5；已完成事实：273；
- 5 条外协/非排程工序均保留为执行策略，不占用内部节点容量。
