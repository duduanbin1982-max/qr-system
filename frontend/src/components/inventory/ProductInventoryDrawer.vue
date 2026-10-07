<template>
  <Teleport to="body">
    <div v-if="open" class="inventory-drawer-backdrop" @click.self="$emit('close')">
      <aside class="inventory-drawer" role="dialog" aria-modal="true" aria-labelledby="product-drawer-title">
        <header><div><h3 id="product-drawer-title">{{ product?.product_code || '产品库存详情' }}</h3><p>{{ product?.product_name || '' }}</p></div><button class="drawer-close" aria-label="关闭" @click="$emit('close')">×</button></header>
        <main>
          <div v-if="!details" class="product-empty">加载中…</div>
          <template v-else>
            <section><h4>兼容分组</h4><div v-for="group in details.compatibility_groups || []" :key="group.compatibility_key" class="compatibility-card"><strong>{{ group.specification || '标准规格' }}</strong><span>可用 {{ group.available_quantity ?? 0 }}</span></div></section>
            <section><h4>库存明细</h4><div v-for="item in details.inventory_items || []" :key="item.inventory_id" class="detail-row"><code>{{ item.order_no || '无订单' }}</code><span>{{ item.location || '未指定库位' }}</span><span>可用 {{ item.available_quantity ?? 0 }}</span></div></section>
            <section v-if="details.identity_warnings?.length" class="warning-block"><h4>身份异常</h4><p v-for="warning in details.identity_warnings" :key="warning.inventory_id">⚠️ 库存 {{ warning.inventory_id }}：{{ warning.reason }}</p></section>
            <section v-if="capabilities?.allocation_preview_enabled" class="allocation-block">
              <h4>来源分配预览</h4>
              <div class="allocation-form">
                <label>兼容分组<select v-model="compatibilityKey"><option value="">自动（仅单一分组）</option><option v-for="group in details.compatibility_groups || []" :key="group.compatibility_key" :value="group.compatibility_key">{{ group.specification || '标准规格' }} · 可用 {{ group.available_quantity }}</option></select></label>
                <label>数量<input v-model.number="allocationQuantity" type="number" min="0.001" step="0.001"></label>
                <label>模式<select v-model="allocationMode"><option value="fifo">FIFO 自动</option><option value="manual">人工指定</option></select></label>
                <label class="reason-field">原因<input v-model="allocationReason" placeholder="出库用途或备注"></label>
              </div>
              <div v-if="allocationMode === 'manual'" class="source-list">
                <label v-for="item in compatibleItems" :key="item.inventory_id"><input v-model="selectedInventoryIds" type="checkbox" :value="item.inventory_id"> {{ item.order_no || '无订单' }} / {{ item.location || '未指定库位' }} · 可用 {{ item.available_quantity }}</label>
              </div>
              <p v-if="allocationError" class="allocation-error">{{ allocationError }}</p>
              <div class="allocation-actions"><button class="btn btn-default" :disabled="allocationLoading" @click="previewAllocation">{{ allocationLoading ? '计算中…' : '生成只读预览' }}</button><button v-if="allocationPreview && capabilities?.cross_order_outbound_enabled" class="btn btn-warning" :disabled="allocationLoading" @click="confirmOutbound">确认正式出库</button></div>
              <div v-if="allocationPreview" class="allocation-result"><strong>预览摘要</strong><span>可用 {{ allocationPreview.available_quantity }}，分配 {{ allocationPreview.allocated_quantity }}</span><code>{{ allocationPreview.preview_digest }}</code><ol><li v-for="item in allocationPreview.items" :key="item.sequence_no">{{ item.order_no || '无订单' }} · {{ item.location || '未指定库位' }} · {{ item.allocated_quantity }}</li></ol></div>
            </section>
            <section v-if="capabilities?.cross_order_outbound_enabled" class="allocation-block">
              <h4>分配历史</h4>
              <p v-if="historyLoading">加载中…</p><p v-else-if="!history.length">暂无正式分配记录</p>
              <div v-for="run in history" :key="run.id" class="history-row"><span>#{{ run.id }} · {{ run.mode === 'reversal' ? '撤销' : '正式出库' }} · {{ run.requested_quantity }}</span><button v-if="run.mode !== 'reversal'" class="btn btn-default btn-sm" @click="reverseRun(run)">撤销</button></div>
            </section>
          </template>
        </main>
        <footer>
          <button v-if="canExport" class="btn btn-default" type="button" @click="exportDetails">导出详情</button>
          <button class="btn btn-default" type="button" @click="$emit('close')">关闭</button>
        </footer>
      </aside>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '@/lib/api.js'

