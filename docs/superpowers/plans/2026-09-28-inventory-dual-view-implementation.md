# 库存管理双视图与受控跨订单出库实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变订单级库存事实和现有库存台账的前提下，增加按产品编码实时聚合视图、兼容分组、FIFO/人工来源分配、受控跨订单出库、双层预警和完整审计。

**Architecture:** 保留 `inventory` 与 `inventory_logs` 作为库存事实和不可变流水；以稳定 `product_id` 生成实时产品聚合读模型；使用不访问数据库的纯分配器计算来源；由单一应用服务在同一数据库事务中完成库存扣减、分配证据和审计 outbox。前端保持现有按订单视图，并增加产品编码工作台、右侧详情抽屉和分配抽屉。

**Tech Stack:** Python 3、Flask、SQLite、JSON Schema、Vue 3.5 Composition API、现有 API facade、Vitest 4、Vue Test Utils、Playwright 1.62、pytest、openpyxl。

## Global Constraints

- 产品身份必须以稳定的 `products.id`/`product_id` 为准，当前编码和历史别名只用于解析与展示。
- 库存事实继续保留具体 `inventory_id`、订单、批次、序列号和库位；产品汇总行不是可扣减库存实体。
- 首期使用实时聚合查询，不新增需要同步维护的产品库存总量字段。
- 不允许依据产品名称、相似型号或模糊文本自动归组。
- 不同规格、路线版本、质量状态或受限批次不得错误混用。
- 正式跨订单出库必须重新读取库存、校验预览摘要、保证数量守恒并在一个数据库事务中提交。
- 所有库存余额变化只能通过 `InventoryPostingService` 完成。
- 成功出库时，库存流水、分配运行、分配项目和审计 outbox 必须全部提交或全部回滚。
- 默认 FIFO；具备 `inventory:allocate` 权限的用户可以指定来源，但必须填写原因。
- 默认禁止静默部分出库；不足时返回准确缺口数量。
- 订单级和产品级安全库存分别配置、分别计算、同时展示。
- 产品聚合必须在权限过滤后进行，不得扩大现有数据访问范围。
- 现有 `/api/inventory`、按订单列表、手工单条出入库、预留、盘点、批次和序列号行为保持兼容。
- 新能力必须按“只读查询 → 分配预览 → 正式出库”顺序通过独立功能开关发布。
- 所有任务采用 TDD；每个任务形成一个可独立审核和回退的提交。
- 不修改生产环境；生产迁移和开关切换必须在后续单独授权的维护窗口执行。

---

## File Structure

### New backend production files

- `modules/migration_inventory_product_views.py`
  定义包含版本 96、说明和 `m096_inventory_product_views` 函数的 `MIGRATIONS`；V096：库存产品身份、快照、冻结数量、产品阈值、分配运行与分配项目、索引、不可变触发器及权限兼容迁移。
- `modules/domain/inventory_allocation.py`
  不访问数据库的候选库存、分配请求、分配项目、分配结果和 FIFO/人工分配算法。
- `modules/repositories/inventory_product_repository.py`
  产品身份异常、产品汇总、兼容分组、订单/批次/库位明细和候选库存查询。
- `modules/repositories/inventory_allocation_repository.py`
  产品阈值、分配运行、分配项目、幂等回放和事务内证据保存。
- `modules/services/inventory_product_query_service.py`
  只读产品聚合、详情、能力开关和双层预警编排。
- `modules/services/inventory_allocation_service.py`
  预览及正式跨订单出库应用服务。
- `modules/services/inventory_product_export_service.py`
  产品汇总及展开明细 Excel 导出。
- `scripts/preflight_inventory_product_groups.py`
  生产副本只读身份覆盖、数量守恒、异常清单和典型 FIFO 试算。

### Modified backend production files

- `modules/migration_catalog.py`
  导入 `MIGRATIONS as INVENTORY_PRODUCT_VIEW_MIGRATIONS`，注册 V096 并把线性迁移链扩展到 96。
- `modules/config.py`
  增加产品查询、分配预览、正式跨订单出库和产品阈值四个功能开关及依赖校验。
- `modules/domain/errors.py`
  增加查询关闭、预览关闭、库存不足、预览过期和正式出库关闭的结构化错误码与处理动作。
- `modules/permission_catalog.py`
  增加库存导出、入库、出库、来源分配、预留、调整、审计和阈值管理动作。
- `modules/repositories/inventory_repository.py`
  在现有按订单查询中返回产品身份快照和冻结数量；保留现有写接口。
- `modules/services/inventory_service.py`
  新建库存时解析并冻结产品身份；原有单条出入库仍委托 `InventoryPostingService`。
- `modules/routes/inventory.py`
  增加能力、产品汇总、详情、预览、正式出库、阈值和产品导出端点。
- `modules/schemas/inventory.py`
  增加产品查询写命令的 JSON Schema。

### New frontend production files

- `frontend/src/composables/inventory/useInventoryProductGroups.js`
  产品视图查询、筛选、详情、预览、正式提交、阈值和保存筛选状态。
- `frontend/src/components/inventory/InventoryViewTabs.vue`
  “按订单/按产品编码”切换及功能开关状态。
- `frontend/src/components/inventory/ProductInventoryTable.vue`
  产品汇总表、双层预警和身份异常提示。
- `frontend/src/components/inventory/ProductInventoryDrawer.vue`
  兼容分组、订单、批次、库位及库存来源详情。
- `frontend/src/components/inventory/ProductAllocationDrawer.vue`
  FIFO/指定来源、分配预览、冲突、原因、二次确认和正式出库。

### Modified frontend production files

- `frontend/src/lib/api/inventory.js`
  暴露库存能力、产品汇总、详情、预览、正式出库、阈值和导出 facade。
- `frontend/src/composables/useInventory.js`
  保留按订单视图职责，并暴露刷新钩子给产品工作台。
- `frontend/src/views/InventoryList.vue`
  组合双视图及抽屉，避免继续扩大现有单文件逻辑。

### New and modified tests

- `tests/test_inventory_product_migration_v096.py`
- `tests/inventory_product_helpers.py`
- `tests/test_inventory_product_query.py`
- `tests/test_inventory_source_allocator.py`
- `tests/test_inventory_group_outbound.py`
- `tests/test_inventory_product_export.py`
- `tests/test_inventory_product_preflight.py`
- `tests/test_migrations.py`
- `tests/test_inventory_ledger.py`
- `tests/test_architecture_imports.py`
- `frontend/tests/unit/inventory-product-api.spec.js`
- `frontend/tests/unit/useInventoryProductGroups.spec.js`
- `frontend/tests/unit/ProductInventoryWorkbench.spec.js`
- `frontend/tests/unit/inventory-composable.spec.js`
- `frontend/tests/e2e/inventory-product-workbench.spec.js`

### Documentation

- `docs/runbooks/inventory-product-views-v096-rollout.md`
- `docs/superpowers/evidence/inventory-product-v096-replica-validation.md`（只在真实副本验证阶段生成）

---

### Task 1: 建立 V096 数据基础、权限和功能开关

**Files:**
- Create: `modules/migration_inventory_product_views.py`
- Modify: `modules/migration_catalog.py:1-81`
- Modify: `modules/config.py:1-260`
- Modify: `modules/permission_catalog.py:1-120`
- Modify: `modules/config.py:280-350`
- Test: `tests/test_inventory_product_migration_v096.py`
- Test: `tests/test_migrations.py:1-120`

**Interfaces:**
- Consumes: existing `inventory`, `orders`, `products`, `product_code_aliases`, `inventory_logs`, `roles`, `users` tables.
- Produces: V096 schema; `INVENTORY_PRODUCT_QUERY_ENABLED`, `INVENTORY_ALLOCATION_PREVIEW_ENABLED`, `INVENTORY_CROSS_ORDER_OUTBOUND_ENABLED`, `INVENTORY_PRODUCT_THRESHOLD_ENABLED`; new permission codes.

- [ ] **Step 1: Write failing migration tests**

Create `tests/test_inventory_product_migration_v096.py` with fixtures that prove unique identities are backfilled and conflicts remain unresolved:

```python
import json
import sqlite3

from modules.migration_inventory_product_views import m096_inventory_product_views


def _columns(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def test_v096_adds_product_identity_and_immutable_allocation_evidence(db):
    m096_inventory_product_views(db)

    assert {
        "product_id", "product_code_snapshot", "product_name_snapshot",
        "frozen_quantity", "route_version_id_snapshot", "quality_status",
    }.issubset(_columns(db, "inventory"))
    tables = {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {
        "product_inventory_thresholds",
        "inventory_allocation_runs",
        "inventory_allocation_items",
    }.issubset(tables)


def test_v096_backfills_only_unambiguous_product_identity(db):
    product_id = db.execute(
        "INSERT INTO products(product_code, product_name) VALUES('P-1001','产品一')"
    ).lastrowid
    order_id = db.execute(
        "INSERT INTO orders(order_no,product_code,product_id,product_name,quantity) "
        "VALUES('O-1','P-1001',?,'产品一',1)",
        (product_id,),
    ).lastrowid
    inventory_id = db.execute(
        "INSERT INTO inventory(product_model,product_name,quantity,order_id) "
        "VALUES('P-1001','产品一',5,?)",
        (order_id,),
    ).lastrowid

    m096_inventory_product_views(db)

    row = db.execute(
        "SELECT product_id,product_code_snapshot,product_name_snapshot "
        "FROM inventory WHERE id=?",
        (inventory_id,),
    ).fetchone()
    assert tuple(row) == (product_id, "P-1001", "产品一")


def test_v096_does_not_hide_order_and_model_identity_conflict(db):
    first = db.execute(
        "INSERT INTO products(product_code,product_name) VALUES('P-A','A')"
    ).lastrowid
    second = db.execute(
        "INSERT INTO products(product_code,product_name) VALUES('P-B','B')"
    ).lastrowid
    db.execute(
        "INSERT OR IGNORE INTO product_code_aliases(product_id,product_code,source) "
        "VALUES(?, 'P-B', 'current')",
        (second,),
    )
    order_id = db.execute(
        "INSERT INTO orders(order_no,product_code,product_id,product_name,quantity) "
        "VALUES('O-X','P-A',?,'A',1)",
        (first,),
    ).lastrowid
    inventory_id = db.execute(
        "INSERT INTO inventory(product_model,product_name,quantity,order_id) "
        "VALUES('P-B','B',5,?)",
        (order_id,),
    ).lastrowid

    m096_inventory_product_views(db)

    assert db.execute(
        "SELECT product_id FROM inventory WHERE id=?", (inventory_id,)
    ).fetchone()[0] is None


def test_v096_grants_new_actions_without_removing_existing_permissions(db):
    role_id = db.execute(
        "INSERT INTO roles(name,code,permissions) VALUES('仓库','warehouse-x',?)",
        (json.dumps(["inventory:view", "inventory:edit"]),),
    ).lastrowid

    m096_inventory_product_views(db)

    permissions = json.loads(db.execute(
        "SELECT permissions FROM roles WHERE id=?", (role_id,)
    ).fetchone()[0])
    assert {"inventory:view", "inventory:edit"}.issubset(permissions)
    assert {
        "inventory:export", "inventory:inbound", "inventory:outbound",
        "inventory:allocate", "inventory:reserve", "inventory:adjust",
        "inventory:audit", "inventory:manage_threshold",
    }.issubset(permissions)
```

