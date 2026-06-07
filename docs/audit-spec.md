# 扫码报工生产管理系统 — 代码审计规范 v1.0

> 基于 100+ 个实际 bug 提炼，按检查项→严重度→检测方法→示例组织

---

## 一、权限与认证 (Auth & RBAC)

### 1.1 后端路由装饰器完整性
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| 每个写端点(POST/PUT/DELETE)必须有 `@check_permission('module:action')` | 🔴 P0 | `grep -A3 'def \w+'` 逐端点检查装饰器链 |
| 读端点(GET)必须有 `@check_auth`，敏感数据需 `@check_permission('module:view')` | 🟡 P1 | 同上 |
| 公开端点（如 board）必须有注释说明为何免认证 | 🟢 P2 | 搜索 `@app.route` 后无 `@check_auth` 者 |

**违规示例：**
```python
# ❌ 仅登录检查，无权限控制 — 任意登录用户可操作
@app.route('/api/orders/batch', methods=['POST'])
@check_auth
def batch_create_orders():
```
**修复：** 添加 `@check_permission('orders:create')`

### 1.2 前端 RBAC 门控
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| JS 文件 `setup()` 中是否有 `canEdit`/`canDelete`/`canCreate` computed | 🔴 P0 | `grep 'canEdit\|canDelete\|canCreate' *.js` |
| 模板中新增/编辑/删除按钮是否有 `v-if="canEdit"` 等 | 🔴 P0 | `grep '@click.*openAdd\|@click.*openEdit\|@click.*del' *.html` |
| `can()` 函数是否从 `auth.js` 正确导入 | 🟡 P1 | 检查 import 语句 |
| `auth` 导入但仅返回未使用 → 应移除或添加 RBAC computed | 🟢 P2 | 对比 import 和 return 中的 auth |

**违规示例：**
```javascript
// ❌ 导入了 auth/can 但从未计算 canEdit/canDelete/canCreate
import { auth, can } from '../../auth.js'
// ... setup() 中无任何 computed(() => can('xxx:edit')) ...
return { ..., auth, can }  // 暴露了但没用
```

---

## 二、事务与异常处理 (Transaction & Exception)

### 2.1 事务边界正确性
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| 写操作前是否有 `db.execute("BEGIN IMMEDIATE")` | 🟡 P1 | `grep -B5 'INSERT\|UPDATE\|DELETE'` 检查上方是否有 BEGIN |
| `audit_log` 是否在 `db.commit()` 和 try 块**之外** | 🟡 P1 | 检查 commit 和 audit_log 的相对位置 |
| try 块是否覆盖**全部**写操作（不仅是 commit） | 🟡 P1 | 检查 try 的起始行是否在第一个 `db.execute(INSERT/UPDATE/DELETE)` 之前 |
| except 块是否有 `db.execute('ROLLBACK')` | 🔴 P0 | 逐 except 块检查 |

**违规示例：**
```python
# ❌ audit_log 在 try 内且 commit 之后 → 日志异常触发 500 但数据已提交
try:
    db.execute('INSERT INTO orders ...')
    db.commit()
    audit_log('create_order', ...)  # ← 应移出 try
    return jsonify(...)
except Exception as e:
    db.execute('ROLLBACK')
    return jsonify(...), 500
```

**正确模式：**
```python
db.execute("BEGIN IMMEDIATE")
try:
    db.execute('INSERT INTO orders ...')
    db.commit()
    return jsonify(...)
except Exception as e:
    db.execute('ROLLBACK')
    return jsonify(...), 500

# 日志在事务外，独立 try/catch
try:
    audit_log('create_order', ...)
except Exception:
    pass
```

### 2.2 SQLite 隐式事务陷阱
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| 无 `BEGIN IMMEDIATE` 的写操作 → SQLite 自动提交导致无法 ROLLBACK | 🟡 P1 | 搜索写端点中缺少 `BEGIN IMMEDIATE` 的情况 |

---

## 三、SQL 安全 (SQL Security)

