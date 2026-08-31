# 待发布路线精确工价 V074 生产运行手册

## 1. 适用范围与授权边界

本手册用于将待发布路线精确工价能力从 V073 迁移到 V074，并按“关闭、观察、
写入”三个阶段启用功能。V074 保留既有工价、工资引用和发布批次成员，新增工价
作废证据、发布成员变更事件和兼容审计证据。

本手册不是生产变更授权。没有取得当次生产变更的单独明确授权时，只能执行代码
检查、生产数据库只读预检和隔离副本演练；不得执行代码切换、停服、生产迁移、
服务重启或功能开关变更。

## 2. 变更单必填项

- 当前生产提交、目标提交和支持 V074 的回退提交完整 SHA。
- 生产部署目录、数据库绝对路径、服务名和附件目录。
- 维护窗口开始与结束时间、最大允许停机时间。
- 实际操作人、独立批准人和不可复用到其他变更的幂等键。
- 预检源数据库 SHA-256、文件大小、`user_version` 和预检摘要 SHA-256。
- 最终数据库、附件和前端发布备份路径及各自校验值。
- 观察阶段和写入阶段的独立批准记录；写入阶段不得沿用部署授权自动开启。

## 3. 阻断门槛

只读预检报告必须满足：

```json
{
  "status": "passed",
  "mode": "read_only_preflight",
  "database": {
    "user_version": 73,
    "query_only": 1,
    "integrity_check": "ok",
    "foreign_key_check": [],
    "missing_tables": []
  },
  "blocking": {
    "empty_bindings": [],
    "binding_mismatches": [],
    "duplicate_pending_drafts": []
  },
  "source_unchanged": true
}
```

任何空路线/工序版本绑定、根与版本归属错配、路线节点错配、同一待发布节点的重复
草稿、完整性错误或外键错误都必须停止迁移。唯一非阻断例外是 V062 已保留的历史
墓碑：状态为 `retired`、`legacy_binding_unavailable=1`、两个版本 ID 均为空，并且
工资明细和工价解析引用都为零。报告必须通过
`price_aggregates.total.preserved_legacy_unbound_rows` 单独披露该数量；迁移不得补齐、
删除或覆盖这些记录。其他记录不得按名称、编码相似度或当前最新版自动修复。

## 4. 只读预检与迁移计划

在已审核目标代码目录执行，输出文件必须位于本次只读证据目录且不得覆盖旧证据：

```bash
python3 scripts/pending_route_price_v074_operations.py preflight \
  --db <生产数据库绝对路径> \
  --output <证据目录>/pending-route-price-v074-preflight.json

python3 scripts/pending_route_price_v074_operations.py migration-plan \
  --db <生产数据库绝对路径> \
  --output <证据目录>/pending-route-price-v074-migration-plan.json
```

迁移计划必须只有 V074 或为空。若源版本不是 V073、计划包含未审核的其他迁移或
两个命令前后的数据库 SHA-256/文件大小不一致，立即停止。

## 5. 备份与恢复验证

维护窗口前可制作在线备份用于副本演练。停服后仍必须重新制作最终一致性备份。
现有备份脚本同时验证数据库完整性、外键、用户表可读取、附件归档和校验文件：

```bash
QR_PROJECT_ROOT=<生产部署目录> \
DB_PATH=<生产数据库绝对路径> \
BACKUP_DIR=<生产部署目录>/data/backups \
BACKUP_METADATA_FILE=<证据目录>/backup-<本次幂等键>.json \
bash scripts/backup-db.sh

python3 scripts/deployment_manifest.py verify-backup \
  --metadata <证据目录>/backup-<本次幂等键>.json
```

必须记录脚本输出的数据库备份路径和附件备份路径，并再次执行：

```bash
sha256sum <数据库备份路径> <附件备份路径>
/usr/bin/sqlite3 <数据库备份路径> "PRAGMA integrity_check; PRAGMA foreign_key_check;"
tar -tzf <附件备份路径> >/dev/null
```

`integrity_check` 必须为 `ok`，`foreign_key_check` 不得输出任何行，附件归档必须可
完整列出。

## 6. 隔离副本演练