- [ ] **Step 2: Run migration tests and verify RED**

Run:

```bash
python -m pytest -q tests/test_inventory_product_migration_v096.py tests/test_migrations.py::test_latest_version_matches_highest_registered_migration
```

Expected: FAIL because the V096 module, columns, tables, permissions and registry entry do not exist.

- [ ] **Step 3: Implement V096 schema and controlled backfill**

Create `modules/migration_inventory_product_views.py` with this public entry point and table contract:

```python
import json

from modules.migration_helpers import add_column_if_missing


INVENTORY_PRODUCT_PERMISSIONS = (
    "inventory:export", "inventory:inbound", "inventory:outbound",
    "inventory:allocate", "inventory:reserve", "inventory:adjust",
    "inventory:audit", "inventory:manage_threshold",
)


def _merge_inventory_permissions(db):
    for row in db.execute("SELECT id,permissions FROM roles ORDER BY id").fetchall():
        values = json.loads(row["permissions"] or "[]")
        if not isinstance(values, list) or "*" in values:
            continue
        additions = []
        if "inventory:view" in values:
            additions.extend(("inventory:export", "inventory:audit"))
        if "inventory:edit" in values:
            additions.extend(code for code in INVENTORY_PRODUCT_PERMISSIONS if code not in additions)
        merged = list(dict.fromkeys([*values, *additions]))
        if merged != values:
            db.execute(
                "UPDATE roles SET permissions=?,updated_at=datetime('now','localtime') WHERE id=?",
                (json.dumps(merged, ensure_ascii=False), row["id"]),
            )


def m096_inventory_product_views(db):
    add_column_if_missing(db, "inventory", "product_id", "INTEGER REFERENCES products(id) ON DELETE RESTRICT")
    add_column_if_missing(db, "inventory", "product_code_snapshot", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "inventory", "product_name_snapshot", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing(db, "inventory", "frozen_quantity", "REAL NOT NULL DEFAULT 0")
    add_column_if_missing(db, "inventory", "route_version_id_snapshot", "INTEGER REFERENCES process_route_versions(id) ON DELETE RESTRICT")
    add_column_if_missing(db, "inventory", "quality_status", "TEXT NOT NULL DEFAULT 'qualified'")

    db.execute("""
        UPDATE inventory
        SET product_id=(SELECT o.product_id FROM orders o WHERE o.id=inventory.order_id),
            product_code_snapshot=COALESCE(
                NULLIF((SELECT o.product_code FROM orders o WHERE o.id=inventory.order_id),''),
                product_model,''
            ),
            product_name_snapshot=COALESCE(NULLIF(product_name,''),'')
        WHERE product_id IS NULL
          AND order_id IS NOT NULL
          AND (SELECT o.product_id FROM orders o WHERE o.id=inventory.order_id) IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM product_code_aliases a
              WHERE a.product_code=inventory.product_model
                AND a.product_id<>(SELECT o.product_id FROM orders o WHERE o.id=inventory.order_id)
          )
    """)
    db.execute("""
        UPDATE inventory
        SET product_id=(
                SELECT a.product_id FROM product_code_aliases a
                WHERE a.product_code=inventory.product_model
            ),
            product_code_snapshot=COALESCE(NULLIF(product_model,''),''),
            product_name_snapshot=COALESCE(NULLIF(product_name,''),'')
        WHERE product_id IS NULL
          AND order_id IS NULL
          AND (SELECT COUNT(*) FROM product_code_aliases a
               WHERE a.product_code=inventory.product_model)=1
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS product_inventory_thresholds (
            product_id INTEGER PRIMARY KEY,
            safe_stock REAL NOT NULL DEFAULT 0 CHECK(safe_stock >= 0),
            warning_buffer REAL NOT NULL DEFAULT 0 CHECK(warning_buffer >= 0),
            updated_by INTEGER,
            updated_by_name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT,
            FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS inventory_allocation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_digest TEXT NOT NULL,
            preview_digest TEXT NOT NULL,
            result_digest TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            compatibility_key TEXT NOT NULL,
            mode TEXT NOT NULL CHECK(mode IN ('fifo','manual','reversal')),
            requested_quantity REAL NOT NULL CHECK(requested_quantity > 0),
            reason TEXT NOT NULL DEFAULT '',
            operator_id INTEGER,
            operator_name TEXT NOT NULL DEFAULT '',
            reversal_of_run_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT,
            FOREIGN KEY(operator_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(reversal_of_run_id) REFERENCES inventory_allocation_runs(id) ON DELETE RESTRICT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS inventory_allocation_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            sequence_no INTEGER NOT NULL,
            inventory_id INTEGER NOT NULL,
            source_order_id INTEGER,
            order_no_snapshot TEXT NOT NULL DEFAULT '',
            lot_no TEXT NOT NULL DEFAULT '',
            serial_no TEXT NOT NULL DEFAULT '',
            location_snapshot TEXT NOT NULL DEFAULT '',
            allocated_quantity REAL NOT NULL CHECK(allocated_quantity > 0),
            movement_id INTEGER NOT NULL,
            balance_before REAL NOT NULL,
            balance_after REAL NOT NULL,
            FOREIGN KEY(run_id) REFERENCES inventory_allocation_runs(id) ON DELETE RESTRICT,
            FOREIGN KEY(inventory_id) REFERENCES inventory(id) ON DELETE RESTRICT,
            FOREIGN KEY(source_order_id) REFERENCES orders(id) ON DELETE RESTRICT,
            FOREIGN KEY(movement_id) REFERENCES inventory_logs(id) ON DELETE RESTRICT,
            UNIQUE(run_id, sequence_no),
            UNIQUE(movement_id)
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_inventory_product_active ON inventory(product_id,deleted_at,quality_status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_inventory_product_location ON inventory(product_id,location,deleted_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_inventory_allocation_product ON inventory_allocation_runs(product_id,created_at)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_allocation_one_reversal ON inventory_allocation_runs(reversal_of_run_id) WHERE reversal_of_run_id IS NOT NULL")
    for table in ("inventory_allocation_runs", "inventory_allocation_items"):
        db.execute(f"DROP TRIGGER IF EXISTS prevent_{table}_update")
        db.execute(f"DROP TRIGGER IF EXISTS prevent_{table}_delete")
        db.execute(f"CREATE TRIGGER prevent_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END")
        db.execute(f"CREATE TRIGGER prevent_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END")
    _merge_inventory_permissions(db)


MIGRATIONS = [(96, "Add product-group inventory views and allocation evidence", m096_inventory_product_views)]
```

- [ ] **Step 4: Register V096 and add feature-flag dependency validation**

In `modules/migration_catalog.py`, import `INVENTORY_PRODUCT_VIEW_MIGRATIONS`, append it to the catalog, and change:

```python
MIGRATION_VERSION_CHAIN = (1, *range(13, 97))
```

Update `tests/test_migrations.py::test_read_only_migration_plan_does_not_modify_database` so `target_version == 96` and pending versions use `range(71, 97)`.

In `modules/config.py`, add:

```python
def load_inventory_product_flags(env=None):
    source = os.environ if env is None else env
    values = {
        key: str(source.get(key, "false")).strip().lower() in {"1", "true", "yes", "on"}
        for key in (
            "INVENTORY_PRODUCT_QUERY_ENABLED",
            "INVENTORY_ALLOCATION_PREVIEW_ENABLED",
            "INVENTORY_CROSS_ORDER_OUTBOUND_ENABLED",
            "INVENTORY_PRODUCT_THRESHOLD_ENABLED",
        )
    }
    if values["INVENTORY_ALLOCATION_PREVIEW_ENABLED"] and not values["INVENTORY_PRODUCT_QUERY_ENABLED"]:
        raise RuntimeError("inventory allocation preview requires product query")
    if values["INVENTORY_CROSS_ORDER_OUTBOUND_ENABLED"] and not (
        values["INVENTORY_PRODUCT_QUERY_ENABLED"]
        and values["INVENTORY_ALLOCATION_PREVIEW_ENABLED"]
    ):
        raise RuntimeError("inventory cross-order outbound requires query and preview")
    if values["INVENTORY_PRODUCT_THRESHOLD_ENABLED"] and not values["INVENTORY_PRODUCT_QUERY_ENABLED"]:
        raise RuntimeError("inventory product threshold requires product query")
    return values
```

Expose the four module constants from the returned mapping. Add tests for every invalid combination and the all-disabled/all-enabled valid combinations.

- [ ] **Step 5: Extend the permission catalog without breaking legacy permissions**

Change the inventory action definition to:

```python
"inventory": (
    "库存",
    [
        "view", "create", "edit", "delete", "export", "inbound", "outbound",
        "allocate", "reserve", "adjust", "audit", "manage_threshold",
    ],
),
```

Add Chinese labels for `inbound`, `outbound`, `allocate`, `reserve`, and `manage_threshold` to `ACTION_LABELS`. Update `PREDEFINED_ROLES['warehouse_keeper']` with the new action permissions while retaining the existing codes.

- [ ] **Step 6: Run migration and permission tests**

Run:

```bash
python -m pytest -q tests/test_inventory_product_migration_v096.py tests/test_migrations.py tests/test_permissions.py
```

Expected: PASS; `LATEST_VERSION == 96`; V096 can be applied twice safely to a migrated database; old permissions remain present.

- [ ] **Step 7: Commit Task 1**

```bash
git add modules/migration_inventory_product_views.py modules/migration_catalog.py modules/config.py modules/permission_catalog.py tests/test_inventory_product_migration_v096.py tests/test_migrations.py tests/test_permissions.py
git commit -m "feat(inventory): add product-view data foundation"
```

---

### Task 2: 实现只读产品聚合、兼容分组和身份异常查询

**Files:**
- Create: `modules/repositories/inventory_product_repository.py`
- Create: `modules/services/inventory_product_query_service.py`
- Modify: `modules/repositories/inventory_repository.py:1-110`
- Modify: `modules/domain/errors.py`
- Modify: `modules/services/inventory_service.py:1-115`
- Modify: `modules/repositories/scan_repository.py:30-50,615-650`
- Modify: `modules/services/scan_helper_service.py:345-365`
- Modify: `modules/services/inventory_auto_inbound_service.py:15-55`
- Modify: `modules/routes/inventory.py:1-150`
- Test: `tests/test_inventory_product_query.py`
- Test: `tests/test_inventory_ledger.py`
- Create: `tests/inventory_product_helpers.py`

**Interfaces:**
- Consumes: V096 columns and `INVENTORY_PRODUCT_QUERY_ENABLED`.
- Produces: `InventoryProductRepository.list_groups`, `get_group_details`, `list_identity_exceptions`; `InventoryProductQueryService.capabilities`, `list_groups`, `get_details`.

- [ ] **Step 1: Write failing query tests**

Create the shared test seed helper first:

