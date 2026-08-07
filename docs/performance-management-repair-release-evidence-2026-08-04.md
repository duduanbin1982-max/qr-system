# 绩效管理版本化台账发布证据

## 1. 发布状态

- 实施日期：2026-08-07（Asia/Shanghai）
- 生产主机：`192.168.1.8`
- 生产目录：`/home/dubin/qr-system`
- 发布分支：`codex/performance-ledger-repair`
- 发布前提交：`c0817bb15cb6a346de411f94bb8142f04145ad0c`
- 已部署提交：`399d23831f6c5224639a2b478ebacce5fd492d42`
- 数据库迁移：V55 -> V56 已完成
- 正式查询模式：`PERFORMANCE_LEDGER_V2_QUERY_ENABLED` 未配置，按代码默认值保持 `false`
- 当前结论：V56 架构、Legacy 只读导入和 Legacy 查询兼容已发布；历史 V2 生成、主管复核、双人批准和正式查询切换尚未执行。

未继续切换 V2 的原因不是技术迁移失败，而是生产库尚无已发布的 V2 评分规则、尚无已批准的岗位目标，并且人工岗位映射及职责分离人员尚未由业务负责人确认。发布过程没有绕过这些门禁。

## 2. 代码和完整回归

本地工作区在实施前、完整构建后均为干净状态。生产工作区在切换前为 `codex/versioned-payroll-ledger@c0817bb`，没有未提交变更；随后快进切换到待发布分支。

本地完整验证结果：

| 验证项 | 结果 |
| --- | --- |
| 后端完整测试 | `625 passed in 117.62s` |
| 前端架构检查 | 通过，30 个 API namespace、339 个唯一方法、180 个文件、434 条内部依赖边 |
| 前端单元测试 | `19 files / 62 tests passed` |
| 浏览器关键路径 | `15 passed` |
| 生产前端构建 | 通过，230 个模块完成转换 |

生产候选工作树 `/home/dubin/qr-system-task15-stage-399d238` 固定为 `399d238`，`scripts/deploy.sh --check-only` 通过。正式部署后再次执行 check-only，结果仍通过。

## 3. 备份与恢复验证

### 3.1 项目目录外备份

| 项目 | 值 |
| --- | --- |
| 路径 | `/home/dubin/qr-system-release-backups/20260807-performance-v56/production-pre-v56.db` |
| 字节数 | `19,988,480` |
| SHA-256 | `f2cc67332fecea3e646a61f7a3d015a997ecdd2d4b978b56012f153fe0782fe0` |
| `PRAGMA integrity_check` | `ok` |
| `PRAGMA foreign_key_check` | 无结果 |

### 3.2 部署脚本内部备份

| 项目 | 值 |
| --- | --- |
| 路径 | `/home/dubin/qr-system/data/backups/production_20260807_153833.db` |
| 字节数 | `19,988,480` |
| SHA-256 | `245ed00c20925c77472220fe6ffd576d76c800b87711a4deaa7b2b7a25f23574` |
| `PRAGMA integrity_check` | `ok` |

数据库迁移只允许向前。应用回滚点为 `c0817bb`；若需要回滚，关闭 V2 查询并回退应用/静态资源，保留 V56 表和证据。只有数据库完整性受损时才允许停止服务并从外置备份恢复。

## 4. 生产数据库副本演练

演练副本：

`/home/dubin/qr-system-release-backups/20260807-performance-v56/production-v55-copy.db`

迁移前基线：

- `PRAGMA user_version = 55`
- `PRAGMA integrity_check = ok`
- 表数量：94
- Legacy 绩效评分：64
- Legacy 复核：0
- Legacy 改进计划：0
- 绩效月份：2026-06 至 2026-07，共 2 个月

V55 -> V56 演练结果：

- 执行迁移数：1
- 迁移耗时：0.21 秒
- `PRAGMA user_version = 56`
- `PRAGMA integrity_check = ok`
- `PRAGMA foreign_key_check` 无结果
- 表数量：112
- 索引数量：251
- Legacy 写保护触发器：18
- Legacy V1 批次：2
- Legacy 评分修订：64
- 迁移 manifest：2
- 权限迁移报告：4

副本历史生成尝试被正确拒绝：

```text
apply_exit_code=1
未找到当月已发布的绩效规则
```

该尝试在事务内回滚，没有生成 V2 批次，也没有写入工资台账。

## 5. 正式迁移与生产健康

官方 `deploy.sh` 已完成完整测试、内部备份、V56 迁移、前端构建、用户级 systemd 服务重载和健康检查。

