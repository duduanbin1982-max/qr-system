# 工序质量评价 v058 生产副本预检证据

## 执行范围

- 执行时间：2026-08-09 10:09 CST
- 生产主机：192.168.1.8
- 生产代码目录：`/home/dubin/qr-system`
- 生产服务：用户级 `qr-system.service`
- 生产提交：`ecf5c03f0888a57b9400bbfe04ff1e33bd71fd85`
- 生产数据库：`/home/dubin/qr-system/data/production.db`

本次仅执行在线备份、生产数据库副本迁移预检和只读健康检查。未修改正式数据库，未重启生产服务，未切换生产代码。

## 生产基线

- `PRAGMA user_version`：57
- `PRAGMA integrity_check`：`ok`
- `PRAGMA foreign_key_check`：0 条违规
- 健康接口：`status=ok`、`db=connected`
- 用户级服务状态：`active`

## 在线备份

- 备份文件：`/home/dubin/qr-system/data/backups/production_20260809_100927.db`
- SHA-256：`fb5c4ce7e47a00d4e9486aeeb7afb2bcd134d429f0376f278067b81ba19e2254`
- 备份服务结果：`status=0/SUCCESS`
- 备份副本完整性和外键检查：通过

## v058 副本预检

使用当前代码的正式迁移注册器在隔离副本执行，结果如下：

- 迁移前版本：57
- 执行迁移数：1
- 迁移后版本：58
- 迁移后 `PRAGMA quick_check`：`ok`
- 迁移后外键违规：0
- 迁移记录的人工处理异常：0

迁移前业务状态分布：

| 对象 | 状态 | 数量 |
| --- | --- | ---: |
| 评价 | `confirmed` | 3752 |
| 评价 | `rejected` | 14 |
| 申诉 | `accepted` | 14 |

差异清单：

- 非法评价状态：0
- 非法申诉状态：0
- 已驳回评价仍存在待处理申诉：0

已验证生成的状态保护触发器：

- `trg_pqe_evaluation_status_insert_guard`
- `trg_pqe_evaluation_status_update_guard`
- `trg_pqe_appeal_status_insert_guard`
- `trg_pqe_appeal_status_update_guard`

## 结论

生产副本预检通过，未发现需要人工确认的历史状态异常，满足进入受控发布的数据库门禁条件。正式发布仍需部署已验证代码、运行 v058、重启用户级服务，并执行健康、权限、状态竞争及 Legacy 回退验收。

本地隔离副本在预检完成并核对哈希后已删除；远端在线备份继续保留用于回滚。