```python
from uuid import uuid4


def seed_product_inventory_scenario(
    db,
    *,
    code="P-1001",
    specs=("标准", "标准"),
    quantities=(5, 7),
    reserved=(1, 2),
    frozen=(0, 1),
    safe_stocks=(2, 10),
):
    suffix = uuid4().hex[:8].upper()
    product_code = f"{code}-{suffix}"
    product_id = db.execute(
        "INSERT INTO products(product_code,product_name,model,spec,category) "
        "VALUES(?, '测试产品', '', '', '结构件')",
        (product_code,),
    ).lastrowid
    db.execute(
        "INSERT OR IGNORE INTO product_code_aliases(product_id,product_code,source) "
        "VALUES(?,?,'current')",
        (product_id, product_code),
    )
    order_ids = []
    inventory_ids = []
    for index, specification in enumerate(specs):
        order_no = f"INV-GROUP-{suffix}-{index + 1}"
        order_id = db.execute(
            "INSERT INTO orders(order_no,product_code,product_id,product_name,quantity,status) "
            "VALUES(?,?,?,'测试产品',20,'pending')",
            (order_no, product_code, product_id),
        ).lastrowid
        inventory_id = db.execute(
            "INSERT INTO inventory(product_model,product_name,specification,quantity,reserved,"
            "frozen_quantity,safe_stock,location,unit,order_id,product_id,"
            "product_code_snapshot,product_name_snapshot,quality_status) "
            "VALUES(?, '测试产品', ?, ?, ?, ?, ?, ?, '件', ?, ?, ?, '测试产品', 'qualified')",
            (
                product_code, specification, quantities[index], reserved[index],
                frozen[index], safe_stocks[index], f"A-{index + 1:02d}",
                order_id, product_id, product_code,
            ),
        ).lastrowid
        order_ids.append(order_id)
        inventory_ids.append(inventory_id)
    db.commit()
    return {
        "product_id": product_id,
        "product_code": product_code,
        "order_ids": tuple(order_ids),
        "inventory_ids": tuple(inventory_ids),
    }


def seed_unresolved_inventory(db):
    suffix = uuid4().hex[:8].upper()
    inventory_id = db.execute(
        "INSERT INTO inventory(product_model,product_name,quantity,reserved,frozen_quantity,"
        "safe_stock,location,unit,product_id,product_code_snapshot,product_name_snapshot) "
        "VALUES(?, '无法识别产品', 3, 0, 0, 0, 'U-01', '件', NULL, '', '无法识别产品')",
        (f"UNKNOWN-{suffix}",),
    ).lastrowid
    db.commit()
    return inventory_id
```

Then add tests that seed two orders for one `product_id`, an incompatible specification and one unresolved inventory record:

```python
def test_product_groups_aggregate_by_product_id_and_preserve_order_details(client, auth_headers, db):
    scenario = seed_product_inventory_scenario(db)
    product_id = scenario["product_id"]
    first_inventory, second_inventory = scenario["inventory_ids"]

    response = client.get(
        "/api/inventory/product-groups?limit=50",
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.get_json()
    group = next(item for item in payload["items"] if item["product_id"] == product_id)
    assert group["quantity"] == 12
    assert group["reserved_quantity"] == 3
    assert group["frozen_quantity"] == 1
    assert group["available_quantity"] == 8
    assert group["order_count"] == 2

    details = client.get(
        f"/api/inventory/product-groups/{product_id}/details",
        headers=auth_headers,
    ).get_json()
    assert {item["inventory_id"] for item in details["inventory_items"]} == {
        first_inventory, second_inventory,
    }


def test_product_group_keeps_incompatible_specifications_separate(client, auth_headers, db):
    scenario = seed_product_inventory_scenario(db, specs=("标准", "加厚"))
    product_id = scenario["product_id"]
    payload = client.get(
        f"/api/inventory/product-groups/{product_id}/details",
        headers=auth_headers,
    ).get_json()
    assert len(payload["compatibility_groups"]) == 2
    assert {group["specification"] for group in payload["compatibility_groups"]} == {"标准", "加厚"}


def test_unresolved_identity_is_reported_and_not_silently_aggregated(client, auth_headers, db):
    inventory_id = seed_unresolved_inventory(db)
    payload = client.get(
        "/api/inventory/product-groups?identity_status=unresolved",
        headers=auth_headers,
    ).get_json()
    assert len(payload["identity_exceptions"]) == 1
    assert payload["identity_exceptions"][0]["inventory_id"] == inventory_id
    assert payload["identity_exceptions"][0]["reason"] == "product_identity_unresolved"
```

- [ ] **Step 2: Run query tests and verify RED**

```bash
INVENTORY_PRODUCT_QUERY_ENABLED=true python -m pytest -q tests/test_inventory_product_query.py
```

Expected: FAIL with 404 because the product-group endpoints do not exist.

- [ ] **Step 3: Implement the repository read model**

Create `InventoryProductRepository` with these exact methods and return contracts:

- `count_groups(filters, db=None) -> int`: count distinct resolved active product IDs after applying the supplied filters.
- `list_groups(filters, page, limit, db=None) -> list[sqlite3.Row]`: return one aggregate row per product, ordered by risk then product code.
- `get_product(product_id, db=None) -> sqlite3.Row | None`: return the active canonical product and current code.
- `list_compatibility_groups(product_id, db=None) -> list[dict]`: return deterministic compatibility keys and their quantity totals.
- `list_inventory_details(product_id, compatibility_key="", db=None) -> list[sqlite3.Row]`: return concrete inventory, order, batch, serial and location rows.
- `list_identity_exceptions(limit=100, db=None) -> list[sqlite3.Row]`: return unresolved and conflicting rows with a machine-readable reason.

Use shared SQL expressions instead of duplicating identity rules. Conflicting non-null identities must resolve to `NULL`, not to the first value:

```python
RESOLVED_PRODUCT_ID_SQL = """
CASE
  WHEN i.product_id IS NOT NULL AND o.product_id IS NOT NULL
       AND i.product_id <> o.product_id THEN NULL
  WHEN i.product_id IS NOT NULL AND pca.product_id IS NOT NULL
       AND i.product_id <> pca.product_id THEN NULL
  WHEN o.product_id IS NOT NULL AND pca.product_id IS NOT NULL
       AND o.product_id <> pca.product_id THEN NULL
  ELSE COALESCE(i.product_id,o.product_id,pca.product_id)
END
"""
IDENTITY_REASON_SQL = """
CASE
  WHEN (i.product_id IS NOT NULL AND o.product_id IS NOT NULL AND i.product_id <> o.product_id)
    OR (i.product_id IS NOT NULL AND pca.product_id IS NOT NULL AND i.product_id <> pca.product_id)
    OR (o.product_id IS NOT NULL AND pca.product_id IS NOT NULL AND o.product_id <> pca.product_id)
    THEN 'product_identity_conflict'
  WHEN COALESCE(i.product_id,o.product_id,pca.product_id) IS NULL
    THEN 'product_identity_unresolved'
  ELSE 'resolved'
END
"""
AVAILABLE_SQL = "MAX(i.quantity-COALESCE(i.reserved,0)-COALESCE(i.frozen_quantity,0),0)"
```

The compatibility key must be deterministic and returned with its readable fields:

```python
def compatibility_key(row):
    raw = "|".join((
        str(row["product_id"]),
        (row["specification"] or "").strip(),
        str(row["route_version_id_snapshot"] or 0),
        (row["quality_status"] or "qualified").strip(),
    ))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

Filter active inventory before aggregation. Return unresolved and conflicting identities only in `identity_exceptions`; never include them in a product total.

- [ ] **Step 4: Implement the query service and capabilities**

Create:

```python
class InventoryProductQueryDisabledError(ConflictError):
    code = "inventory_product_query_disabled"

    def to_payload(self):
        payload = super().to_payload()
        payload["action"] = "use_order_inventory_view"
        return payload


class InventoryProductQueryService:
    @staticmethod
    def capabilities():
        return {
            "product_query_enabled": bool(config.INVENTORY_PRODUCT_QUERY_ENABLED),
            "allocation_preview_enabled": bool(config.INVENTORY_ALLOCATION_PREVIEW_ENABLED),
            "cross_order_outbound_enabled": bool(config.INVENTORY_CROSS_ORDER_OUTBOUND_ENABLED),
            "product_threshold_enabled": bool(config.INVENTORY_PRODUCT_THRESHOLD_ENABLED),
        }

    @classmethod
    def list_groups(cls, *, keyword="", low_stock=False, location="", quality_status="", identity_status="", page=1, limit=50):
        if not config.INVENTORY_PRODUCT_QUERY_ENABLED:
            raise InventoryProductQueryDisabledError("产品编码库存视图尚未启用")
        filters = {
            "keyword": (keyword or "").strip(),
            "low_stock": bool(low_stock),
            "location": (location or "").strip(),
            "quality_status": (quality_status or "").strip(),
            "identity_status": (identity_status or "").strip(),
        }
        size = min(max(int(limit), 1), 200)
        total = InventoryProductRepository.count_groups(filters)
        rows = InventoryProductRepository.list_groups(filters, max(int(page), 1), size)
        return {"items": [dict(row) for row in rows], "total": total, "page": max(int(page), 1), "limit": size}
```

`get_details(product_id, compatibility_key="")` must verify the product exists, return canonical code, aliases, compatibility groups, inventory items and identity warnings.

- [ ] **Step 5: Add read-only routes**

Add endpoints protected by `inventory:view`:

```python
@app.route('/api/inventory/capabilities', methods=['GET'])
@check_auth
@check_permission('inventory:view')
def inventory_capabilities():
    return jsonify(InventoryProductQueryService.capabilities())


@app.route('/api/inventory/product-groups', methods=['GET'])
@check_auth
@check_permission('inventory:view')
def inventory_product_groups():
    pagination = parse_pagination(max_limit=200)
    return jsonify(InventoryProductQueryService.list_groups(
        keyword=request.args.get('keyword', ''),
        low_stock=request.args.get('low_stock', '0') == '1',
        location=request.args.get('location', ''),
        quality_status=request.args.get('quality_status', ''),
        identity_status=request.args.get('identity_status', ''),
        page=pagination['page'],
        limit=pagination['limit'],
    ))


@app.route('/api/inventory/product-groups/<int:product_id>/details', methods=['GET'])
@check_auth
@check_permission('inventory:view')
def inventory_product_group_details(product_id):
    return jsonify(InventoryProductQueryService.get_details(
        product_id,
        compatibility_key=request.args.get('compatibility_key', ''),
    ))
```

- [ ] **Step 6: Make every inventory-creation path capture the same product identity**

Add `InventoryProductRepository.resolve_creation_identity(product_code, order_id, db)` with this contract:

```python
{
    "product_id": int | None,
    "product_code_snapshot": str,
    "product_name_snapshot": str,
    "route_version_id_snapshot": int | None,
}
```

If an order product ID and code alias both exist but disagree, raise `ConflictError("订单产品与库存产品编码不一致")`. If neither can resolve, preserve the snapshots and leave `product_id` null so the record appears in the exception list.

Extend `InventoryRepository.insert_txn` to require those four values and write them in the same INSERT as the new inventory record. `InventoryService.create_item` must resolve identity inside its existing transaction before calling `insert_txn`.

Update `ScanRepository.get_order_for_stock` to return stable identity and route version:

```sql
SELECT o.id,o.order_no,o.product_code,o.product_name,o.quantity,p.spec,
       COALESCE(opl.product_id,o.product_id) AS product_id,
       o.route_version_id
