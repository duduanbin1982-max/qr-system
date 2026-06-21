<!-- InventoryList.vue -->
<template>
<div style="padding:var(--space-6)">
    <!-- ====== 统计栏（统一 summary-bar 风格）====== -->
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">📦</span><div><div class="s-val">{{ stats.total_items }}</div><div class="s-label">库存品类</div></div></div>
      <div class="summary-item"><span class="s-icon">📊</span><div><div class="s-val text-primary">{{ stats.total_quantity || totalQty }}</div><div class="s-label">库存总量</div></div></div>
      <div class="summary-item"><span class="s-icon">💎</span><div><div class="s-val" style="color:var(--primary)">{{ inventoryValue.toLocaleString() }}</div><div class="s-label">库存总值</div></div></div>
      <div class="summary-item"><span class="s-icon">📥</span><div><div class="s-val text-success">{{ stats.today_in }}</div><div class="s-label">今日入库</div></div></div>
      <div class="summary-item"><span class="s-icon">📤</span><div><div class="s-val text-warning">{{ stats.today_out }}</div><div class="s-label">今日出库</div></div></div>
      <div class="summary-item"><span class="s-icon">⚠️</span><div><div class="s-val" :style="{color: stats.low_stock > 0 ? 'var(--danger)' : 'var(--success)'}">{{ stats.low_stock }}</div><div class="s-label">低库存预警</div></div></div>
    </div>
    <!-- ====== 主内容卡片 ====== -->
    <div class="card" style="border-radius:var(--radius-lg);overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.06),0 4px 16px rgba(0,0,0,0.04)">
      <div class="card-header" style="background:var(--bg-table-stripe);border-bottom:1px solid var(--bg-hover);padding:var(--space-4) 20px">
        <h3 style="font-size:var(--text-lg);font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:var(--space-2)">
          <span style="display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;background:linear-gradient(135deg,var(--primary),var(--primary-accent));border-radius:var(--radius-md);font-size:var(--text-lg)">🏗️</span>
          库存管理
        </h3>
        <div style="display:flex;gap:var(--space-3);align-items:center;flex-wrap:wrap">
          <div style="display:flex;align-items:center;background:var(--bg-hover);border-radius:var(--radius-md);padding:0 12px;transition:all 0.2s;border:1px solid transparent">
            <span style="color:var(--text-placeholder);font-size:var(--text-base)">🔍</span>
            <input class="form-input" v-model="searchKeyword" placeholder="搜索型号 / 名称…" @keyup.enter="load" style="border:none;background:transparent;outline:none;padding:var(--space-2) 8px;font-size:var(--text-sm);width:170px;box-shadow:none">
          </div>
          <label style="display:flex;align-items:center;gap:5px;font-size:var(--text-xs);color:var(--text-placeholder);cursor:pointer;white-space:nowrap;padding:6px 10px;background:#FFF;border-radius:var(--radius-md);border:1px solid var(--border-light)">
            <input type="checkbox" v-model="lowStockOnly" @change="load" style="accent-color:var(--danger);width:14px;height:14px"> 仅低库存
          </label>
          <select class="form-input" v-model="locationFilter" @change="load" style="border:1px solid var(--border-light);border-radius:var(--radius-md);padding:var(--space-2) 12px;font-size:var(--text-xs);background:white;cursor:pointer;width:110px">
            <option value="">📍 全部库位</option>
            <option v-for="loc in locations" :key="loc" :value="loc">{{ loc }}</option>
          </select>
          <div style="display:flex;gap:var(--space-2)">
            <button class="btn" style="padding:var(--space-2) 14px;font-size:var(--text-xs);background:var(--bg-hover);color:var(--text-secondary);border:1px solid var(--border-light);border-radius:var(--radius-md);cursor:pointer;font-weight:500" @click="load">🔍 搜索</button>
            <button class="btn" style="padding:var(--space-2) 14px;font-size:var(--text-xs);background:var(--bg-hover);color:var(--text-secondary);border:1px solid var(--border-light);border-radius:var(--radius-md);cursor:pointer;font-weight:500" @click="doABC">🏷️ ABC</button>
            <button class="btn" style="padding:var(--space-2) 14px;font-size:var(--text-xs);background:var(--bg-hover);color:var(--text-secondary);border:1px solid var(--border-light);border-radius:var(--radius-md);cursor:pointer;font-weight:500" @click="loadLogs()">📋 流水</button>
            <button class="btn" style="padding:var(--space-2) 14px;font-size:var(--text-xs);background:var(--bg-hover);color:var(--text-secondary);border:1px solid var(--border-light);border-radius:var(--radius-md);cursor:pointer;font-weight:500" @click="loadTurnover">📊 周转</button>
            <button class="btn" style="padding:var(--space-2) 14px;font-size:var(--text-xs);background:var(--bg-hover);color:var(--text-secondary);border:1px solid var(--border-light);border-radius:var(--radius-md);cursor:pointer;font-weight:500" @click="doCount">🔢 盘点</button>
            <button class="btn" style="padding:var(--space-2) 14px;font-size:var(--text-xs);background:var(--bg-hover);color:var(--text-secondary);border:1px solid var(--border-light);border-radius:var(--radius-md);cursor:pointer;font-weight:500" @click="exportExcel">📥导出</button>
            <button class="btn" style="padding:var(--space-2) 16px;font-size:var(--text-xs);background:linear-gradient(135deg,var(--primary),var(--primary));color:#FFF;border:none;border-radius:var(--radius-md);cursor:pointer;font-weight:600;box-shadow:0 2px 6px rgba(99,102,241,0.35)" @click="openAdd" v-if="canCreate">+ 新增库存</button>
          </div>
        </div>
      </div>
      <div class="card-body" style="padding:0">
        <div class="table-wrap" style="border-radius:0">
          <table v-if="items.length" class="data-table" style="min-width:850px;margin:0">
            <thead>
              <tr style="background:var(--bg-table-header)">
                <th style="min-width:100px;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">产品名称</th>
                <th style="min-width:90px;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">订单号</th>
                <th style="min-width:80px;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">客户</th>
                <th style="min-width:110px;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">产品型号</th>
                <th style="min-width:80px;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">规格</th>
                <th style="width:55px;text-align:center;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">ABC</th>
                <th style="width:80px;text-align:center;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">数量</th>
                <th style="width:80px;text-align:center;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">安全库存</th>
                <th style="min-width:80px;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">存放位置</th>
                <th style="width:55px;text-align:center;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted)">单位</th>
                <th style="width:195px;text-align:center;font-size:var(--text-xs);text-transform:uppercase;letter-spacing:0.5px;color:var(--text-muted);white-space:nowrap">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.id" class="inv-row" :class="{'inv-row-low': item.is_low}" @click="loadLogs(item.id)" style="cursor:pointer">
                <td style="font-weight:500">{{ item.product_name || '-' }}</td>
                <td><code style="font-size:var(--text-xs-alt)">{{ item.order_no || '-' }}</code></td>
                <td style="font-size:var(--text-xs)">{{ item.customer || '-' }}</td>
                <td>
                  <div style="display:flex;align-items:center;gap:var(--space-2)">
                    <span :style="{display:'inline-block',width:8,height:8,borderRadius:'50%',background: item.is_low ? 'var(--danger)' : 'var(--success)',flexShrink:0}"></span>
                    <code style="font-size:var(--text-xs);font-weight:600;color:var(--text-primary)">{{ item.product_model }}</code>
                  </div>
                </td>
                <td style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ item.specification || '-' }}</td>
                <td style="text-align:center">
                  <span v-if="item.category" class="badge" :class="item.category==='A'?'badge-danger':item.category==='B'?'badge-warning':'badge-success'" style="font-size:var(--text-2xs);font-weight:700">{{ item.category }}</span>
                  <span v-else style="color:var(--text-placeholder);font-size:var(--text-2xs)">-</span>
                </td>
                <td style="text-align:center">
                  <span style="display:inline-block;font-weight:700;font-size:15px;min-width:28px;padding:var(--space-1) 8px;border-radius:var(--radius-sm)" :style="{background: item.is_low ? 'var(--danger-light)' : 'var(--success-light)', color: item.is_low ? 'var(--danger)' : 'var(--success)'}">{{ item.quantity }}</span>
                </td>
                <td style="text-align:center;font-size:var(--text-xs);color:var(--text-placeholder)">
                  <span v-if="item.safe_stock" style="display:inline-block;background:var(--bg-hover);padding:1px 8px;border-radius:var(--radius-md);font-size:var(--text-xs-alt)">{{ item.safe_stock }}</span>
                  <span v-else>-</span>
                </td>
                <td style="font-size:var(--text-xs);color:var(--text-placeholder)">
                  <span v-if="item.location" style="display:inline-flex;align-items:center;gap:var(--space-1)">📍 {{ item.location }}</span>
                  <span v-else>-</span>
                </td>
                <td style="text-align:center;font-size:var(--text-xs);font-weight:500;color:var(--text-placeholder)">{{ item.unit }}</td>
                <td style="text-align:center">
                  <div class="inv-actions" @click.stop>
                    <button v-if="canEdit" class="inv-btn inv-btn-in" @click="openMove(item, 'in')" title="入库">
                      <span>📥</span><span>入库</span>
                    </button>
                    <button v-if="canEdit" class="inv-btn inv-btn-out" @click="openMove(item, 'out')" title="出库">
                      <span>📤</span><span>出库</span>
                    </button>
                    <button class="inv-btn inv-btn-edit" @click="openEdit(item)" v-if="canEdit" title="编辑">
                      <span>✏️</span>
                    </button>
                    <button class="inv-btn inv-btn-del" @click="del(item)" v-if="canDelete" title="删除">
                      <span>🗑️</span>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else style="text-align:center;padding:60px 20px">
            <div style="font-size:48px;margin-bottom:var(--space-3);opacity:0.4">🏗️</div>
            <div style="font-size:var(--text-base);color:var(--text-placeholder);margin-bottom:6px">暂无库存数据</div>
            <div style="font-size:var(--text-xs);color:var(--border)">点击「+ 新增库存」添加第一条记录</div>
          </div>
        </div>
      </div>
    </div>
    <!-- 新增/编辑模态框 -->
    <div v-if="showModal" class="modal-overlay" >
      <div class="modal" style="max-width:550px">
        <div class="modal-header">
          <span>{{ modalEdit ? '编辑库存' : '新增库存' }}</span>
          <span class="modal-close" @click="showModal=false">&times;</span>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-col" style="flex:2"><div class="form-group"><label>产品型号 *</label><input class="form-input" v-model="form.product_model" :disabled="modalEdit" placeholder="唯一标识"></div></div>
            <div class="form-col" style="flex:1"><div class="form-group"><label>关联订单</label><select class="form-input" v-model="form.order_id"><option value="">-- 无 --</option><option v-for="o in orderOptions" :key="o.id" :value="o.id">{{ o.order_no }} {{ o.product_name }}</option></select></div></div>
            <div class="form-col" style="flex:1"><div class="form-group"><label>单位</label><input class="form-input" v-model="form.unit" placeholder="件"></div></div>
          </div>
          <div class="form-row">
            <div class="form-col"><div class="form-group"><label>产品名称</label><input class="form-input" v-model="form.product_name" placeholder="名称"></div></div>
            <div class="form-col"><div class="form-group"><label>规格</label><input class="form-input" v-model="form.specification" placeholder="规格"></div></div>
          </div>
          <div class="form-row">
            <div class="form-col" v-if="!modalEdit"><div class="form-group"><label>初始数量</label><input class="form-input" v-model.number="form.quantity" type="number" min="0"></div></div>
            <div class="form-col"><div class="form-group"><label>安全库存</label><input class="form-input" v-model.number="form.safe_stock" type="number" min="0"></div></div>
            <div class="form-col"><div class="form-group"><label>存放位置</label><input class="form-input" v-model="form.location" placeholder="如：A区-3号架"></div></div>
          </div>
          <div class="form-group"><label>备注</label><input class="form-input" v-model="form.remark" placeholder="备注"></div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showModal=false">取消</button>
          <button class="btn btn-primary" @click="save">保存</button>
        </div>
      </div>
    </div>
    <!-- 出入库模态框 -->
    <div v-if="showMoveModal" class="modal-overlay" >
      <div class="modal" style="max-width:400px">
        <div class="modal-header">
          <span>{{ moveType === 'in' ? '📥 入库' : '📤 出库' }} — {{ moveTarget?.product_model }}</span>
          <span class="modal-close" @click="showMoveModal=false">&times;</span>
        </div>
        <div class="modal-body" style="text-align:center">
          <p style="color:var(--text-placeholder);margin-bottom:var(--space-4)">当前库存：<strong>{{ moveTarget?.quantity }}</strong> {{ moveTarget?.unit }}</p>
          <div class="form-group" v-if="moveType==='in'" style="margin-bottom:var(--space-3)">
            <label>关联订单</label>
            <select class="form-input" v-model="moveOrderId" style="text-align:center">
              <option value="">-- 无 --</option>
              <option v-for="o in orderOptions" :key="o.id" :value="o.id">{{ o.order_no }} {{ o.product_name }}</option>
            </select>
          </div>
          <div class="form-group">
            <label>{{ moveType === 'in' ? '入库' : '出库' }}数量</label>
            <input class="form-input" v-model.number="moveQty" type="number" min="1" style="text-align:center;font-size:24px;font-weight:700;width:150px;margin:0 auto" autofocus @keyup.enter="doMove">
          </div>
        </div>
        <div class="modal-footer" style="justify-content:center">
          <button class="btn btn-default" @click="showMoveModal=false">取消</button>
          <button class="btn" :class="moveType === 'in' ? 'btn-success' : 'btn-warning'" @click="doMove" style="min-width:100px">
            {{ moveType === 'in' ? '确认入库' : '确认出库' }}
          </button>
        </div>
      </div>
    </div>
    <!-- 流水日志 -->
    <div v-if="showLogs" class="modal-overlay" >
      <div class="modal" style="max-width:1500px">
        <div class="modal-header">
          <span>📋 库存流水</span>
          <div style="display:flex;gap:var(--space-2);align-items:center">
            <button class="btn btn-default btn-sm" @click="window.open('/api/inventory/logs/export','_blank')" style="font-size:var(--text-xs)">📥导出</button>
            <span class="modal-close" @click="showLogs=false">&times;</span>
          </div>
        </div>
        <div class="modal-body">
          <div v-if="logsLoading" style="text-align:center;padding:40px">⏳ 加载中...</div>
          <table v-else-if="logs.length" class="data-table">
            <thead><tr><th style="min-width:150px">时间</th><th style="min-width:130px">型号</th><th style="min-width:60px">类型</th><th style="min-width:60px">数量</th><th style="min-width:80px">操作人</th><th style="min-width:180px">备注</th></tr></thead>
            <tbody>
              <tr v-for="l in logs" :key="l.id">
                <td style="font-size:var(--text-xs);white-space:nowrap">{{ l.created_at }}</td>
                <td style="white-space:nowrap"><code style="font-size:var(--text-xs-alt)">{{ l.product_model }}</code></td>
                <td><span class="badge" :class="l.type==='in'?'badge-success':'badge-warning'" style="font-size:var(--text-xs-alt)">{{ l.type==='in'?'入库':'出库' }}</span></td>
                <td style="font-weight:600" :style="{color: l.type==='in'?'var(--success)':'var(--danger)'}">{{ l.type==='in'?'+':'-' }}{{ l.quantity }}</td>
                <td style="font-size:var(--text-sm);white-space:nowrap">{{ l.operator_name || '-' }}</td>
                <td style="font-size:var(--text-xs);color:var(--text-placeholder);white-space:nowrap">{{ l.remark || '-' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else style="text-align:center;color:var(--text-muted);padding:40px">暂无流水记录</p>
        </div>
      </div>
    </div>

    <!-- 周转率模态框 -->
    <div v-if="showTurnover" class="modal-overlay" >
      <div class="modal" style="max-width:700px">
        <div class="modal-header">
          <span>📊 库存周转分析</span>
          <span class="modal-close" @click="showTurnover=false">&times;</span>
        </div>
        <div class="modal-body">
          <div v-if="turnoverLoading" style="text-align:center;padding:40px">⏳ 加载中...</div>
          <table v-else-if="turnoverData.length" class="data-table">
            <thead><tr><th>产品型号</th><th>当前库存</th><th>月出库</th><th>月周转率</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="t in turnoverData" :key="t.id">
                <td><code style="font-size:var(--text-xs-alt)">{{ t.product_model }}</code></td>
                <td style="text-align:center;font-weight:600">{{ t.current_stock }}</td>
                <td style="text-align:center">{{ t.total_out || 0 }}</td>
                <td style="text-align:center">{{ t.turnover_rate || '-' }}</td>
                <td><span class="badge" :class="t.total_out===0?'badge-danger':t.turnover_rate<0.5?'badge-warning':'badge-success'" style="font-size:var(--text-2xs)">{{ t.total_out===0?'滞销':t.turnover_rate<0.5?'慢动':'正常' }}</span></td>
              </tr>
            </tbody>
          </table>
          <p v-else style="text-align:center;color:var(--text-muted);padding:40px">暂无数据</p>
        </div>
      </div>
    </div>
  </div>
</template>
<script>
import { ref, onMounted, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'

export default {
  setup() {
    const items = ref([])
    const orderOptions = ref([])
    const loading = ref(true)
    const searchKeyword = ref('')
    const lowStockOnly = ref(false)
    const locationFilter = ref('')
    const locations = ref([])

    // 流水
    const showLogs = ref(false)
    const logs = ref([])
    const logsLoading = ref(false)

    // 周转率
    const showTurnover = ref(false)
    const turnoverData = ref([])
    const turnoverLoading = ref(false)

    // 模态框 - 新增/编辑
    const showModal = ref(false)
    const modalEdit = ref(false)
    const modalId = ref(null)
    const form = ref({ product_model:'', product_name:'', specification:'', quantity:0, safe_stock:0, location:'', unit:'件', remark:'' })

    // 出入库
    const showMoveModal = ref(false)
    const moveType = ref('in')
    const moveTarget = ref(null)
    const moveQty = ref(1)
    const moveOrderId = ref('')

    // 统计
    const lowCount = computed(() => stats.value.low_stock || items.value.filter(i => i.is_low).length)
    const totalQty = computed(() => stats.value.total_quantity || items.value.reduce((s, i) => s + (i.quantity || 0), 0))
    const inventoryValue = computed(() => items.value.reduce((s, i) => s + (i.price || 0) * (i.quantity || 0), 0))
    const stats = ref({ total_items: 0, total_quantity: 0, low_stock: 0, today_in: 0, today_out: 0 })

    // RBAC
    const canEdit   = computed(() => can('inventory:edit'))
    const canDelete = computed(() => can('inventory:delete'))
    const canCreate = computed(() => can('inventory:create'))

    async function loadStats() {
      try { 
        const d = await api.inventoryStats()
        Object.assign(stats.value, d)
      } catch(e) {}
    }

    async function load() {
      loading.value = true
      try {
        const params = {}
        if (searchKeyword.value.trim()) params.keyword = searchKeyword.value.trim()
        if (lowStockOnly.value) params.low_stock = '1'
        if (locationFilter.value) params.location = locationFilter.value
        const d = await api.listInventory(Object.keys(params).length ? params : null)
        items.value = d.items || []
      } catch(e) {
        showToast(e.message || '加载失败', 'error')
      } finally {
        loading.value = false
      }
    }

    function exportExcel() {
      window.open('/api/inventory/export', '_blank')
    }

    async function doABC() {
      try {
        await api.classifyABC()
        showToast('ABC 分类完成')
        await load()
      } catch(e) { showToast(e.message || 'ABC分类失败','error') }
    }

    async function loadTurnover() {
      showTurnover.value = true
      turnoverLoading.value = true
      try {
        const d = await api.inventoryTurnover()
        turnoverData.value = d.data || []
      } catch(e) { showToast('加载周转数据失败','error') }
      finally { turnoverLoading.value = false }
    }

    async function doCount() {
      if (!confirm('确定创建盘点任务吗？')) return
      try {
        await api.createCountTask()
        showToast('盘点任务已创建')
      } catch(e) { showToast(e.message || '创建失败','error') }
    }

    async function loadLocations() {
      try {
        const d = await api.listLocations()
        locations.value = d.locations || []
      } catch(e) {}
    }

    async function loadLogs(invId) {
      showLogs.value = true
      logsLoading.value = true
      try {
        const params = invId ? { inventory_id: invId } : {}
        const d = await api.inventoryLogs(params)
        logs.value = d.logs || []
      } catch(e) {
        showToast(e.message || '加载流水失败', 'error')
      } finally {
        logsLoading.value = false
      }
    }

    function openAdd() {
      form.value = { product_model:'', product_name:'', specification:'', quantity:0, safe_stock:0, location:'', unit:'件', remark:'', order_id:'' }
      modalEdit.value = false; modalId.value = null
      showModal.value = true
    }

    function openEdit(item) {
      form.value = {
        product_model: item.product_model || '',
        product_name: item.product_name || '',
        specification: item.specification || '',
        quantity: item.quantity || 0,
        safe_stock: item.safe_stock || 0,
        location: item.location || '',
        unit: item.unit || '件',
        remark: item.remark || ''
      }
      modalEdit.value = true; modalId.value = item.id
      showModal.value = true
    }

    async function save() {
      if (!form.value.product_model.trim()) { showToast('请输入产品型号','error'); return }
      try {
        if (modalEdit.value) {
          await api.updateInventory(modalId.value, form.value)
          showToast('更新成功')
        } else {
          await api.createInventory(form.value)
          showToast('创建成功')
        }
        showModal.value = false
        await load()
        await loadStats()
      } catch(e) {
        showToast(e.message || '保存失败', 'error')
      }
    }

    async function del(item) {
      let impactInfo = ''
      try {
        const res = await api.inventoryImpact(item.id)
        if (res.log_count > 0) {
          impactInfo = '（将同步删除 ' + res.log_count + ' 条流水记录）'
        }
      } catch(e) { /* non-blocking */ }
      if (!confirm('确定删除库存 "' + item.product_model + '" 吗？' + impactInfo)) return
      try {
        await api.deleteInventory(item.id)
        showToast('删除成功')
        await load()
        await loadStats()
      } catch(e) {
        showToast(e.message || '删除失败', 'error')
      }
    }

    function openMove(item, type) {
      moveTarget.value = item
      moveType.value = type
      moveQty.value = 1
      showMoveModal.value = true
    }

    async function doMove() {
      const qty = parseInt(moveQty.value)
      if (!qty || qty <= 0) { showToast('请输入有效数量','error'); return }
      try {
        if (moveType.value === 'in') {
          const payload = { inventory_id: moveTarget.value.id, quantity: qty, remark: '手动入库' }
          if (moveOrderId.value) {
            payload.order_id = moveOrderId.value
            const ord = orderOptions.value.find(o => o.id == moveOrderId.value)
            if (ord) payload.order_no = ord.order_no
          }
          await api.stockIn(payload)
          showToast('入库成功 +' + qty)
        } else {
          await api.stockOut({ inventory_id: moveTarget.value.id, quantity: qty, remark: '手动出库' })
          showToast('出库成功 -' + qty)
        }
        showMoveModal.value = false
        moveOrderId.value = ''
        await load()
        await loadStats()
      } catch(e) {
        showToast(e.message || '操作失败', 'error')
      }
    }

    async function loadOrders() {
      try { const d = await api.listOrders({limit:999}); orderOptions.value = d.orders || [] } catch(e) {}
    }
    onMounted(() => { load(); loadStats(); loadOrders(); loadLocations() })

    return {
      items, loading, searchKeyword, lowStockOnly, locationFilter, locations, load, exportExcel, doABC,
      lowCount, totalQty, inventoryValue, stats,
      showLogs, logs, logsLoading, loadLogs,
      showTurnover, turnoverData, turnoverLoading, loadTurnover, doCount,
      showModal, modalEdit, form, openAdd, openEdit, save, del,
      showMoveModal, moveType, moveTarget, moveQty, moveOrderId, openMove, doMove,
      can, canEdit, canDelete, canCreate
    }
  }
}
</script>