副本目标必须不存在，不得与生产数据库、在线备份或历史证据同名：

```bash
python3 scripts/pending_route_price_v074_operations.py validate-replica \
  --source-db <已验证的V073数据库备份> \
  --replica-db <一次性隔离目录>/pending-route-price-v074-replica.db \
  --output <证据目录>/pending-route-price-v074-replica-validation.json
```

报告必须满足：

- `status=passed`、`source_unchanged=true`、`blocking_differences=[]`。
- `source_version=73`、`target_version=74`、`executed_migrations=1`。
- 已批准和已退役工价的数量、金额及精确绑定聚合前后一致。
- 草稿/待审批发布批次及其工序、路线、工价成员前后一致。
- 工资明细和历史工价解析引用前后一致。
- 副本 `integrity_check=ok`、`foreign_key_check=[]`，三类工价阻断项均为空。

副本演练失败时保留源备份、副本和报告，不得在副本内人工修数后把结果替换为生产
迁移输入。

## 7. 部署前代码检查

在目标提交的干净工作区执行：

```bash
git status --porcelain
git rev-parse HEAD
python3 scripts/check_secrets.py
bash deploy.sh --check-only
python3 -m pytest -q \
  tests/test_pending_route_price_v074_operations.py \
  tests/test_deployment_contracts.py \
  tests/test_migrations.py
```

工作区必须干净，`HEAD` 必须等于变更单目标提交，检查和测试必须全部通过。

## 8. 维护窗口迁移

推荐由已有 `deploy.sh` 执行停服、最终备份、迁移、前端原子发布、部署标识同步、
服务启动和失败自动回退：

```bash
DEPLOYMENT_KEY=<本次幂等键> bash deploy.sh
```

如经批准采用人工分步方式，必须先创建部署 manifest 并确认回退脚本可读取它。维护
窗口内的核心顺序不得改变：

```bash
systemctl --user stop qr-system.service
systemctl --user is-active qr-system.service

QR_PROJECT_ROOT=<生产部署目录> \
DB_PATH=<生产数据库绝对路径> \
BACKUP_DIR=<生产部署目录>/data/backups \
BACKUP_METADATA_FILE=<最终证据目录>/backup-<本次幂等键>.json \
bash scripts/backup-db.sh

python3 scripts/deployment_manifest.py verify-backup \
  --metadata <最终证据目录>/backup-<本次幂等键>.json

python3 -c "from modules.bootstrap import load_environment; load_environment(); from modules.migrations import run_migrations; run_migrations()"

/usr/bin/sqlite3 <生产数据库绝对路径> \
  "PRAGMA user_version; PRAGMA integrity_check; PRAGMA foreign_key_check;"

systemctl --user start qr-system.service
systemctl --user is-active qr-system.service
curl -ksSf --max-time 5 https://127.0.0.1/api/health
```

`is-active` 在停服确认时应返回 `inactive`，因此该检查允许非零退出码；其余写阶段
命令任一失败都必须停止后续步骤并执行第 11 节回退。

## 9. 三段式功能开关

部署及 V074 验收完成后，首先保持全部关闭：

```text
ROUTE_PRICE_PENDING_REFERENCE_ENABLED=false
ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED=false
ROUTE_PRICE_PENDING_WRITE_ENABLED=false
```

观察阶段必须一次性开启引用与兼容审计，写入继续关闭：

```text
ROUTE_PRICE_PENDING_REFERENCE_ENABLED=true
ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED=true
ROUTE_PRICE_PENDING_WRITE_ENABLED=false
```

只有目录、精确版本绑定、权限和兼容审计差异全部为零并取得新的独立批准后，才能
进入写入阶段：

```text
ROUTE_PRICE_PENDING_REFERENCE_ENABLED=true
ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED=true
ROUTE_PRICE_PENDING_WRITE_ENABLED=true
```

每次先在候选环境文件中准备完整三项值，再验证阶段转换，验证通过后才原子替换
生产环境文件并重启服务：