FROM orders o
LEFT JOIN order_product_links opl ON opl.order_id=o.id
LEFT JOIN products p ON p.id=COALESCE(opl.product_id,o.product_id)
WHERE o.id=?
```

Extend `ScanRepository.find_or_create_inventory` and `ScanHelperService.find_or_create_inventory` with keyword-only `product_id` and `route_version_id` arguments. The INSERT must write:

```python
(product_code, product_name or product_code, order_id, specification or "",
 product_id, product_code, product_name or product_code, route_version_id)
```

into `product_model`, `product_name`, `order_id`, `specification`, `product_id`, `product_code_snapshot`, `product_name_snapshot`, and `route_version_id_snapshot`. Pass the two values from `InventoryAutoInboundService.auto_inbound_for_item`.

Extend `test_auto_inbound_can_create_separate_inventory_for_same_model_by_order` to assert both rows have the expected stable `product_id`, code/name snapshots and route-version snapshot.

- [ ] **Step 7: Preserve existing order-list behavior while exposing snapshots**

Update the existing repository SELECT to return canonical `product_id`, `product_code_snapshot`, `product_name_snapshot`, `frozen_quantity`, and:

```sql
MAX(i.quantity - COALESCE(i.reserved,0) - COALESCE(i.frozen_quantity,0), 0)
    AS available_quantity
```

Do not change the existing response keys used by `InventoryList.vue`. Add a regression assertion to `tests/test_inventory_ledger.py` proving `/api/inventory` still returns the prior fields and quantities.

- [ ] **Step 8: Run backend query regression**

```bash
INVENTORY_PRODUCT_QUERY_ENABLED=true python -m pytest -q tests/test_inventory_product_query.py tests/test_inventory_ledger.py tests/test_architecture_imports.py
```

Expected: PASS; architecture test confirms routes do not import repositories and services do not execute direct SQL.

- [ ] **Step 9: Commit Task 2**

```bash
git add modules/repositories/inventory_product_repository.py modules/services/inventory_product_query_service.py modules/repositories/inventory_repository.py modules/services/inventory_service.py modules/repositories/scan_repository.py modules/services/scan_helper_service.py modules/services/inventory_auto_inbound_service.py modules/domain/errors.py modules/routes/inventory.py tests/inventory_product_helpers.py tests/test_inventory_product_query.py tests/test_inventory_ledger.py tests/test_architecture_imports.py
git commit -m "feat(inventory): add product-group read model"
```

---

### Task 3: 增加双视图库存工作台和产品详情抽屉

**Files:**
- Create: `frontend/src/composables/inventory/useInventoryProductGroups.js`
- Create: `frontend/src/components/inventory/InventoryViewTabs.vue`
- Create: `frontend/src/components/inventory/ProductInventoryTable.vue`
- Create: `frontend/src/components/inventory/ProductInventoryDrawer.vue`
- Modify: `frontend/src/lib/api/inventory.js:1-22`
- Modify: `frontend/src/views/InventoryList.vue:1-281`
- Modify: `frontend/src/composables/useInventory.js:1-381`
- Test: `frontend/tests/unit/inventory-product-api.spec.js`
- Test: `frontend/tests/unit/useInventoryProductGroups.spec.js`
- Test: `frontend/tests/unit/ProductInventoryWorkbench.spec.js`
- Test: `frontend/tests/unit/inventory-composable.spec.js`

**Interfaces:**
- Consumes: Task 2 capabilities, product-group list and details endpoints.
- Produces: `productInventoryManager`; view tabs; read-only product table and detail drawer.

- [ ] **Step 1: Write failing API facade tests**

Create `frontend/tests/unit/inventory-product-api.spec.js`:

```javascript
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api.js'

function response(payload) {
  return { status: 200, ok: true, text: vi.fn(async () => JSON.stringify(payload)) }
}

describe('inventory product API facade', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('serializes group filters and detail compatibility keys', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ items: [] }))
    await api.domains.inventory.listProductGroups({ keyword: 'SB121', page: 2, limit: 50 })
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/inventory/product-groups?keyword=SB121&page=2&limit=50',
      { method: 'GET', headers: {}, credentials: 'same-origin' },
    )
    await api.domains.inventory.productGroupDetails(7, { compatibility_key: 'abc' })
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/inventory/product-groups/7/details?compatibility_key=abc',
      { method: 'GET', headers: {}, credentials: 'same-origin' },
    )
  })
})
```

- [ ] **Step 2: Run facade test and verify RED**

```bash
npx vitest run --config vitest.config.js frontend/tests/unit/inventory-product-api.spec.js
```

Expected: FAIL because the facade methods do not exist.

- [ ] **Step 3: Add exact facade methods**

Extend `inventoryApi`:

```javascript
inventoryCapabilities: () => request('GET', '/api/inventory/capabilities'),
listProductGroups: params => request('GET', '/api/inventory/product-groups' + buildQuery(params)),
productGroupDetails: (productId, params) => request(
  'GET', `/api/inventory/product-groups/${productId}/details` + buildQuery(params),
),
productGroupExportUrl: params => '/api/inventory/product-groups/export' + buildQuery(params),
```

Add a facade test for `productGroupExportUrl({ detail: 1, keyword: 'SB121' })` and assert the result is `/api/inventory/product-groups/export?detail=1&keyword=SB121`.

- [ ] **Step 4: Write composable tests for tabs, saved filters, stale detail responses and feature gating**

Test the following public state:

```javascript
expect(manager.viewMode.value).toBe('order')
manager.setViewMode('product')
expect(localStorage.getItem('inventory-workbench:v1:view')).toBe('product')

await manager.loadGroups()
expect(mocks.listProductGroups).toHaveBeenCalledWith(expect.objectContaining({ page: 1, limit: 50 }))

const first = manager.openProduct({ product_id: 1 })
await manager.openProduct({ product_id: 2 })
resolveFirst({ product: { id: 1 }, compatibility_groups: [] })
await first
expect(manager.selectedProduct.value.id).toBe(2)
```

- [ ] **Step 5: Implement `useInventoryProductGroups`**

Expose grouped state instead of adding more flat refs to `useInventory.js`:

```javascript
return {
  state: {
    capabilities, viewMode, groups, total, page, limit, filters,
    loading, error, selectedProduct, selectedDetails, drawerOpen,
  },
  actions: {
    loadCapabilities, setViewMode, loadGroups, resetFilters,
    openProduct, selectCompatibilityGroup, closeDrawer,
  },
}
```

Use `localStorage` keys beginning with `inventory-workbench:v1:`. Guard detail requests with a monotonically increasing request number so stale responses cannot replace the current selection.

- [ ] **Step 6: Build the read-only components**

`InventoryViewTabs.vue` emits `update:modelValue`. `ProductInventoryTable.vue` emits `open-product`. `ProductInventoryDrawer.vue` emits `close` and `select-compatibility-group`.

The product table must render these columns:

```text
产品编码 | 产品名称/规格 | 总库存 | 预留 | 冻结 | 可用 | 订单数 | 批次数 | 库位数 | 预警 | 操作
```

The drawer must show compatibility groups first, then order/batch/location details. Identity exceptions use text and an icon, not color alone.

- [ ] **Step 7: Integrate without replacing the order view**

In `InventoryList.vue`, mount the tabs above the current card. Keep the existing order table under `v-if="viewMode === 'order'"`; mount `ProductInventoryTable` under `v-else`. Mount the detail drawer with `Teleport to="body"`.

Do not move existing order CRUD, log, turnover or count behavior in this task.

- [ ] **Step 8: Run focused frontend tests and checks**

```bash
npx vitest run --config vitest.config.js \
  frontend/tests/unit/inventory-product-api.spec.js \
  frontend/tests/unit/useInventoryProductGroups.spec.js \
  frontend/tests/unit/ProductInventoryWorkbench.spec.js \
  frontend/tests/unit/inventory-composable.spec.js
npm run check:api
npm run check:imports
```

Expected: all tests PASS; API facade and import-cycle checks exit 0.

- [ ] **Step 9: Commit Task 3**

```bash
git add frontend/src/lib/api/inventory.js frontend/src/composables/inventory/useInventoryProductGroups.js frontend/src/components/inventory/InventoryViewTabs.vue frontend/src/components/inventory/ProductInventoryTable.vue frontend/src/components/inventory/ProductInventoryDrawer.vue frontend/src/views/InventoryList.vue frontend/src/composables/useInventory.js frontend/tests/unit/inventory-product-api.spec.js frontend/tests/unit/useInventoryProductGroups.spec.js frontend/tests/unit/ProductInventoryWorkbench.spec.js frontend/tests/unit/inventory-composable.spec.js
git commit -m "feat(inventory): add dual-view inventory workbench"
```

---

### Task 4: 实现纯来源分配算法和只读分配预览

**Files:**
- Create: `modules/domain/inventory_allocation.py`
- Modify: `modules/domain/errors.py`
- Modify: `modules/repositories/inventory_product_repository.py`
- Create: `modules/services/inventory_allocation_service.py`
- Modify: `modules/schemas/inventory.py:1-51`
- Modify: `modules/routes/inventory.py`
- Test: `tests/test_inventory_source_allocator.py`
- Test: `tests/test_inventory_product_query.py`

**Interfaces:**
- Consumes: Task 2 product identities/details and `INVENTORY_ALLOCATION_PREVIEW_ENABLED`.
- Produces: immutable `InventoryCandidate`, `AllocationItem`, `AllocationResult`; `allocate_inventory_sources`; preview endpoint and digest.

- [ ] **Step 1: Write pure allocation tests**

Create deterministic Decimal-based tests:

```python
from decimal import Decimal

import pytest

from modules.domain.inventory_allocation import (
    AllocationShortage,
    InventoryCandidate,
    allocate_inventory_sources,
)


def candidate(inventory_id, quantity, received_at, *, order_id=None, lot_no="", manual_rank=None):
    return InventoryCandidate(
        inventory_id=inventory_id,
        order_id=order_id,
        order_no=f"O-{order_id or 0}",
        available_quantity=Decimal(str(quantity)),
        received_at=received_at,
        lot_no=lot_no,
        serial_no="",
        location="A-01",
        compatibility_key="group-a",
        manual_rank=manual_rank,
    )


def test_fifo_uses_oldest_candidates_and_preserves_quantity():
    result = allocate_inventory_sources(
        [candidate(2, 4, "2026-09-02"), candidate(1, 3, "2026-09-01")],
        Decimal("5"),
        mode="fifo",
        compatibility_key="group-a",
    )
    assert [(item.inventory_id, item.quantity) for item in result.items] == [
        (1, Decimal("3")), (2, Decimal("2")),
    ]
    assert sum(item.quantity for item in result.items) == Decimal("5")


def test_manual_mode_respects_selected_order_and_rank():
    result = allocate_inventory_sources(
        [candidate(1, 4, "2026-09-01", order_id=10, manual_rank=2),
         candidate(2, 4, "2026-09-02", order_id=11, manual_rank=1)],
        Decimal("3"), mode="manual", compatibility_key="group-a",
        selected_inventory_ids=(2,),
    )
    assert [(item.inventory_id, item.quantity) for item in result.items] == [(2, Decimal("3"))]