### 3.1 注入风险
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| 是否使用 f-string 拼接用户输入到 SQL | 🔴 P0 | `grep -E "f['\"].*\{.*\}.*SELECT\|INSERT\|UPDATE\|DELETE"` |
| 动态列名/表名是否使用白名单映射 | 🟡 P1 | 检查 f-string 中是否有变量被直接拼入 SQL 关键位置 |
| LIKE 查询是否使用参数化 `?` 而非字符串拼接 | 🟢 P2 | 检查 LIKE 子句 |

**违规示例：**
```python
# ❌ category 来自 request.args，直接拼入 SQL
cat_filter = f" AND p.category = '{category}'" if category else ""
db.execute(f'SELECT * FROM orders WHERE 1=1{cat_filter}', ...)
```
**修复：**
```python
cat_filter = " AND p.category = ?" if category else ""
cat_params = [category] if category else []
db.execute(f'SELECT * FROM orders WHERE 1=1{cat_filter}', cat_params)
```

### 3.2 field_map 白名单
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| 动态 ORDER BY / GROUP BY 列是否使用 `field_map` 字典映射 | 🟡 P1 | 检查 sortBy/orderBy 参数处理 |

**正确模式：**
```python
field_map = {
    'order_no': 'o.order_no',
    'product_name': 'o.product_name',
    'status': 'o.status',
}
sort_col = field_map.get(sort_by, 'o.created_at')
```

---

## 四、查询性能 (Query Performance)

### 4.1 N+1 查询
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| 循环内是否有 SQL 查询 | 🟡 P1 | `grep -A5 'for.*in'` 后跟 `db.execute` |
| 关联数据是否用 JOIN 或 `IN (?)` 批量预取 | 🟢 P2 | 检查是否先获取列表再循环查详情 |

### 4.2 查询合并
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| 多个独立统计查询是否可合并为一个 | 🟢 P2 | 检查连续多个 `SELECT COUNT(*)/SUM()` 是否可 UNION ALL |
| 是否缺少分页参数 (limit/offset) | 🟡 P1 | 检查 list 端点是否有 limit/offset 处理 |
| Python 侧大集合运算是否可下推到 SQL | 🟢 P2 | 检查 `set()` 操作是否来自 `fetchall()` 结果 |

---

## 五、前端代码质量 (Frontend Quality)

### 5.1 导入与引用
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| 是否导入了未使用的 Vue API | 🟢 P2 | 对比 import 和实际使用 |
| `auth`/`router` 是否导入但未使用 | 🟢 P2 | 同上 |
| JS 版本号（`?v=56`）是否一致 | 🟢 P3 | 批量检查 import 路径 |

### 5.2 模板与交互
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| `v-if="canEdit"` / `v-if="canDelete"` 是否与 JS 中 computed 变量名一致 | 🔴 P0 | 交叉比对模板和 JS |
| 导航目标是否正确（如"今日报废"应跳 stats 而非 orders） | 🟢 P3 | 逐卡片检查 `@click="navigate(...)"` |
| 是否有多余的响应式赋值（如 `items.value = [...items.value]`） | 🟢 P3 | 搜索 `= [...` 模式 |

### 5.3 生命周期
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| `onMounted` 中是否返回 cleanup 函数（Vue3 不支持） | 🔴 P0 | 检查 `onMounted(() => { ... return () => {} })` |
| 定时器是否在 `onUnmounted` 中清除 | 🟡 P1 | 检查 `setInterval`/`setTimeout` 是否有对应 clear |
| `onMounted` 中的多个 API 请求是否用 `Promise.all` 并发 | 🟢 P2 | 统计 `onMounted` 中独立的异步调用数量 |

**违规示例：**
```javascript
// ❌ Vue3 不支持 onMounted 返回 cleanup
onMounted(() => {
    const timer = setInterval(load, 30000)
    return () => { clearInterval(timer) }  // 永远不会执行
})
```
**修复：** 使用 `onUnmounted`

### 5.4 API 调用
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| 是否使用 `api.xxx()` 包装器而非原生 `fetch()` | 🟡 P1 | `grep 'fetch(' *.js` |
| 文件上传是否调用专用的 upload wrapper | 🟢 P2 | 检查 FormData 处理 |
| 错误处理是否包含 `showToast(e.message, 'error')` | 🟢 P2 | 检查 catch 块 |

---

## 六、前后端对齐 (Frontend-Backend Alignment)