发布后状态：

- Git HEAD、`.deployed_commit` 和健康接口 commit 均为 `399d23831f6c5224639a2b478ebacce5fd492d42`
- `qr-system.service` 为 `active`
- 服务于 2026-08-07 15:38:41 +08:00 完成重启
- 健康接口：`status=ok`、`db=connected`
- `PRAGMA user_version = 56`
- `PRAGMA integrity_check = ok`
- 表数量：112
- 索引数量：251
- Legacy 写保护触发器：18
- V2 正式查询开关：关闭

正式库当前批次仅有：

| 生产月 | 版本 | 状态 | 来源 |
| --- | ---: | --- | --- |
| 2026-06 | V1 | approved | Legacy 只读导入 |
| 2026-07 | V1 | approved | Legacy 只读导入 |

没有创建或批准 V2 批次。

## 6. 历史预检证据

正式库只读预检通过四项审计基线校验：

| 指标 | 总数 |
| --- | ---: |
| Legacy 评分 | 64 |
| 已覆盖但旧修订不可恢复 | 64 |
| 缺少历史岗位快照 | 30 |
| 07:00 口径跨自然月报工 | 5 |
| 07:00 口径跨自然月质量记录 | 11 |
| 质量来源歧义 | 0 |
| 缺少已批准岗位目标的员工 | 34 |

月度摘要：

| 生产月 | 评分 | 覆盖 | 缺岗位 | 跨月报工 | 跨月质量 | 缺目标 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-06 | 27 | 27 | 27 | 1 | 0 | 0 |
| 2026-07 | 37 | 37 | 3 | 4 | 11 | 34 |

- 全局 manifest SHA-256：`c98835a9cb56c684b9b0f114319c75903ca52841ef8e264fd3a5009336ff1044`
- 正式预检 JSON SHA-256：`58c706327c2f28fae615bc587a2110b4a94d1f88424215508a665944d13c784b`
- 正式预检摘要 SHA-256：`d1c427bbd1e8d34e72ce2b2954df3c6510c014afffc0a8f07e344aa5b31894f3`

## 7. 权限影响与职责分离

V56 权限迁移结果：

| 角色 | 受影响用户 | 迁移结果 |
| --- | ---: | --- |
| worker | 38 | 增加 `page:performance` 和 `performance:view_self` |
| production_manager | 0 | 移除 Legacy 宽权限，保留本人查看 |
| qc_inspector | 0 | 移除 Legacy 宽权限，保留本人查看 |
| warehouse_keeper | 0 | 移除 Legacy 宽权限，保留本人查看 |

当前共有 4 个管理员账号，管理员角色使用通配权限。本人查询已用真实生产数据验证：员工 `10271` 只能看到本人的 1 条 2026-07 评分，尝试查询员工 `10272` 被拒绝并返回“无权查看该员工绩效”。

以下显式授权仍待业务负责人指定，不能用管理员通配权限替代正式职责拆分：

- 部门主管复核人
- 历史 V2 制单人
- 与制单人不同的批准人
- 改进计划管理人
- 与计划管理人分离的复评人

当前角色和用户导出位于：

- `/home/dubin/qr-system-release-backups/20260807-performance-v56/current-performance-user-roles.csv`
- `/home/dubin/qr-system-release-backups/20260807-performance-v56/performance-permission-impact.csv`

## 8. 工资隔离验证

绩效迁移前后工资台账完全一致：

| 项目 | 迁移前 | 迁移后 |
| --- | ---: | ---: |
| 工资批次 | 4 | 4 |
| 员工工资行 | 119 | 119 |
| 员工应付合计（分） | 27,695,420 | 27,695,420 |
| 工资明细 | 2,975 | 2,975 |
| 工资明细金额合计（分） | 27,695,420 | 27,695,420 |
| 工价解析 | 2,638 | 2,638 |
| 调整项 | 0 | 0 |
| 工资事件 | 4 | 4 |
| 工资迁移 manifest | 1 | 1 |

绩效 V56 迁移和历史预检均没有写工资台账。

## 9. 真实业务验收结果