def test_shortage_is_explicit_and_does_not_return_partial_success():
    with pytest.raises(AllocationShortage) as exc:
        allocate_inventory_sources(
            [candidate(1, 2, "2026-09-01")], Decimal("5"),
            mode="fifo", compatibility_key="group-a",
        )
    assert exc.value.available == Decimal("2")
    assert exc.value.shortage == Decimal("3")
```

Also test incompatible keys, non-positive quantities, deterministic tie breaking, lot restriction and one-unit serial candidates.

- [ ] **Step 2: Run allocator tests and verify RED**

```bash
python -m pytest -q tests/test_inventory_source_allocator.py
```

Expected: FAIL because the domain module does not exist.

- [ ] **Step 3: Implement immutable domain types and allocation function**

Create:

```python
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class InventoryCandidate:
    inventory_id: int
    order_id: int | None
    order_no: str
    available_quantity: Decimal
    received_at: str
    lot_no: str
    serial_no: str
    location: str
    compatibility_key: str
    manual_rank: int | None = None


@dataclass(frozen=True)
class AllocationItem:
    inventory_id: int
    order_id: int | None
    order_no: str
    lot_no: str
    serial_no: str
    location: str
    quantity: Decimal


@dataclass(frozen=True)
class AllocationResult:
    requested_quantity: Decimal
    available_quantity: Decimal
    items: tuple[AllocationItem, ...]


class AllocationShortage(ValueError):
    def __init__(self, requested, available):
        self.requested = requested
        self.available = available
        self.shortage = requested - available
        super().__init__(f"可用库存不足，缺少 {self.shortage}")
```

`allocate_inventory_sources` must filter the requested compatibility key, apply manual IDs only in manual mode, sort FIFO by `(received_at, lot_no, location, inventory_id, serial_no)`, allocate until exact quantity is reached, and raise `AllocationShortage` before returning a partial result.

- [ ] **Step 4: Add candidate query with batch and serial balances**

Add `list_allocation_candidates(product_id, compatibility_key, filters, db=None)` to `InventoryProductRepository`.

The query must:

- exclude deleted, frozen, non-qualified and zero-available inventory;
- compute lot balances from `inventory_logs.qty_delta`;
- expose individual in-stock serial candidates;
- expose an untracked candidate for `inventory.quantity - tracked_lot_balance` when positive;
- include `inventory.updated_at` in the preview digest source;
- never return rows from another compatibility key.

- [ ] **Step 5: Add preview schema and service**

Add `inventory_allocation_preview`:

```python
{
    "type": "object",
    "additionalProperties": False,
    "required": ["quantity", "compatibility_key", "mode"],
    "properties": {
        "quantity": {"type": "number", "exclusiveMinimum": 0},
        "compatibility_key": {"type": "string", "minLength": 64, "maxLength": 64},
        "mode": {"type": "string", "enum": ["fifo", "manual"]},
        "inventory_ids": {"type": "array", "items": {"type": "integer", "minimum": 1}, "uniqueItems": True},
        "order_ids": {"type": "array", "items": {"type": "integer", "minimum": 1}, "uniqueItems": True},
        "lot_nos": {"type": "array", "items": {"type": "string", "maxLength": 128}, "uniqueItems": True},
        "locations": {"type": "array", "items": {"type": "string", "maxLength": 128}, "uniqueItems": True},
        "reason": {"type": "string", "maxLength": 512},
    },
}
```

`InventoryAllocationService.preview` must return `requested_quantity`, `available_quantity`, `shortage_quantity`, `items`, and `preview_digest`. The digest is SHA-256 over canonical JSON containing product ID, compatibility key, request, candidate identity, candidate balances and `updated_at` values.

Add explicit HTTP-facing errors:

```python
class InventoryAllocationPreviewDisabledError(ConflictError):
    code = "inventory_allocation_preview_disabled"

    def to_payload(self):
        payload = super().to_payload()
        payload["action"] = "enable_inventory_allocation_preview"
        return payload


class InventoryAllocationShortageError(ConflictError):
    code = "inventory_allocation_shortage"

    def to_payload(self):
        payload = super().to_payload()
        payload["action"] = "reduce_quantity_or_change_sources"
        return payload
```

Map internal `AllocationShortage` to `InventoryAllocationShortageError` with `details={"requested": str(exc.requested), "available": str(exc.available), "shortage": str(exc.shortage)}`. Manual mode without `inventory:allocate`, without selected sources, or without a reason raises `AuthorizationError` or `ValidationError` with a specific message.

- [ ] **Step 6: Add preview route**

```python
@app.route('/api/inventory/product-groups/<int:product_id>/allocation-preview', methods=['POST'])
@check_auth
@check_permission('inventory:outbound')
@validate_json('inventory_allocation_preview')
def preview_inventory_product_allocation(product_id):
    result = InventoryAllocationService.preview(
        product_id,
        get_json_body(),
        can_allocate=has_permission(g.current_user, 'inventory:allocate'),
    )
    return jsonify(result)
```

Import the existing `has_permission` helper from `modules.route_decorators`; do not invoke a decorator as a normal function.

- [ ] **Step 7: Run allocator and preview tests**

```bash
INVENTORY_PRODUCT_QUERY_ENABLED=true \
INVENTORY_ALLOCATION_PREVIEW_ENABLED=true \
python -m pytest -q tests/test_inventory_source_allocator.py tests/test_inventory_product_query.py
```

Expected: PASS; preview does not change `inventory`, `inventory_logs`, allocation tables or audit tables.

- [ ] **Step 8: Commit Task 4**

```bash
git add modules/domain/inventory_allocation.py modules/domain/errors.py modules/repositories/inventory_product_repository.py modules/services/inventory_allocation_service.py modules/schemas/inventory.py modules/routes/inventory.py tests/test_inventory_source_allocator.py tests/test_inventory_product_query.py
git commit -m "feat(inventory): add source allocation preview"
```

---

### Task 5: 实现单事务正式跨订单出库、幂等和审计证据

**Files:**
- Create: `modules/repositories/inventory_allocation_repository.py`
- Modify: `modules/services/inventory_allocation_service.py`
- Modify: `modules/domain/errors.py`
- Modify: `modules/services/inventory_posting_service.py:1-155`
- Modify: `modules/repositories/inventory_repository.py:119-170`
- Modify: `modules/schemas/inventory.py`
- Modify: `modules/routes/inventory.py`
- Modify: `modules/audit_action_catalog.py`
- Test: `tests/test_inventory_group_outbound.py`
- Test: `tests/test_inventory_ledger.py`

**Interfaces:**
- Consumes: Task 4 preview digest and allocation result; existing `InventoryPostingService.post` with the caller-owned transaction passed as `db=txn`.
- Produces: `InventoryAllocationService.outbound`; immutable allocation run/items; transactional audit outbox event.

- [ ] **Step 1: Write failing transactional tests**

Cover success, replay, digest conflict, stale preview, insufficient stock, forced evidence failure and immutable reversal:

```python
from inventory_product_helpers import seed_product_inventory_scenario


def seed_and_preview(client, auth_headers, db, quantity=5):
    scenario = seed_product_inventory_scenario(
        db,
        specs=("标准", "标准"),
        quantities=(3, 4),
        reserved=(0, 0),
        frozen=(0, 0),
        safe_stocks=(0, 0),
    )
    details = client.get(
        f"/api/inventory/product-groups/{scenario['product_id']}/details",
        headers=auth_headers,
    ).get_json()
    compatibility_key = details["compatibility_groups"][0]["compatibility_key"]
    preview_response = client.post(
        f"/api/inventory/product-groups/{scenario['product_id']}/allocation-preview",
        headers=auth_headers,
        json={
            "quantity": quantity,
            "compatibility_key": compatibility_key,
            "mode": "fifo",
            "reason": "测试分配",
        },
    )
    assert preview_response.status_code == 200
    preview = preview_response.get_json()
    preview["compatibility_key"] = compatibility_key
    return scenario["product_id"], preview


def seed_outbound_command(client, auth_headers, db, *, key="inventory-group-outbound-1"):
    product_id, preview = seed_and_preview(client, auth_headers, db, quantity=5)
    return product_id, {
        "quantity": 5,
        "compatibility_key": preview["compatibility_key"],
        "mode": "fifo",
        "preview_digest": preview["preview_digest"],
        "idempotency_key": key,
        "reason": "生产领用",
    }


def snapshot_inventory_and_logs(db):
    balances = tuple(
        tuple(row) for row in db.execute(
            "SELECT id,quantity,reserved,frozen_quantity FROM inventory ORDER BY id"
        ).fetchall()
    )
    logs = tuple(
        tuple(row) for row in db.execute(
            "SELECT id,inventory_id,qty_delta,idempotency_key FROM inventory_logs ORDER BY id"
        ).fetchall()
    )
    return balances, logs