const props = defineProps({ open: Boolean, product: { type: Object, default: null }, details: { type: Object, default: null }, capabilities: { type: Object, default: () => ({}) }, canExport: Boolean })
defineEmits(['close'])
const compatibilityKey = ref('')
const allocationQuantity = ref(1)
const allocationMode = ref('fifo')
const allocationReason = ref('')
const selectedInventoryIds = ref([])
const allocationPreview = ref(null)
const allocationError = ref('')
const allocationLoading = ref(false)
const history = ref([])
const historyLoading = ref(false)
const compatibleItems = computed(() => (props.details?.inventory_items || []).filter(item => !compatibilityKey.value || item.compatibility_key === compatibilityKey.value))
watch(() => props.product?.product_id, () => { compatibilityKey.value = ''; allocationPreview.value = null; selectedInventoryIds.value = []; allocationError.value = ''; loadHistory() })
async function loadHistory() {
  if (!props.product?.product_id || !props.capabilities?.cross_order_outbound_enabled) return
  historyLoading.value = true
  try { history.value = (await api.domains.inventory.listAllocationRuns({ product_id: props.product.product_id, limit: 20 })).items || [] } catch (_) { history.value = [] }
  finally { historyLoading.value = false }
}
async function previewAllocation() {
  allocationLoading.value = true; allocationError.value = ''
  try {
    allocationPreview.value = await api.domains.inventory.allocationPreview(props.product.product_id, { quantity: allocationQuantity.value, mode: allocationMode.value, compatibility_key: compatibilityKey.value, selected_inventory_ids: selectedInventoryIds.value, reason: allocationReason.value })
  } catch (error) { allocationError.value = error.message || '无法生成分配预览' }
  finally { allocationLoading.value = false }
}
async function confirmOutbound() {
  if (!allocationPreview.value) return
  allocationLoading.value = true; allocationError.value = ''
  try {
    await api.domains.inventory.productGroupOutbound(props.product.product_id, { quantity: allocationQuantity.value, mode: allocationMode.value, compatibility_key: allocationPreview.value.compatibility_key, selected_inventory_ids: selectedInventoryIds.value, preview_digest: allocationPreview.value.preview_digest, idempotency_key: `inventory-ui-${Date.now()}`, reason: allocationReason.value })
    allocationPreview.value = null
    await loadHistory()
    window.alert('出库成功')
  } catch (error) { allocationError.value = error.message || '正式出库失败' }
  finally { allocationLoading.value = false }
}
async function reverseRun(run) {
  if (!window.confirm(`确认撤销分配运行 #${run.id}？`)) return
  allocationLoading.value = true; allocationError.value = ''
  try { await api.domains.inventory.reverseAllocation(run.id, { idempotency_key: `inventory-ui-reverse-${run.id}-${Date.now()}`, reason: '库存产品视图撤销' }); await loadHistory(); window.alert('撤销成功') }
  catch (error) { allocationError.value = error.message || '撤销失败' }
  finally { allocationLoading.value = false }
}
function exportDetails() {
  if (!props.product?.product_id || !props.canExport) return
  window.open(api.domains.inventory.productGroupDetailsExportUrl(props.product.product_id, { compatibility_key: compatibilityKey.value }), '_blank')
}
</script>

<style scoped>
.inventory-drawer-backdrop { position:fixed; inset:0; z-index:1000; background:rgba(15,23,42,.35); display:flex; justify-content:flex-end; }
.inventory-drawer { width:min(560px, 94vw); height:100%; background:#fff; display:flex; flex-direction:column; box-shadow:-8px 0 24px rgba(15,23,42,.16); }
.inventory-drawer header,.inventory-drawer footer { flex:none; display:flex; align-items:center; justify-content:space-between; padding:18px 22px; border-bottom:1px solid var(--border-light); }
.inventory-drawer footer { border-top:1px solid var(--border-light); border-bottom:0; justify-content:flex-end; }
.inventory-drawer main { flex:1; overflow:auto; padding:22px; }.drawer-close { border:0; background:none; font-size:28px; cursor:pointer; color:var(--text-muted); }
.inventory-drawer h3 { margin:0; }.inventory-drawer h4 { margin:0 0 10px; }.inventory-drawer section { margin-bottom:22px; }
.compatibility-card,.detail-row { display:flex; justify-content:space-between; gap:12px; padding:12px; border:1px solid var(--border-light); border-radius:8px; margin-bottom:8px; }
.warning-block { color:var(--danger); background:var(--danger-light,#fff1f2); padding:12px; border-radius:8px; }
.allocation-block { border:1px solid var(--border-light); border-radius:10px; padding:14px; background:var(--bg-table-stripe,#f8fafc); }
.allocation-form { display:grid; grid-template-columns:2fr 1fr 1fr; gap:8px; }.allocation-form label { display:flex; flex-direction:column; gap:4px; font-size:12px; color:var(--text-muted); }.allocation-form select,.allocation-form input { min-height:34px; border:1px solid var(--border-light); border-radius:6px; padding:5px 8px; background:#fff; }.reason-field { grid-column:1 / -1; }
.source-list { display:flex; flex-direction:column; gap:6px; margin:10px 0; font-size:12px; }.allocation-actions { display:flex; gap:8px; margin-top:10px; }.allocation-result { margin-top:12px; display:flex; flex-direction:column; gap:5px; font-size:12px; }.allocation-result code { word-break:break-all; color:var(--text-muted); }.allocation-error { color:var(--danger); font-size:12px; }
.history-row { display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-bottom:1px solid var(--border-light); font-size:12px; }
@media (max-width: 700px) { .inventory-drawer { width:100vw; } }
</style>