| 验收项 | 状态 | 证据或原因 |
| --- | --- | --- |
| Legacy 正式结果可查 | 通过 | 管理员查询 2026-06 返回 27 条、2026-07 返回 37 条，来源为 `legacy_v1`、版本 V1、状态 approved |
| 本人访问与跨员工越权 | 通过 | 本人仅 1 条；指定其他员工 ID 被拒绝 |
| 07:00 生产月边界 | 预检通过 | 识别 5 条跨月报工和 11 条跨月质量记录 |
| 质量来源唯一性 | 预检通过 | 质量来源歧义为 0；尚未生成 V2 正式事实 |
| 工资隔离 | 通过 | 行数及 27,695,420 分金额摘要完全一致 |
| Legacy 只读保护 | 通过 | 18 个 Legacy 写保护触发器存在，旧写接口改为失败关闭 |
| 零产量、岗位目标评分和单人岗位排名 | 阻塞 | 尚无已发布规则和已批准岗位目标，不能生成合格 V2 |
| 主管复核与岗位排名原子重算 | 阻塞 | 尚无 V2 批次及显式部门主管账号 |
| 制单/批准双人分离和旧 row_version 409 | 阻塞 | 尚未指定制单人、批准人并走真实审批 |
| 改进计划状态机和失败复评 | 阻塞 | 尚未指定计划管理人和复评人 |
| V2 批准、V1 回查和 V3 取代 | 阻塞 | V2 尚未生成和批准 |

## 10. 待业务确认清单

### 10.1 人工岗位映射

30 条记录必须逐条人工确认，禁止按名称相似度自动修复：

`/home/dubin/qr-system-release-backups/20260807-performance-v56/manual-position-mapping-required.csv`

文件 SHA-256：`87f49058491561b1dcf9b851a33e17857be85eac7743adf5d30a3341dce1df8d`

### 10.2 岗位目标

2026-07 有 34 名员工涉及 8 个岗位目标分组，需要业务负责人给出目标产量和最低有效报工日并批准版本：

`/home/dubin/qr-system-release-backups/20260807-performance-v56/position-target-required.csv`

文件 SHA-256：`35792f4f83702f6163bf60598bac90e91c5f442683335a7e193d7b36ec24582e`

### 10.3 首个 V2 规则

生产库当前状态：

- 规则版本：0
- 已发布规则：0
- 岗位目标版本：0
- 已批准岗位目标：0

必须由业务负责人确认并发布首个 V2 规则，至少包括权重、预警阈值、产量评分参数、质量扣分参数、最低有效报工日和生效月份。

### 10.4 显式授权矩阵

必须指定不同人员承担制单和批准，并明确部门复核、计划管理和计划复评人员。当前仅管理员通配权限和员工本人查看权限，不满足完整生产验收所需的显式职责拆分证据。

## 11. 下一次安全续跑点

业务负责人完成规则、岗位目标、30 条岗位映射和授权矩阵后，按以下顺序继续：

1. 再次执行生产只读 preflight，核对 `64 / 30 / 5 / 11` 和 manifest SHA-256。
2. 使用已授权制单人执行 2026-06 至 2026-07 的 `--apply`，生成影子 V2。
3. 处理所有岗位、目标和质量异常；提交审批前未确认异常必须为 0。
4. 导出 V1/V2 逐人差异并由部门主管复核。
5. 制单人提交，由不同批准人批准。
6. 验证工资台账摘要仍完全一致。
7. 将 `PERFORMANCE_LEDGER_V2_QUERY_ENABLED=true` 写入生产环境并重启服务。
8. 执行 V2 正式结果、Legacy 回退、越权、并发和改进计划真实业务冒烟。

在以上条件满足前，V2 查询保持关闭，Legacy V1 继续作为正式结果来源。

## 12. 证据文件哈希

| 文件 | SHA-256 |
| --- | --- |
| `copy-baseline.txt` | `06024183dea743329187460762a0571cda9dc0985da644d937896613a9a76217` |
| `copy-v56-validation.txt` | `a3d10dd3950ec9ea5304e849c819d6e214baef8c0eb9abeb538fd1ad68d53e8a` |
| `business-readiness-summary.txt` | `0fb27417a390c54f30ff23e9f2bb3cf025acb05f3e4ba98beeea070d14fbf7b0` |
| `historical-apply-blocker.txt` | `05856c27b75fe1ab626bc6fc372c4e4363de3ed56ab17e208e6089222a9b2763` |
| `current-performance-user-roles.csv` | `5e6f72ead40f3f9b748f7e4a65424cfbcb6b350dca1d367271c4b6d1b9381bd4` |
| `performance-permission-impact.csv` | `2ac1707a827cf04b438b41225634cc6cdb93225b3d9730d4ab2d667269235fc9` |
| `production-check-only.txt` | `7ae65203c4f21a3a695b6ab2856358d16a8fe38ada6d919a505c2c14e683fd98` |