def test_group_outbound_posts_each_source_and_saves_one_immutable_run(client, auth_headers, db):
    product_id, preview = seed_and_preview(client, auth_headers, db, quantity=5)
    response = client.post(
        f"/api/inventory/product-groups/{product_id}/outbound",
        headers=auth_headers,
        json={
            "quantity": 5,
            "compatibility_key": preview["compatibility_key"],
            "mode": "fifo",
            "preview_digest": preview["preview_digest"],
            "idempotency_key": "inventory-group-outbound-1",
            "reason": "生产领用",
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert sum(item["allocated_quantity"] for item in body["items"]) == 5
    assert db.execute("SELECT COUNT(*) FROM inventory_allocation_runs").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM inventory_allocation_items").fetchone()[0] == len(body["items"])


def test_group_outbound_idempotent_replay_does_not_double_decrement(client, auth_headers, db):
    product_id, command = seed_outbound_command(client, auth_headers, db)
    first = client.post(f"/api/inventory/product-groups/{product_id}/outbound", headers=auth_headers, json=command)
    quantities = tuple(row[0] for row in db.execute("SELECT quantity FROM inventory ORDER BY id"))
    second = client.post(f"/api/inventory/product-groups/{product_id}/outbound", headers=auth_headers, json=command)
    assert second.get_json() == first.get_json()
    assert tuple(row[0] for row in db.execute("SELECT quantity FROM inventory ORDER BY id")) == quantities


def test_group_outbound_rolls_back_balances_when_evidence_insert_fails(client, auth_headers, db, monkeypatch):
    product_id, command = seed_outbound_command(
        client,
        auth_headers,
        db,
        key="inventory-group-outbound-failure",
    )
    before = snapshot_inventory_and_logs(db)
    monkeypatch.setattr(
        InventoryAllocationRepository,
        "insert_items_txn",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("evidence failed")),
    )
    response = client.post(
        f"/api/inventory/product-groups/{product_id}/outbound",
        headers=auth_headers,
        json=command,
    )
    assert response.status_code == 500
    assert snapshot_inventory_and_logs(db) == before
    assert db.execute("SELECT COUNT(*) FROM inventory_allocation_runs").fetchone()[0] == 0


def test_group_outbound_reversal_restores_exact_sources_without_deleting_history(client, auth_headers, db):
    product_id, command = seed_outbound_command(
        client, auth_headers, db, key="inventory-group-outbound-reverse-source",
    )
    before = snapshot_inventory_and_logs(db)[0]
    outbound = client.post(
        f"/api/inventory/product-groups/{product_id}/outbound",
        headers=auth_headers,
        json=command,
    ).get_json()
    response = client.post(
        f"/api/inventory/allocation-runs/{outbound['run']['id']}/reverse",
        headers=auth_headers,
        json={
            "idempotency_key": "inventory-group-outbound-reversal-1",
            "reason": "领用单撤销",
        },
    )
    assert response.status_code == 200
    assert snapshot_inventory_and_logs(db)[0] == before
    reversal = response.get_json()["run"]
    assert reversal["reversal_of_run_id"] == outbound["run"]["id"]
    original_log_count = db.execute(
        "SELECT COUNT(*) FROM inventory_logs WHERE source_id=?",
        (outbound["run"]["id"],),
    ).fetchone()[0]
    assert original_log_count == len(outbound["items"])
```

- [ ] **Step 2: Run transactional tests and verify RED**

```bash
INVENTORY_PRODUCT_QUERY_ENABLED=true \
INVENTORY_ALLOCATION_PREVIEW_ENABLED=true \
INVENTORY_CROSS_ORDER_OUTBOUND_ENABLED=true \
python -m pytest -q tests/test_inventory_group_outbound.py
```

Expected: FAIL because the endpoint and repository do not exist.

- [ ] **Step 3: Implement allocation evidence repository**

Create these exact methods and contracts:

- `find_run_by_idempotency_key(idempotency_key, db=None) -> sqlite3.Row | None`: query the immutable run by its unique key.
- `get_run_result(run_id, db=None) -> dict`: join the run and ordered items and rebuild the public response.
- `insert_run_txn(*, idempotency_key, request_digest, preview_digest, result_digest, product_id, compatibility_key, mode, requested_quantity, reason, operator_id, operator_name, reversal_of_run_id=None, db) -> int`: insert one immutable run and return its ID.
- `insert_items_txn(run_id, items, movements, db) -> None`: insert one item per movement and verify list lengths and quantities before writing.
- `find_reversal_for_run(run_id, db=None) -> sqlite3.Row | None`: enforce one immutable reversal per original run.
- `list_runs_by_product(product_id, page, limit, db=None) -> tuple[list[dict], int]`: return immutable outbound and reversal history ordered newest first.
- `get_threshold(product_id, db=None) -> sqlite3.Row | None`: return the product threshold.
- `upsert_threshold_txn(product_id, safe_stock, warning_buffer, actor_id, actor_name, db) -> None`: insert or replace the product threshold and actor snapshot.

`get_run_result` must reconstruct the same public response used by the first request so replay is stable.

- [ ] **Step 4: Add the outbound command schema**

Extend the preview schema with required `preview_digest`, `idempotency_key` and `reason`:

```python
"preview_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
"idempotency_key": {"type": "string", "minLength": 8, "maxLength": 128},
"reason": {"type": "string", "minLength": 1, "maxLength": 512},
```

Name the schema `inventory_group_outbound`.

Add `inventory_group_outbound_reversal`:

```python
{
    "type": "object",
    "additionalProperties": False,
    "required": ["idempotency_key", "reason"],
    "properties": {
        "idempotency_key": {"type": "string", "minLength": 8, "maxLength": 128},
        "reason": {"type": "string", "minLength": 1, "maxLength": 512},
    },
}
```

- [ ] **Step 5: Implement the single-transaction command**

First harden the shared stock-update predicates so frozen stock cannot be consumed or reserved:

```python
@staticmethod
def decrease_stock_if_available_txn(item_id, quantity, db):
    return db.execute(
        "UPDATE inventory SET quantity=quantity-?,updated_at=datetime('now','localtime') "
        "WHERE id=? AND quantity-reserved-COALESCE(frozen_quantity,0)>=? "
        "AND deleted_at IS NULL",
        (quantity, item_id, quantity),
    )


@staticmethod
def reserve_stock_txn(item_id, quantity, db):
    return db.execute(
        "UPDATE inventory SET reserved=reserved+?,updated_at=datetime('now','localtime') "
        "WHERE id=? AND quantity-reserved-COALESCE(frozen_quantity,0)>=? "
        "AND deleted_at IS NULL",
        (quantity, item_id, quantity),
    )
```

For `consume_stock_txn`, require both `reserved >= reserved_quantity` and `quantity - frozen_quantity >= quantity`. Include `frozen_quantity` in `get_item_quantity`, and calculate conflict messages from `quantity - reserved - frozen_quantity`.

Add write-gate and stale-preview errors:

```python
class InventoryCrossOrderOutboundDisabledError(ConflictError):
    code = "inventory_cross_order_outbound_disabled"

    def to_payload(self):
        payload = super().to_payload()
        payload["action"] = "use_single_inventory_outbound"
        return payload


class InventoryAllocationPreviewStaleError(ConflictError):
    code = "inventory_allocation_preview_stale"

    def to_payload(self):
        payload = super().to_payload()
        payload["action"] = "refresh_inventory_allocation_preview"
        return payload
```

`outbound` must reject immediately with `InventoryCrossOrderOutboundDisabledError` when the formal-write flag is false. Replace the generic stale-preview conflict in the transaction sequence with `InventoryAllocationPreviewStaleError`.

The public method signature is:

```python
@classmethod
def outbound(cls, product_id, data, *, operator_id, operator_name, can_allocate):
```

Implement this transaction sequence exactly:

```python
request_digest = cls.request_digest(product_id, data)
with BaseService.transaction() as txn:
    existing = InventoryAllocationRepository.find_run_by_idempotency_key(
        data["idempotency_key"], db=txn,
    )
    if existing:
        if existing["request_digest"] != request_digest:
            raise ConflictError("幂等键已用于不同的库存分配请求")
        return InventoryAllocationRepository.get_run_result(existing["id"], db=txn)

    preview = cls._calculate_preview(product_id, data, can_allocate=can_allocate, db=txn)
    if preview["preview_digest"] != data["preview_digest"]:
        raise ConflictError("库存已经变化，请重新生成分配预览")

    result_digest = cls.result_digest(preview["items"])
    run_id = InventoryAllocationRepository.insert_run_txn(
        idempotency_key=data["idempotency_key"],
        request_digest=request_digest,
        preview_digest=preview["preview_digest"],
        result_digest=result_digest,
        product_id=product_id,
        compatibility_key=data["compatibility_key"],
        mode=data["mode"],
        requested_quantity=data["quantity"],
        reason=data["reason"],
        operator_id=operator_id,
        operator_name=operator_name,
        db=txn,
    )
    movements = []
    for sequence_no, item in enumerate(preview["items"], 1):
        movements.append(InventoryPostingService.post(
            item["inventory_id"],
            -item["allocated_quantity"],
            "out",
            order_id=item["order_id"],
            order_no=item["order_no"],
            remark=data["reason"],
            operator_id=operator_id,
            operator_name=operator_name,
            lot_no=item["lot_no"],
            serial_no=item["serial_no"],
            source_type="product_group_allocation",
            source_id=run_id,
            idempotency_key=f"{data['idempotency_key']}:{sequence_no}",
            db=txn,
        ))
    InventoryAllocationRepository.insert_items_txn(run_id, preview["items"], movements, txn)
    AuditLogRepository.enqueue_event_txn(
        operator_id,
        "inventory_group_outbound",
        "inventory_allocation_run",
        run_id,
        {"product_id": product_id, "mode": data["mode"], "quantity": data["quantity"], "reason": data["reason"]},
        db=txn,
    )
    return InventoryAllocationRepository.get_run_result(run_id, db=txn)
```

Register `inventory_group_outbound` in the audit action catalog with mandatory evidence metadata.

Implement `reverse_outbound(run_id, data, *, operator_id, operator_name)` in the same service. In one transaction it must:

1. replay an existing reversal when its idempotency key and request digest match;
2. reject a different command using the same key;
3. reject an original run that already has a reversal;
4. insert a new allocation run with `mode='reversal'` and `reversal_of_run_id=run_id`;
5. post one positive `return` movement per original allocation item through `InventoryPostingService.post`, with `reversal_of_id` equal to the original movement ID;
6. save reversal allocation items and an `inventory_group_outbound_reversal` audit outbox event;
7. commit all evidence together or roll it all back.

- [ ] **Step 6: Add formal outbound route**

Protect it with `inventory:outbound`; service enforces `inventory:allocate` for manual mode:

```python
@app.route('/api/inventory/product-groups/<int:product_id>/outbound', methods=['POST'])
@check_auth
@check_permission('inventory:outbound')
@validate_json('inventory_group_outbound')
def inventory_product_group_outbound(product_id):
    return jsonify(InventoryAllocationService.outbound(
        product_id,
        get_json_body(),
        operator_id=g.current_user['id'],
        operator_name=g.current_user['name'],
        can_allocate=has_permission(g.current_user, 'inventory:allocate'),
    ))


@app.route('/api/inventory/allocation-runs/<int:run_id>/reverse', methods=['POST'])
@check_auth
@check_permission('inventory:adjust')
@validate_json('inventory_group_outbound_reversal')
def reverse_inventory_product_group_outbound(run_id):
    return jsonify(InventoryAllocationService.reverse_outbound(
        run_id,
        get_json_body(),
        operator_id=g.current_user['id'],
        operator_name=g.current_user['name'],
    ))


@app.route('/api/inventory/product-groups/<int:product_id>/allocation-runs', methods=['GET'])
@check_auth
@check_permission('inventory:audit')
def list_inventory_product_allocation_runs(product_id):
    pagination = parse_pagination(max_limit=100)
    return jsonify(InventoryAllocationService.list_runs(
        product_id,
        page=pagination['page'],
        limit=pagination['limit'],
    ))
```

- [ ] **Step 7: Run transactional and legacy ledger tests**

```bash
INVENTORY_PRODUCT_QUERY_ENABLED=true \
INVENTORY_ALLOCATION_PREVIEW_ENABLED=true \
INVENTORY_CROSS_ORDER_OUTBOUND_ENABLED=true \
python -m pytest -q tests/test_inventory_group_outbound.py tests/test_inventory_ledger.py tests/test_audit_outbox_smoke.py
```

Expected: PASS; forced failures leave inventory, logs, run/items and audit outbox unchanged.

- [ ] **Step 8: Commit Task 5**

```bash
git add modules/repositories/inventory_allocation_repository.py modules/services/inventory_allocation_service.py modules/services/inventory_posting_service.py modules/repositories/inventory_repository.py modules/domain/errors.py modules/schemas/inventory.py modules/routes/inventory.py modules/audit_action_catalog.py tests/test_inventory_group_outbound.py tests/test_inventory_ledger.py
git commit -m "feat(inventory): add transactional grouped outbound"
```

---

### Task 6: 增加产品级安全库存、双层预警、权限和导出

**Files:**
- Create: `modules/services/inventory_product_export_service.py`
- Modify: `modules/repositories/inventory_allocation_repository.py`
- Modify: `modules/services/inventory_product_query_service.py`
- Modify: `modules/schemas/inventory.py`
- Modify: `modules/routes/inventory.py`
- Modify: `modules/export_utils.py`
- Test: `tests/test_inventory_product_export.py`
- Test: `tests/test_inventory_product_query.py`

**Interfaces:**
- Consumes: Task 2 aggregation and Task 1 product thresholds.
- Produces: product threshold command; product summary/detail Excel export; product and order risk values.

- [ ] **Step 1: Write failing threshold and export tests**

```python
from inventory_product_helpers import seed_product_inventory_scenario


def seed_product_group(db, *, available, order_safe_stocks):
    scenario = seed_product_inventory_scenario(
        db,
        specs=("标准", "标准"),
        quantities=(5, 6),
        reserved=(1, 2),
        frozen=(0, 0),
        safe_stocks=order_safe_stocks,
    )
    assert sum((5 - 1, 6 - 2)) == available
    return scenario["product_id"]


def get_group(client, auth_headers, product_id):
    response = client.get(
        "/api/inventory/product-groups?limit=200",
        headers=auth_headers,
    )
    assert response.status_code == 200
    return next(
        item for item in response.get_json()["items"]
        if item["product_id"] == product_id
    )


def test_product_threshold_is_independent_from_order_threshold(client, auth_headers, db):
    product_id = seed_product_group(db, available=8, order_safe_stocks=(2, 10))
    response = client.put(
        f"/api/inventory/product-groups/{product_id}/threshold",
        headers=auth_headers,
        json={"safe_stock": 12, "warning_buffer": 3},
    )
    assert response.status_code == 200
    group = get_group(client, auth_headers, product_id)
    assert group["product_alert_level"] == "low"
    assert group["at_risk_order_count"] == 1


def test_product_export_supports_summary_and_expanded_detail(client, auth_headers, db):
    seed_product_group(db, available=8, order_safe_stocks=(2, 10))
    summary = client.get(
        "/api/inventory/product-groups/export?detail=0",
        headers=auth_headers,
    )
    expanded = client.get(
        "/api/inventory/product-groups/export?detail=1",
        headers=auth_headers,
    )
    assert summary.status_code == 200
    assert expanded.status_code == 200
    assert len(expanded.data) > len(summary.data)
```

- [ ] **Step 2: Run tests and verify RED**

```bash
INVENTORY_PRODUCT_QUERY_ENABLED=true INVENTORY_PRODUCT_THRESHOLD_ENABLED=true \
python -m pytest -q tests/test_inventory_product_export.py tests/test_inventory_product_query.py
```

Expected: FAIL because threshold and export endpoints do not exist.

- [ ] **Step 3: Add threshold schema and command**

```python
'inventory_product_threshold': {
    'type': 'object',
    'additionalProperties': False,
    'required': ['safe_stock', 'warning_buffer'],
    'properties': {
        'safe_stock': {'type': 'number', 'minimum': 0},
        'warning_buffer': {'type': 'number', 'minimum': 0},
    },
}
```

Add this exact service method contract to `InventoryProductQueryService`:

```python
@classmethod
def update_threshold(cls, product_id, data, *, actor_id, actor_name) -> dict:
    """Validate the product, upsert its threshold in one transaction, enqueue audit, and return the saved threshold."""
```

It must check `INVENTORY_PRODUCT_THRESHOLD_ENABLED`, verify the product exists, upsert in one transaction and write a transactional audit outbox event named `inventory_product_threshold_update`. The route returns `{ "product_id": ..., "safe_stock": ..., "warning_buffer": ... }`.

- [ ] **Step 4: Calculate double-level risk explicitly**

Each product-group response must expose:

```python
{
    "product_safe_stock": float(threshold["safe_stock"] or 0),
    "product_warning_buffer": float(threshold["warning_buffer"] or 0),
    "product_alert_level": "normal" | "attention" | "low" | "out_of_stock",
    "at_risk_order_count": int(row["at_risk_order_count"] or 0),
    "total_shortage_quantity": float(row["total_shortage_quantity"] or 0),
    "earliest_at_risk_order_no": row["earliest_at_risk_order_no"] or "",
}
```

Order risk uses each inventory row’s `safe_stock`; product risk uses `product_inventory_thresholds`. Do not offset an order’s reserved or incompatible stock using unrelated product stock.

- [ ] **Step 5: Implement summary and expanded export**

`InventoryProductExportService.export(filters, include_details=False)` creates:

- sheet `产品库存汇总` with canonical code, aliases, totals, counts and risk;
- optional sheet `订单批次明细` with product code, compatibility group, order, batch, serial, location, quality status, quantity, reserved, frozen and available.

Reuse `style_header`, `auto_width`, `THIN_BORDER`, and `CELL_ALIGN`. Apply the same filters and permissions as the list endpoint.

- [ ] **Step 6: Add routes**

```python
@app.route('/api/inventory/product-groups/<int:product_id>/threshold', methods=['PUT'])
@check_auth
@check_permission('inventory:manage_threshold')
@validate_json('inventory_product_threshold')
def update_inventory_product_threshold(product_id):
    return jsonify(InventoryProductQueryService.update_threshold(
        product_id,
        get_json_body(),
        actor_id=g.current_user['id'],
        actor_name=g.current_user['name'],
    ))

@app.route('/api/inventory/product-groups/export', methods=['GET'])
@check_auth
@check_permission('inventory:export')
def export_inventory_product_groups():
    output = InventoryProductExportService.export(
        keyword=request.args.get('keyword', ''),
        low_stock=request.args.get('low_stock', '0') == '1',
        location=request.args.get('location', ''),
        quality_status=request.args.get('quality_status', ''),
        include_details=request.args.get('detail', '0') == '1',
    )
    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'inventory_products_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx',
    )