```bash
python3 scripts/pending_route_price_v074_operations.py validate-flag-transition \
  --current-env <当前生产环境文件> \
  --candidate-env <本次候选环境文件> \
  --output <证据目录>/pending-route-price-v074-flag-transition.json

chmod --reference=<当前生产环境文件> <本次候选环境文件>
mv <本次候选环境文件> <当前生产环境文件>
systemctl --user restart qr-system.service

python3 scripts/pending_route_price_v074_operations.py flags \
  --env <当前生产环境文件> \
  --output <证据目录>/pending-route-price-v074-flags-after-restart.json
```

不允许只开启引用、不允许跳过观察阶段直接开启写入，也不允许在普通发布中反向关闭
开关。反向切换仅能作为已批准回退步骤执行。

## 10. 生产验收

每次迁移或开关切换后重新运行只读预检，并执行：

```bash
/usr/bin/sqlite3 -readonly <生产数据库绝对路径> <<'SQL'
PRAGMA user_version;
PRAGMA integrity_check;
PRAGMA foreign_key_check;

SELECT status,COUNT(*) AS rows,
       COALESCE(SUM(normal_unit_price_micros),0) AS micros
FROM route_price_versions
GROUP BY status ORDER BY status;

SELECT COUNT(*) AS invalid_exact_bindings
FROM route_price_versions price
LEFT JOIN process_route_versions route_version
  ON route_version.id=price.route_version_id
LEFT JOIN process_versions process_version
  ON process_version.id=price.process_version_id
LEFT JOIN process_route_version_items item
  ON item.route_version_id=price.route_version_id
 AND item.process_id=price.process_id
 AND item.process_version_id=price.process_version_id
WHERE price.route_version_id IS NULL OR price.process_version_id IS NULL
   OR route_version.process_route_id<>price.route_id
   OR process_version.process_id<>price.process_id
   OR item.id IS NULL;

SELECT COUNT(*) AS duplicate_pending_draft_groups
FROM (
  SELECT price.route_version_id,price.process_version_id
  FROM route_price_versions price
  JOIN process_route_versions route_version
    ON route_version.id=price.route_version_id
  JOIN process_versions process_version
    ON process_version.id=price.process_version_id
  WHERE price.status='draft' AND route_version.status='pending_approval'
    AND process_version.status IN ('published','pending_approval')
  GROUP BY price.route_version_id,price.process_version_id
  HAVING COUNT(*)>1
);
SQL
```

验收还必须确认：

- 健康接口正常，数据库连接正常，服务日志无迁移、外键或敏感数据异常。
- 观察阶段能看到待审批路线和精确工序版本，但创建入口仍被禁用。
- 最新兼容审计观察值差异为零，历史差异证据仍保留且未被更新或删除。
- 写入阶段开启后，草稿路线不能定价；待审批路线只能创建精确绑定的工价草稿。
- 待审批工价不能单独批准，只能随精确路线、工序进入同一成组发布批次。
- 路线驳回后同版工价原子变为 `voided`，旧记录不可修改、批准或重新入批次。
- 重新提交路线后必须新建工价草稿，原作废记录仍可追溯。
- 制单与批准职责分离，越权、过期摘要和重复幂等键均返回约定错误码。

## 11. 全量回退

任何完整性、外键、业务聚合、发布成员、工资引用、兼容差异或健康检查失败，都应
保持或重新进入停服状态，保存失败现场和日志，然后使用本次部署 manifest 回退：

```bash
bash scripts/rollback-deployment.sh <本次部署manifest绝对路径>
```

该脚本必须恢复部署前数据库、附件和前端发布文件，代码切回变更单批准的回退提交，
同步 `.deployed_commit` 并重新启动服务。回退后执行：

```bash
git rev-parse HEAD
cat .deployed_commit
/usr/bin/sqlite3 -readonly <生产数据库绝对路径> \
  "PRAGMA user_version; PRAGMA integrity_check; PRAGMA foreign_key_check;"
systemctl --user is-active qr-system.service
curl -ksSf --max-time 5 https://127.0.0.1/api/health
```

回退不得删除 `data/`、附件、预检报告、迁移报告、失败现场或历史审计证据。若已经
产生真实待发布工价写入，不得通过删除工价版本或事件伪造回退；应先关闭新增写入，
保留事实，再通过受控修订或前滚迁移处置。
