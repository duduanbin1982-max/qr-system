<!-- TracePage.vue -->
<template>
<div style="padding:var(--space-6)">
    <div class="card" style="margin-bottom:var(--space-5)">
      <div class="card-body" style="padding:var(--space-5)">
        <div style="display:flex;gap:var(--space-3);align-items:center;margin-bottom:12px">
          <button class="btn btn-sm" :style="{background: traceMode==='serial'?'var(--primary)':'var(--bg-hover)',color: traceMode==='serial'?'#fff':'var(--text-placeholder)'}" @click="traceMode='serial'">🔢 序列号追溯</button>
          <button class="btn btn-sm" :style="{background: traceMode==='order'?'var(--primary)':'var(--bg-hover)',color: traceMode==='order'?'#fff':'var(--text-placeholder)'}" @click="traceMode='order'">📋 订单号追溯</button>
        </div>
        <div style="display:flex;gap:var(--space-3);align-items:center">
          <div style="flex:1;position:relative">
            <input class="form-input" v-model="traceCode" :placeholder="traceMode==='serial'?'🔍 输入产品序列号进行追溯...':'🔍 输入订单号进行追溯...'"
              @keyup.enter="doTrace" style="font-size:var(--text-lg);padding:var(--space-3) 16px;border:2px solid var(--primary);border-radius:var(--radius-lg)" autofocus>
          </div>
          <button class="btn btn-primary" @click="doTrace" :disabled="searching" style="padding:var(--space-3) 32px;font-size:15px;white-space:nowrap">
            <span v-if="searching">⏳ 查询中...</span>
            <span v-else>🔍 追溯</span>
          </button>
          <button v-if="result" class="btn" style="padding:var(--space-3) 20px;font-size:15px;white-space:nowrap;background:#fff;border:1px solid var(--border-light)" onclick="window.print()">🖨 打印报告</button>
        </div>
        <!-- Trace history -->
        <div v-if="traceHistory.length" style="margin-top:10px;display:flex;align-items:center;gap:6px;flex-wrap:wrap">
          <span style="font-size:11px;color:var(--text-placeholder);white-space:nowrap">历史:</span>
          <span v-for="(h,i) in traceHistory" :key="i" style="font-size:11px;padding:2px 8px;background:var(--bg-hover);border-radius:10px;cursor:pointer;color:var(--primary);white-space:nowrap" @click="traceCode=h.code;traceMode=h.mode;doTrace()" :title="h.mode==='serial'?'序列号':'订单号'+': '+h.code">
            {{ h.mode==='serial'?'🔢':'📋' }} {{ h.code }}
          </span>
        </div>
      </div>
    </div>

    <!-- Results -->
    <div v-if="result">
      <!-- Mode badge -->
      <div v-if="result.item" style="margin-bottom:var(--space-3);font-size:var(--text-sm);color:var(--primary);font-weight:500">🔢 序列号追溯结果</div>
      <div v-else-if="result.items" style="margin-bottom:var(--space-3);font-size:var(--text-sm);color:var(--primary);font-weight:500">📋 订单号追溯结果</div>

      <!-- Item Info (serial mode only) -->
      <div class="card" style="margin-bottom:var(--space-5)" v-if="result.item">
        <div class="card-header"><h3>🏷️ 产品信息</h3></div>
        <div class="card-body">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-3);font-size:var(--text-base)">
            <div><span style="color:var(--text-placeholder)">序列号：</span><code style="font-weight:600">{{ result.item.serial_no }}</code></div>
            <div><span style="color:var(--text-placeholder)">状态：</span><span class="badge" :class="result.item.status==='completed'?'badge-success':result.item.status==='in_progress'?'badge-warning':'badge-info'" style="font-size:var(--text-xs-alt)">{{ result.item.status==='completed'?'已完成':result.item.status==='in_progress'?'生产中':'待处理' }}</span></div>
            <div><span style="color:var(--text-placeholder)">订单号：</span><code style="font-weight:600">{{ result.order?.order_no || '-' }}</code></div>
            <div><span style="color:var(--text-placeholder)">产品：</span>{{ result.order?.product_name || '-' }}</div>
            <div><span style="color:var(--text-placeholder)">位置序号：</span>{{ result.item.position_no || '-' }}</div>
            <div><span style="color:var(--text-placeholder)">当前工序ID：</span>{{ result.item.current_process_id || '-' }}</div>
          </div>
        </div>
      </div>

      <!-- Items list (order trace mode) -->
      <div class="card" style="margin-bottom:var(--space-5)" v-if="result.items && result.items.length">
        <div class="card-header"><h3>📦 产品列表 ({{ result.items.length }})</h3></div>
        <div class="card-body">
          <table class="data-table" style="font-size:var(--text-xs)">
            <thead><tr><th>序列号</th><th>位置</th><th>状态</th><th>当前工序ID</th><th>创建时间</th></tr></thead>
            <tbody>
              <tr v-for="it in result.items" :key="it.id" :style="{cursor:'pointer'}" @click="traceCode=it.serial_no;traceMode='serial';doTrace()" title="点击追溯该产品">
                <td><code style="font-weight:600;color:var(--primary)">{{ it.serial_no }}</code></td>
                <td>{{ it.position_no || "-" }}</td>
                <td><span class="badge" :class="it.status==='completed'?'badge-success':it.status==='in_progress'?'badge-warning':'badge-info'" style="font-size:var(--text-2xs)">{{ it.status==='completed'?'已完成':it.status==='in_progress'?'生产中':'待处理' }}</span></td>
                <td>{{ it.current_process_id || "-" }}</td>
                <td style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ it.created_at }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Back to order (serial mode only, if order exists) -->
      <div v-if="result.item && result.order" style="margin-bottom:var(--space-3);font-size:12px">
        <span style="color:var(--primary);cursor:pointer;text-decoration:underline" @click="traceCode=result.order.order_no;traceMode='order';doTrace()">← 查看订单 {{ result.order.order_no }} 全部产品</span>
      </div>

      <!-- Order Info -->
      <div class="card" style="margin-bottom:var(--space-5)" v-if="result.order">
        <div class="card-header"><h3>📋 关联订单</h3></div>
        <div class="card-body">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-3);font-size:var(--text-base)">
            <div><span style="color:var(--text-placeholder)">订单号：</span><code style="font-weight:600">{{ result.order.order_no }}</code></div>
            <div><span style="color:var(--text-placeholder)">客户：</span>{{ result.order.customer || '-' }}</div>
            <div><span style="color:var(--text-placeholder)">产品名：</span>{{ result.order.product_name }}</div>
            <div><span style="color:var(--text-placeholder)">数量：</span><strong>{{ result.order.quantity }}</strong></div>
            <div><span style="color:var(--text-placeholder)">已完成：</span><strong class="text-success">{{ result.order.completed || 0 }}</strong></div>
            <div><span style="color:var(--text-placeholder)">状态：</span><span class="badge" :class="result.order.status==='completed'?'badge-success':result.order.status==='producing'?'badge-warning':'badge-info'" style="font-size:var(--text-xs-alt)">{{ result.order.status==='completed'?'已完成':result.order.status==='producing'?'生产中':'待处理' }}</span></div>
            <div><span style="color:var(--text-placeholder)">创建时间：</span>{{ result.order.created_at }}</div>
          </div>
        </div>
      </div>

      <!-- Work Records Timeline -->
      <div class="card" style="margin-bottom:var(--space-5)">
        <div class="card-header"><h3>📝 报工记录 ({{ (result.work_records||[]).length }})</h3></div>
        <div class="card-body">
          <div v-if="result.work_records && result.work_records.length">
            <div class="timeline">
              <div v-for="(r, idx) in result.work_records" :key="r.id" class="tl-item" style="display:flex;gap:var(--space-4);padding:var(--space-3) 0;border-bottom:1px solid var(--bg-hover)">
                <div style="min-width:60px;text-align:center">
                  <div style="width:32px;height:32px;border-radius:50%;background:var(--primary-light);display:flex;align-items:center;justify-content:center;margin:0 auto;font-size:var(--text-base)">{{ idx + 1 }}</div>
                  <div v-if="idx < result.work_records.length - 1" style="width:2px;height:calc(100% - 32px);background:var(--border-light);margin:4px auto 0"></div>
                </div>
                <div style="flex:1">
                  <div style="display:flex;justify-content:space-between;align-items:center">
                    <div style="font-weight:500">{{ r.process_name }}</div>
                    <span class="badge" :class="r.status==='approved'?'badge-success':r.status==='pending'?'badge-warning':'badge-danger'" style="font-size:var(--text-2xs)">{{ r.status==='approved'?'已审批':r.status==='pending'?'待审批':r.status }}</span>
                  </div>
                  <div style="font-size:var(--text-xs);color:var(--text-placeholder);margin-top:2px">
                    <span>{{ r.worker_name }}</span>
                    <span style="margin:0 8px">·</span>
                    <span>数量 <strong style="color:#111">{{ r.quantity }}</strong></span>
                    <span v-if="getTimeDiff(idx, result.work_records)" style="margin:0 8px">·</span>
                    <span v-if="getTimeDiff(idx, result.work_records)" style="color:var(--teal)">⏱ {{ getTimeDiff(idx, result.work_records) }}</span>
                    <span style="margin:0 8px">·</span>
                    <span>{{ r.created_at }}</span>
                  </div>
                  <div v-if="r.remark" style="font-size:var(--text-xs);color:var(--text-placeholder);margin-top:2px">备注：{{ r.remark }}</div>
                </div>
              </div>
            </div>
          </div>
          <p v-else style="text-align:center;color:var(--text-placeholder);padding:var(--space-5)">暂无报工记录</p>
        </div>
      </div>

      <!-- Lifecycle Timeline -->
      <div class="card" style="margin-bottom:var(--space-5)">
        <div class="card-header"><h3>🕐 完整生命周期</h3></div>
        <div class="card-body">
          <div class="timeline">
            <div v-if="result.order" class="tl-item" style="display:flex;gap:var(--space-4);padding:var(--space-3) 0;border-bottom:1px solid var(--bg-hover)">
              <div style="min-width:60px;text-align:center">
                <div style="width:32px;height:32px;border-radius:50%;background:#e8f5e9;display:flex;align-items:center;justify-content:center;margin:0 auto;font-size:var(--text-base)">📋</div>
              </div>
              <div style="flex:1">
                <div style="font-weight:500">订单创建</div>
                <div style="font-size:var(--text-xs);color:var(--text-placeholder);margin-top:2px">{{ result.order.created_at }}</div>
              </div>
            </div>
            <div v-for="(r, idx) in (result.work_records||[])" :key="'life-'+r.id" class="tl-item" style="display:flex;gap:var(--space-4);padding:var(--space-3) 0;border-bottom:1px solid var(--bg-hover)">
              <div style="min-width:60px;text-align:center">
                <div style="width:32px;height:32px;border-radius:50%;background:var(--primary-light);display:flex;align-items:center;justify-content:center;margin:0 auto;font-size:12px;font-weight:600;color:var(--primary)">{{ idx+1 }}</div>
              </div>
              <div style="flex:1">
                <div style="font-weight:500">{{ r.process_name }} <span style="color:var(--text-placeholder);font-weight:400;font-size:var(--text-xs)">— {{ r.worker_name }}</span></div>
                <div style="font-size:var(--text-xs);color:var(--text-placeholder);margin-top:2px">+{{ r.quantity }} {{ r.created_at }}</div>
              </div>
            </div>
            <div v-for="qi in (result.quality_inspections||[])" :key="'qi-'+qi.id" class="tl-item" style="display:flex;gap:var(--space-4);padding:var(--space-3) 0;border-bottom:1px solid var(--bg-hover)">
              <div style="min-width:60px;text-align:center">
                <div :style="{width:'32px',height:'32px',borderRadius:'50%',background: qi.result==='passed'?'#e8f5e9':qi.result==='failed'?'#fce4ec':'#fff3e0',display:'flex',alignItems:'center',justifyContent:'center',margin:'0 auto',fontSize:'14px'}">🔍</div>
              </div>
              <div style="flex:1">
                <div style="font-weight:500">{{ qi.process_name || '-' }} 质检 <span class="badge" :class="qi.result==='passed'?'badge-success':qi.result==='failed'?'badge-danger':'badge-warning'" style="font-size:var(--text-2xs)">{{ qi.result==='passed'?'合格':qi.result==='failed'?'不合格':'待检' }}</span></div>
                <div style="font-size:var(--text-xs);color:var(--text-placeholder);margin-top:2px">抽检 {{ qi.quantity_checked }} / 合格 {{ qi.quantity_passed }} {{ qi.inspected_at }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Quality Inspections -->
      <div class="card" style="margin-bottom:var(--space-5)">
        <div class="card-header"><h3>🔍 质检记录 ({{ (result.quality_inspections||[]).length }})</h3></div>
        <div class="card-body">
          <table v-if="result.quality_inspections && result.quality_inspections.length" class="data-table" style="font-size:var(--text-xs)">
            <thead><tr><th>工序</th><th>类型</th><th>抽检</th><th>合格</th><th>不合格</th><th>结果</th><th>检验员</th><th>时间</th></tr></thead>
            <tbody>
              <tr v-for="q in result.quality_inspections" :key="q.id">
                <td>{{ q.process_name || "-" }}</td>
                <td>{{ q.inspection_type || "-" }}</td>
                <td>{{ q.quantity_checked }}</td>
                <td style="color:var(--success)">{{ q.quantity_passed }}</td>
                <td style="color:var(--danger)">{{ q.quantity_failed }}</td>
                <td><span class="badge" :class="q.result==='passed'?'badge-success':q.result==='failed'?'badge-danger':'badge-warning'" style="font-size:var(--text-2xs)">{{ q.result==='passed'?'合格':q.result==='failed'?'不合格':'待检' }}</span></td>
                <td>{{ q.inspector_name || "-" }}</td>
                <td style="font-size:var(--text-xs-alt)">{{ q.inspected_at || q.created_at }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else style="text-align:center;color:var(--text-placeholder);padding:var(--space-5)">暂无质检记录</p>
        </div>
      </div>

      <!-- Material Consumptions -->
      <div class="card" style="margin-bottom:var(--space-5)">
        <div class="card-header"><h3>🧱 物料消耗 ({{ (result.material_consumptions||[]).length }})</h3></div>
        <div class="card-body">
          <table v-if="result.material_consumptions && result.material_consumptions.length" class="data-table" style="font-size:var(--text-xs)">
            <thead><tr><th>物料</th><th>规格</th><th>工序</th><th>数量</th><th>操作人</th><th>备注</th><th>时间</th></tr></thead>
            <tbody>
              <tr v-for="mc in result.material_consumptions" :key="mc.id">
                <td style="font-weight:500">{{ mc.material_name }}</td>
                <td>{{ mc.material_spec || "-" }}</td>
                <td>{{ mc.process_name || "-" }}</td>
                <td style="color:var(--danger);font-weight:600">{{ mc.quantity }}</td>
                <td>{{ mc.operator_name || "-" }}</td>
                <td style="color:var(--text-placeholder);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" :title="mc.notes">{{ mc.notes || "-" }}</td>
                <td style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ mc.created_at }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else style="text-align:center;color:var(--text-placeholder);padding:var(--space-5)">暂无物料消耗</p>
        </div>
      </div>

      <!-- Rework Records -->
      <div class="card" style="margin-bottom:var(--space-5)">
        <div class="card-header"><h3>🔄 返工记录 ({{ (result.rework_records||[]).length }})</h3></div>
        <div class="card-body">
          <div v-if="result.rework_records && result.rework_records.length">
            <table class="data-table" style="font-size:var(--text-xs)">
              <thead><tr><th>工序</th><th>数量</th><th>原因</th><th>操作人</th><th>状态</th><th>创建时间</th><th>完成时间</th></tr></thead>
              <tbody>
                <tr v-for="r in result.rework_records" :key="r.id">
                  <td style="font-weight:500">{{ r.process_name }}</td>
                  <td style="color:var(--danger);font-weight:600">{{ r.quantity }}</td>
                  <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" :title="r.reason">{{ r.reason || "-" }}</td>
                  <td>{{ r.worker_name || "-" }}</td>
                  <td><span class="badge" :class="r.status==='completed'?'badge-success':'badge-warning'" style="font-size:var(--text-2xs)">{{ r.status==='completed'?'已完成':'处理中' }}</span></td>
                  <td style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ r.created_at }}</td>
                  <td style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ r.completed_at || "-" }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else style="text-align:center;color:var(--text-placeholder);padding:var(--space-5)">暂无返工记录</p>
        </div>
      </div>

      <!-- Shipments -->
      <div class="card">
        <div class="card-header"><h3>🚚 发货记录 ({{ (result.shipments||[]).length }})</h3></div>
        <div class="card-body">
          <table v-if="result.shipments && result.shipments.length" class="data-table" style="font-size:var(--text-xs)">
            <thead><tr><th>出库单号</th><th>客户</th><th>状态</th><th>总量</th><th>出库时间</th></tr></thead>
            <tbody>
              <tr v-for="s in result.shipments" :key="s.id">
                <td><code style="font-size:var(--text-xs-alt)">{{ s.shipment_no }}</code></td>
                <td>{{ s.customer || '-' }}</td>
                <td><span class="badge" :class="s.status==='completed'?'badge-success':'badge-info'" style="font-size:var(--text-2xs)">{{ s.status==='completed'?'已出库':'待出库' }}</span></td>
                <td style="text-align:center;font-weight:600">{{ s.total_quantity }}</td>
                <td style="font-size:var(--text-xs-alt)">{{ s.completed_at || '-' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else style="text-align:center;color:var(--text-placeholder);padding:var(--space-5)">暂无发货记录</p>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-else class="card">
      <div class="card-body" style="text-align:center;padding:60px">
        <div style="font-size:48px;margin-bottom:var(--space-4)">🔍</div>
        <div style="font-size:var(--text-lg);color:var(--text-placeholder)">输入产品序列号或订单号查询完整追溯链</div>
        <div style="font-size:var(--text-sm);color:var(--text-placeholder);margin-top:8px">🔢 序列号追溯：产品信息 → 报工时间线 → 完整生命周期<br>📋 订单号追溯：产品列表 → 全部报工 → 质检/物料/入库/发货</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@media print {
  body * { visibility: hidden; }
  .card, .card * { visibility: visible; }
  .card { break-inside: avoid; margin-bottom: 12px !important; }
  .btn, .timeline div[style*="min-width:60px"] > div:last-child { display: none !important; }
  .modal-overlay { display: none !important; }
}
</style>

<script>
import { ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export default {
  setup() {
    const traceCode = ref('')
    const traceMode = ref('serial')
    const searching = ref(false)
    const result = ref(null)

    // Trace history (localStorage)
    const HISTORY_KEY = 'qr_trace_history'
    const traceHistory = ref(JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'))

    function saveHistory(code, mode) {
      const list = traceHistory.value.filter(h => !(h.code === code && h.mode === mode))
      list.unshift({ code, mode })
      if (list.length > 10) list.pop()
      traceHistory.value = list
      localStorage.setItem(HISTORY_KEY, JSON.stringify(list))
    }

    function getTimeDiff(idx, records) {
      if (idx === 0 || !records) return ''
      const prev = records[idx - 1]
      const curr = records[idx]
      if (!prev || !curr || !prev.created_at || !curr.created_at) return ''
      const t1 = new Date(prev.created_at).getTime()
      const t2 = new Date(curr.created_at).getTime()
      const diff = t2 - t1
      if (isNaN(diff) || diff < 0) return ''
      const hours = Math.floor(diff / 3600000)
      const mins = Math.floor((diff % 3600000) / 60000)
      if (hours > 0) return hours + 'h' + (mins > 0 ? mins + 'm' : '')
      return mins + 'min'
    }

    async function doTrace() {
      const code = traceCode.value.trim()
      if (!code) { showToast(traceMode.value==='serial'?'请输入产品序列号':'请输入订单号','error'); return }
      searching.value = true
      try {
        const d = traceMode.value === 'serial'
          ? await api.trace(code)
          : await api.traceByOrder(code)
        result.value = d
        saveHistory(code, traceMode.value)
      } catch(e) {
        showToast(e.message || '查询失败','error')
        result.value = null
      } finally {
        searching.value = false
      }
    }

    return { traceCode, traceMode, searching, result, doTrace, traceHistory, getTimeDiff }
  }
}
</script>