```

- [ ] **Step 7: Run export, permission and query tests**

```bash
INVENTORY_PRODUCT_QUERY_ENABLED=true INVENTORY_PRODUCT_THRESHOLD_ENABLED=true \
python -m pytest -q tests/test_inventory_product_export.py tests/test_inventory_product_query.py tests/test_permissions.py
```

Expected: PASS; users without export or threshold permission receive 403; workbook quantities match API totals.

- [ ] **Step 8: Commit Task 6**

```bash
git add modules/services/inventory_product_export_service.py modules/repositories/inventory_allocation_repository.py modules/services/inventory_product_query_service.py modules/schemas/inventory.py modules/routes/inventory.py modules/export_utils.py tests/test_inventory_product_export.py tests/test_inventory_product_query.py tests/test_permissions.py
git commit -m "feat(inventory): add product alerts and exports"
```

---

### Task 7: 完成来源分配抽屉、正式出库 UI 和移动端验收

**Files:**
- Create: `frontend/src/components/inventory/ProductAllocationDrawer.vue`
- Modify: `frontend/src/components/inventory/ProductInventoryDrawer.vue`
- Modify: `frontend/src/composables/inventory/useInventoryProductGroups.js`
- Modify: `frontend/src/lib/api/inventory.js`
- Modify: `frontend/src/views/InventoryList.vue`
- Test: `frontend/tests/unit/inventory-product-api.spec.js`
- Test: `frontend/tests/unit/useInventoryProductGroups.spec.js`
- Test: `frontend/tests/unit/ProductInventoryWorkbench.spec.js`
- Create: `frontend/tests/e2e/inventory-product-workbench.spec.js`

**Interfaces:**
- Consumes: Task 4 preview, Task 5 outbound and Task 6 threshold/export endpoints.
- Produces: complete FIFO/manual allocation UI; conflict recovery; desktop drawer and mobile full-screen behavior.

- [ ] **Step 1: Extend API facade tests for commands**

Assert exact payload and error mapping:

```javascript
await api.domains.inventory.previewProductAllocation(7, payload)
expect(fetchMock).toHaveBeenCalledWith(
  '/api/inventory/product-groups/7/allocation-preview',
  expect.objectContaining({ method: 'POST', body: JSON.stringify(payload) }),
)

await expect(api.domains.inventory.submitProductGroupOutbound(7, command))
  .rejects.toMatchObject({ status: 409, domainCode: 'inventory_allocation_preview_stale' })

await api.domains.inventory.updateProductThreshold(7, { safe_stock: 12, warning_buffer: 3 })
await api.domains.inventory.listProductAllocationRuns(7, { page: 1, limit: 20 })
await api.domains.inventory.reverseProductGroupOutbound(81, {
  idempotency_key: 'inventory-reversal-81-1',
  reason: '领用单撤销',
})
```

- [ ] **Step 2: Add facade methods**

```javascript
previewProductAllocation: (productId, data) => request(
  'POST', `/api/inventory/product-groups/${productId}/allocation-preview`, data,
),
submitProductGroupOutbound: (productId, data) => request(
  'POST', `/api/inventory/product-groups/${productId}/outbound`, data,
),
updateProductThreshold: (productId, data) => request(
  'PUT', `/api/inventory/product-groups/${productId}/threshold`, data,
),
listProductAllocationRuns: (productId, params) => request(
  'GET', `/api/inventory/product-groups/${productId}/allocation-runs` + buildQuery(params),
),
reverseProductGroupOutbound: (runId, data) => request(
  'POST', `/api/inventory/allocation-runs/${runId}/reverse`, data,
),
```

- [ ] **Step 3: Write composable tests for preview, manual mode, stale conflicts and idempotency keys**

Test that:

- FIFO is default;
- switching to manual clears the previous preview;
- manual mode requires at least one source and a reason;
- each confirm attempt creates one stable key such as `inventory-product-outbound:<productId>:<uuid>`;
- retry after a network timeout reuses that key;
- a 409 stale-preview error clears the old digest, reloads details and asks for a new preview;
- success refreshes both order and product views.
- users with `inventory:audit` can load immutable allocation history, and users with `inventory:adjust` can reverse an unreversed run only after entering a reason and confirming.
- users with `inventory:manage_threshold` can edit product safe stock and warning buffer; other users see read-only values.
- summary and expanded-detail export actions use `productGroupExportUrl` with the current filters and never construct an API path in the component.

- [ ] **Step 4: Implement allocation state in the product composable**

Expose:

```javascript
allocation: {
  drawerOpen, mode, quantity, reason, selectedInventoryIds,
  preview, previewLoading, submitting, error,
  runs, runsLoading, reversingRunId,
},
threshold: {
  safeStock, warningBuffer, saving, error,
},
actions: {
  openAllocation, closeAllocation, setAllocationMode,
  toggleInventorySource, previewAllocation, confirmOutbound,
  loadAllocationRuns, reverseAllocationRun,
  saveProductThreshold, exportProductGroups,
},
```

Do not generate a new idempotency key after an ambiguous network failure. Generate a new key only when the user changes the command after a confirmed failure or starts a new operation.

- [ ] **Step 5: Build the allocation drawer**

The drawer must show:

```text
产品与兼容分组
申请数量 / 可用总量
FIFO / 指定来源
来源订单 / 批次 / 库位 / 序列号
本次分配量 / 分配后余额
缺口、冲突和预览时间
人工原因
重新预览 / 确认出库
历史出库运行 / 反向流水状态 / 受控撤销
产品安全库存 / 预警缓冲 / 保存权限
导出当前汇总 / 导出汇总及展开明细
```

Use a fixed footer, internal scrolling, Escape close guard and explicit confirmation text. Disable confirmation until preview quantity exactly equals the request.

- [ ] **Step 6: Add responsive and accessibility behavior**

At widths below 900px the drawer occupies the viewport. Add `role="dialog"`, `aria-modal="true"`, labelled headings, focus restoration, visible keyboard focus and status text in addition to color.

- [ ] **Step 7: Add E2E acceptance flow**

The Playwright test must cover:

1. switch to product view;
2. filter a product code;
3. open compatible group;
4. preview FIFO allocation;
5. switch to manual and choose a source;
6. submit and observe refreshed balances;
7. update a product threshold with permission and verify read-only rendering without permission;
8. verify both export actions retain the active filters;
9. reverse the completed run and verify the original history remains visible;
10. emulate a mobile viewport and verify full-screen layout;
11. inject a stale-preview 409 and verify recovery guidance.

- [ ] **Step 8: Run frontend verification**

```bash
npx vitest run --config vitest.config.js \
  frontend/tests/unit/inventory-product-api.spec.js \
  frontend/tests/unit/useInventoryProductGroups.spec.js \
  frontend/tests/unit/ProductInventoryWorkbench.spec.js \
  frontend/tests/unit/inventory-composable.spec.js