### 6.1 数据结构
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| 后端返回的 JSON 字段名是否与前端模板一致 | 🔴 P0 | 对比 `jsonify({...})` 和 `{{ item.xxx }}` |
| 统计字段来源一致性（如 stats ref vs computed） | 🟢 P2 | 检查同一概念是否有多数据源 |

### 6.2 模板 ID
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| `template: '#xxx-template'` 是否与实际 HTML 模板 ID 匹配 | 🔴 P0 | 交叉检查 |

---

## 七、架构与代码组织 (Architecture)

### 7.1 模块职责
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| 一个文件是否包含多个独立业务模块 | 🟡 P1 | 检查文件内 `@app.route` 的多样性 |
| Route 层是否绕过了 Service 层直接写 SQL | 🟢 P2 | 检查 route 文件中是否有内联 SQL |
| Service 层方法是否为死代码（从无 route 调用） | 🟢 P2 | 交叉引用搜索 |

### 7.2 代码重复
| 检查项 | 严重度 | 检测方法 |
|--------|:------:|----------|
| 两个函数/文件是否有相同逻辑块 | 🟢 P2 | 函数体相似度对比 |
| CSV 导出是否有多个独立实现 → 应提取公共函数 | 🟢 P3 | 搜索 `exportCSV` / `Blob` / `createObjectURL` |

---

## 八、审计执行流程

### 8.1 定位模块文件
```bash
find /home/dubin/qr-system -type f \( -name "*<module>*" -o -name "*<Module>*" \) \
  ! -path "*/__pycache__/*" ! -path "*.bak*"
```
典型文件清单：
- `modules/routes/<module>.py` — 后端路由
- `modules/services/<module>_service.py` — 业务逻辑层（如存在）
- `public/js/components/<module>/<Module>List.js` — 前端组件
- `public/components/<module>-list.html` — 前端模板

### 8.2 逐文件检查顺序
1. **后端路由**：权限装饰器 → 事务边界 → SQL 注入 → N+1 → 分页 → 死代码
2. **Service 层**：是否被调用 → 逻辑是否重复 → 参数化查询
3. **前端 JS**：导入 → RBAC computed → API wrapper → 生命周期 → 语法错误
4. **前端模板**：v-if 门控 → 字段对齐 → 导航目标 → 按钮逻辑

### 8.3 报告格式
```
🔴 P0 — 致命（阻塞性 bug）
🟠 P1 — 高危（安全/数据风险）
🟡 P2 — 中危（性能/架构/可维护性）
🔵 P3 — 低危（代码风格/可读性）
✅ 已验证通过（N 项）
```

---

## 附录 A：已知项目约定

| 约定 | 说明 |
|------|------|
| 软删除 | `deleted_at IS NULL`（非 `is_deleted = 0`） |
| 认证方式 | httpOnly cookie `qr_token` + `@check_auth` 装饰器 |
| 当前用户 | `g.current_user`（非 `request.environ.current_user`） |
| 权限格式 | `module:action`（如 `orders:edit`、`products:delete`） |
| 前端 RBAC | `can('module:action')` 返回 boolean |
| 数据库 | SQLite，需 `BEGIN IMMEDIATE` 防止并发写入丢失 |
| 前端框架 | Vue 3 CDN（无构建步骤），模板变更需重启 Gunicorn |
| API 调用 | 前端统一用 `api.xxx()` 包装器，禁止直接 `fetch()` |
| CSS 变量 | `var(--primary)`, `var(--space-4)` 等，禁止硬编码颜色/间距 |

## 附录 B：已知重复 bug 模式

| 模式 | 出现次数 | 检测正则 |
|------|:------:|----------|
| `@check_auth` 后缺 `@check_permission` | 6+ | 检查装饰器链完整性 |
| `audit_log` 在 commit 后 try 内 | 4+ | `commit()\n.*audit_log` |
| JS 缺 `canEdit`/`canDelete`/`canCreate` computed | 8+ | 检查 return 对象 |
| 模板缺 `v-if="canEdit"` | 8+ | 按钮无 v-if |
| `fetch()` 替代 `api.xxx()` | 3+ | `fetch('/api` |
| 硬编码颜色/间距 | 10+ | `style="color:#xxx"` |
| `onMounted` 返回 cleanup | 1 | `return () =>` in onMounted |