npx playwright test frontend/tests/e2e/inventory-product-workbench.spec.js
npm run check:api
npm run check:imports
npm run build
```

Expected: all unit and E2E tests PASS; build exits 0; no facade or import-cycle violation.

- [ ] **Step 9: Commit Task 7**

```bash
git add frontend/src/components/inventory/ProductAllocationDrawer.vue frontend/src/components/inventory/ProductInventoryDrawer.vue frontend/src/composables/inventory/useInventoryProductGroups.js frontend/src/lib/api/inventory.js frontend/src/views/InventoryList.vue frontend/tests/unit/inventory-product-api.spec.js frontend/tests/unit/useInventoryProductGroups.spec.js frontend/tests/unit/ProductInventoryWorkbench.spec.js frontend/tests/unit/inventory-composable.spec.js frontend/tests/e2e/inventory-product-workbench.spec.js
git commit -m "feat(inventory): complete grouped outbound workbench"
```

---

### Task 8: 生产副本预检、全量验证和分阶段发布准备

**Files:**
- Create: `scripts/preflight_inventory_product_groups.py`
- Create: `tests/test_inventory_product_preflight.py`
- Create: `docs/runbooks/inventory-product-views-v096-rollout.md`
- Modify: `tests/test_deployment_contracts.py`
- Generated during authorized replica validation: `docs/superpowers/evidence/inventory-product-v096-replica-validation.md`

**Interfaces:**
- Consumes: all prior tasks and a copied production database path.
- Produces: deterministic JSON/Markdown preflight report, deployment gates, rollback contract and phased feature-flag checklist.

- [ ] **Step 1: Write failing preflight tests**

```python
import sqlite3

from modules.migrations import run_migrations
from scripts.preflight_inventory_product_groups import inspect_inventory_product_groups


def seed_inventory_replica(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    run_migrations(db)

    direct = db.execute(
        "INSERT INTO products(product_code,product_name,model,spec,category) "
        "VALUES('PF-DIRECT','直接产品','','','结构件')"
    ).lastrowid
    db.execute(
        "INSERT INTO inventory(product_model,product_name,quantity,reserved,frozen_quantity,"
        "safe_stock,unit,product_id,product_code_snapshot,product_name_snapshot) "
        "VALUES('PF-DIRECT','直接产品',5,0,0,0,'件',?,'PF-DIRECT','直接产品')",
        (direct,),
    )

    order_product = db.execute(
        "INSERT INTO products(product_code,product_name,model,spec,category) "
        "VALUES('PF-ORDER','订单产品','','','结构件')"
    ).lastrowid
    order_id = db.execute(
        "INSERT INTO orders(order_no,product_code,product_id,product_name,quantity,status) "
        "VALUES('PF-ORDER-001','PF-ORDER',?,'订单产品',1,'pending')",
        (order_product,),
    ).lastrowid
    db.execute(
        "INSERT INTO inventory(product_model,product_name,quantity,reserved,frozen_quantity,"
        "safe_stock,unit,order_id,product_id) "
        "VALUES('PF-ORDER','订单产品',4,0,0,0,'件',?,NULL)",
        (order_id,),
    )

    alias_product = db.execute(
        "INSERT INTO products(product_code,product_name,model,spec,category) "
        "VALUES('PF-ALIAS-CURRENT','别名产品','','','结构件')"
    ).lastrowid
    db.execute(
        "INSERT INTO product_code_aliases(product_id,product_code,source) "
        "VALUES(?, 'PF-ALIAS-OLD', 'product_update')",
        (alias_product,),
    )
    db.execute(
        "INSERT INTO inventory(product_model,product_name,quantity,reserved,frozen_quantity,"
        "safe_stock,unit,product_id) "
        "VALUES('PF-ALIAS-OLD','别名产品',3,0,0,0,'件',NULL)"
    )
    db.execute(
        "INSERT INTO inventory(product_model,product_name,quantity,reserved,frozen_quantity,"
        "safe_stock,unit,product_id) "
        "VALUES('PF-UNKNOWN','未知产品',2,0,0,0,'件',NULL)"
    )
    db.commit()
    db.close()
    return path


def test_preflight_is_read_only_and_reports_identity_buckets(tmp_path):
    database = seed_inventory_replica(tmp_path / "production-copy.db")
    before = database.read_bytes()

    report = inspect_inventory_product_groups(database, sample_limit=100)

    assert database.read_bytes() == before
    assert report["connection_mode"] == "read-only"
    assert report["identity"]["direct_product_id"] == 1
    assert report["identity"]["order_product_id"] == 1
    assert report["identity"]["alias_match"] == 1
    assert report["identity"]["unresolved"] == 1
    assert report["quantity_reconciliation"]["difference"] == 0
```

- [ ] **Step 2: Run preflight test and verify RED**

```bash
python -m pytest -q tests/test_inventory_product_preflight.py
```

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Implement the read-only preflight**

The script accepts:

```bash
python scripts/preflight_inventory_product_groups.py \
  --db /absolute/path/to/production-copy.db \
  --sample-limit 1000 \
  --json-output /absolute/path/to/report.json \
  --markdown-output /absolute/path/to/report.md
```

Export `inspect_inventory_product_groups(database_path, sample_limit=100) -> dict`, and have the CLI call the same function. Open SQLite using `mode=ro`. Report:

- current and target migration version;
- integrity and foreign-key checks;
- direct, order-derived, alias-derived, conflicting and unresolved identities;
- inventory, reserved, frozen and available totals before/after simulated grouping;
- product/compatibility group counts;
- negative or inconsistent balances;
- duplicate idempotency keys or allocation evidence anomalies;
- 20 representative FIFO previews without writes;
- exact blocking records requiring business confirmation.

Exit non-zero when integrity fails, totals differ, negative availability exists, or identity conflicts would be auto-grouped.

- [ ] **Step 4: Write the rollout and rollback runbook**

Document these stages with exact gates:

```text
Stage 0: V096 migration, all four flags false
Stage 1: INVENTORY_PRODUCT_QUERY_ENABLED=true
Stage 2: INVENTORY_ALLOCATION_PREVIEW_ENABLED=true
Stage 3: INVENTORY_PRODUCT_THRESHOLD_ENABLED=true
Stage 4: INVENTORY_CROSS_ORDER_OUTBOUND_ENABLED=true
```

For every stage list backup paths, health checks, API smoke tests, count reconciliation, audit queries and the command that restores the database and code. Require a separate authorization before Stage 4.

- [ ] **Step 5: Add deployment-contract assertions**

Assert the runbook contains V096, the four exact flag names, database backup, frontend backup, service restart, a rollback-SHA field that is filled only during deployment authorization, `data/`/attachment preservation, migration logs and audit evidence. The runbook must not claim a concrete production SHA before deployment authorization.

- [ ] **Step 6: Run focused backend and frontend suites**

```bash
python -m pytest -q \
  tests/test_inventory_product_migration_v096.py \
  tests/test_inventory_product_query.py \
  tests/test_inventory_source_allocator.py \
  tests/test_inventory_group_outbound.py \
  tests/test_inventory_product_export.py \
  tests/test_inventory_product_preflight.py \
  tests/test_inventory_ledger.py \
  tests/test_architecture_imports.py \
  tests/test_deployment_contracts.py
npx vitest run --config vitest.config.js \
  frontend/tests/unit/inventory-product-api.spec.js \
  frontend/tests/unit/useInventoryProductGroups.spec.js \
  frontend/tests/unit/ProductInventoryWorkbench.spec.js \
  frontend/tests/unit/inventory-composable.spec.js
```

Expected: exit 0 with no failures.

- [ ] **Step 7: Run complete repository verification**

```bash
python -m pytest -q
npm run test:unit
npm run check:architecture
npm run build
```

Expected: every command exits 0; backend and frontend pass counts are not lower than the branch baseline recorded before Task 1.

- [ ] **Step 8: Run an authorized production-copy replay**

On a verified copy, never the live database:

```bash
python scripts/preflight_inventory_product_groups.py \
  --db /absolute/path/to/production-copy.db \
  --sample-limit 1000 \
  --json-output /absolute/path/to/inventory-product-v096.json \
  --markdown-output docs/superpowers/evidence/inventory-product-v096-replica-validation.md
```

Then migrate a second disposable copy through V096 and rerun the same report. Acceptance requires:

- `PRAGMA integrity_check = ok`;
- zero foreign-key violations;
- inventory, reserved, frozen and available totals conserved;
- zero silently grouped conflicts;
- unresolved identities listed with inventory ID and reason;
- FIFO sample allocations conserve requested quantities;
- official inventory and shipment facts unchanged by the read-only pass.

- [ ] **Step 9: Commit Task 8**

```bash
git add scripts/preflight_inventory_product_groups.py tests/test_inventory_product_preflight.py docs/runbooks/inventory-product-views-v096-rollout.md tests/test_deployment_contracts.py
git commit -m "test(inventory): add V096 production readiness gates"
```

Do not commit a report containing production-sensitive rows until it has been reviewed and redacted. Commit the evidence report separately only if the authorized reviewer confirms it contains no sensitive customer, employee, serial-number or cost data.

---

## Final Review Gates

Before opening the implementation PR, verify:

1. Every task has its own commit and targeted tests.
2. `git diff --name-only "$(git merge-base HEAD github/master)" HEAD` contains only inventory dual-view files, migration registration, permissions, tests and approved documentation.
3. No `.brooks-lint-history.json`, `.tmp-*`, database copy, backup, generated spreadsheet or deployment secret is staged.
4. V096 is the next migration on the implementation branch; if master has advanced to a later migration before Task 1 begins, rebase first and renumber the migration and all tests consistently before writing code.
5. All four feature flags remain `false` by default.
6. With all flags false, current `/api/inventory` and frontend order view pass their existing tests unchanged.
7. Query and preview endpoints do not write inventory, logs, allocation evidence or audit records.
8. Formal grouped outbound cannot bypass `InventoryPostingService`.
9. Forced failure after any individual posting proves complete transaction rollback.
10. Product totals can always be reconciled to concrete inventory rows.
11. Identity exceptions are visible and excluded from automatic aggregation.
12. FIFO/manual results, idempotent replay, permission failures and stale previews have explicit tests.
13. API facade, backend/frontend import-cycle, production build and deployment-contract checks pass.
14. No production deployment, migration or feature-flag change occurs without separate authorization.
