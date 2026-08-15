<template>
  <section class="release-panel" aria-label="主数据成组发布">
    <header class="release-header">
      <div><h3>成组发布</h3><p>工序、路线和工价按同一批次原子切换</p></div>
      <div class="release-header-actions">
        <select v-model="statusFilter" class="form-input" aria-label="发布状态" @change="reload">
          <option value="">全部状态</option>
          <option value="draft">草稿</option>
          <option value="pending_approval">待审批</option>
          <option value="published">已发布</option>
          <option value="rejected">已驳回</option>
        </select>
        <button type="button" class="btn btn-default btn-sm" :disabled="loading" @click="reload">刷新</button>
        <button v-if="canCreate" type="button" class="btn btn-primary btn-sm" @click="openCreate">新建发布批次</button>
      </div>
    </header>

    <div class="release-layout">
      <aside class="batch-list" aria-label="发布批次列表">
        <button
          v-for="batch in batches"
          :key="batch.id"
          type="button"
          class="batch-row"
          :class="{ active: selectedBatch?.id === batch.id }"
          @click="selectBatch(batch.id)"
        >
          <span><strong>{{ batch.release_no }}</strong><small>{{ batch.revision_reason }}</small></span>
          <span class="release-status" :class="`status-${batch.status}`">{{ releaseStatusLabel(batch.status) }}</span>
        </button>
        <div v-if="!loading && !batches.length" class="release-empty">暂无发布批次</div>
      </aside>

      <main class="batch-detail">
        <div v-if="loading && !selectedBatch" class="release-empty">正在加载发布批次...</div>
        <div v-else-if="!selectedBatch" class="release-empty">选择一个批次查看依赖和差异</div>
        <template v-else>
          <div class="batch-title">
            <div><code>{{ selectedBatch.release_no }}</code><h4>{{ selectedBatch.revision_reason }}</h4></div>
            <span class="release-status" :class="`status-${selectedBatch.status}`">{{ releaseStatusLabel(selectedBatch.status) }}</span>
          </div>

          <div class="dependency-summary">
            <span>工序版本<strong>{{ selectedBatch.process_versions?.length || 0 }}</strong></span>
            <span>路线版本<strong>{{ selectedBatch.route_versions?.length || 0 }}</strong></span>
            <span>工价版本<strong>{{ selectedBatch.price_versions?.length || 0 }}</strong></span>
          </div>

          <section class="dependency-section">
            <h5>工序版本依赖</h5>
            <div v-if="!selectedBatch.process_versions?.length" class="dependency-empty">本批次不包含工序修订</div>
            <div v-for="version in selectedBatch.process_versions" :key="version.id" class="dependency-item">
              <div class="dependency-line"><strong>{{ version.name }}</strong><span>V{{ version.version }} · {{ versionStatus(version.status) }}</span></div>
              <VersionDiffPanel :before="version.comparison_base" :after="version" />
            </div>
          </section>

          <section class="dependency-section">
            <h5>路线版本和节点依赖</h5>
            <div v-if="!selectedBatch.route_versions?.length" class="dependency-empty">本批次不包含路线修订</div>
            <div v-for="route in selectedBatch.route_versions" :key="route.id" class="dependency-item">
              <div class="dependency-line"><strong>{{ route.name }}</strong><span>V{{ route.version }} · {{ versionStatus(route.status) }}</span></div>
              <ol class="route-dependencies">
                <li v-for="node in route.items || []" :key="`${route.id}-${node.process_version_id}`">
                  <span>{{ node.process_name_snapshot || node.process_id }} V{{ node.process_version || node.process_version_id }}</span>
                  <span>{{ node.required_audit ? '需要审批' : '无需节点审批' }}</span>
                </li>
              </ol>
              <VersionDiffPanel :before="route.comparison_base" :after="route" />
            </div>
          </section>

          <section class="dependency-section">
            <h5>工价版本依赖</h5>
            <div v-if="!selectedBatch.price_versions?.length" class="dependency-empty">本批次未包含新工价，可选择已批准工价或登记不适用原因</div>
            <div v-for="price in selectedBatch.price_versions" :key="price.id" class="price-line">
              <span>工序 {{ price.process_id }} · 路线版本 {{ price.route_version_id }}</span>
              <strong>{{ money(price.normal_unit_price_micros) }}</strong>
              <span>{{ priceStatus(price.status) }}</span>
            </div>
          </section>

          <section v-if="selectedBatch.status === 'pending_approval'" class="dependency-section disposition-section">
            <h5>发布工价处置</h5>
            <div v-for="node in uniqueNodes" :key="node.process_id" class="disposition-row">
              <div><strong>{{ node.process_name_snapshot || `工序 ${node.process_id}` }}</strong><small>绑定工序版本 {{ node.process_version_id }}</small></div>
              <select v-model="dispositions[node.process_id].disposition" class="form-input">
                <option value="">请选择处置</option>
                <option value="price_version">使用精确工价版本</option>
                <option value="not_applicable">不适用计件工价</option>
              </select>
              <select v-if="dispositions[node.process_id].disposition === 'price_version'" v-model.number="dispositions[node.process_id].price_version_id" class="form-input">
                <option :value="null">请选择工价版本</option>
                <option v-for="price in exactPrices(node)" :key="price.id" :value="price.id">#{{ price.id }} · {{ money(price.normal_unit_price_micros) }} · {{ priceStatus(price.status) }}</option>
              </select>
              <input v-else-if="dispositions[node.process_id].disposition === 'not_applicable'" v-model="dispositions[node.process_id].reason" class="form-input" placeholder="填写不适用依据">
            </div>
            <p v-if="dispositionError" class="release-error">{{ dispositionError }}</p>
          </section>

          <p v-if="operationError" class="release-error">{{ operationError }}</p>
          <footer class="batch-actions">
            <button v-if="selectedBatch.status === 'draft' && canSubmit" type="button" class="btn btn-primary" :disabled="busy" @click="submitSelected">提交审批</button>
            <button v-if="selectedBatch.status === 'pending_approval' && canReject" type="button" class="btn btn-default" :disabled="busy" @click="rejectSelected">驳回</button>
            <button v-if="selectedBatch.status === 'pending_approval' && canApprove" type="button" class="btn btn-primary" :disabled="busy || !approvalReady" @click="approveSelected">批准并原子发布</button>
          </footer>
        </template>
      </main>
    </div>

    <div v-if="showCreate" class="modal-overlay" @click.self="showCreate = false">
      <div class="modal release-modal">
        <div class="modal-header"><span>新建成组发布批次</span><button class="modal-close" type="button" aria-label="关闭" @click="showCreate = false">×</button></div>
        <div class="modal-body create-form">
          <label>发布批次号<input v-model="createForm.release_no" class="form-input" placeholder="MDR-YYYYMMDD-NN"></label>
          <label>发布原因<textarea v-model="createForm.revision_reason" class="form-input" rows="3"></textarea></label>
          <div class="create-scope">
            <span>工序版本 {{ createForm.process_version_ids.length }}</span>
            <span>路线版本 {{ createForm.route_version_ids.length }}</span>
            <span>工价版本 {{ createForm.price_version_ids.length }}</span>
          </div>
        </div>
        <div class="modal-footer"><button class="btn btn-default" type="button" @click="showCreate = false">取消</button><button class="btn btn-primary" type="button" :disabled="busy" @click="createSelected">创建草稿批次</button></div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

import VersionDiffPanel from '@/components/master-data/VersionDiffPanel.vue'
import { releaseStatusLabel, useMasterDataReleases } from '@/composables/useMasterDataReleases.js'
import { routeVersionStatusLabel } from '@/composables/useRouteVersions.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

const props = defineProps({
  defaultRouteVersion: { type: Object, default: null },
  defaultPriceVersions: { type: Array, default: () => [] },
})
const emit = defineEmits(['published'])

const state = useMasterDataReleases()
const { batches, selectedBatch, loading, busy, operationError } = state
const statusFilter = ref('')
const showCreate = ref(false)
const dispositions = reactive({})
const dispositionError = ref('')
const createForm = reactive({ release_no: '', revision_reason: '', process_version_ids: [], route_version_ids: [], price_version_ids: [] })

const canCreate = computed(() => can('master_data_releases:create'))
const canSubmit = computed(() => can('master_data_releases:submit'))
const canApprove = computed(() => can('master_data_releases:approve'))
const canReject = computed(() => can('master_data_releases:reject'))
const uniqueNodes = computed(() => {
  const byProcess = new Map()
  ;(selectedBatch.value?.route_versions || []).forEach(route => {
    ;(route.items || []).forEach(node => { if (!byProcess.has(Number(node.process_id))) byProcess.set(Number(node.process_id), node) })
  })
  return [...byProcess.values()]
})
const approvalReady = computed(() => {
  try {
    state.validatePriceDispositions(Object.values(dispositions))
    return true
  } catch (_) {
    return false
  }
})

watch(uniqueNodes, nodes => {
  Object.keys(dispositions).forEach(key => delete dispositions[key])
  nodes.forEach(node => {
    dispositions[node.process_id] = { process_id: Number(node.process_id), disposition: '', price_version_id: null, reason: '' }
  })
}, { immediate: true })

function versionStatus(status) { return routeVersionStatusLabel(status) }
function priceStatus(status) { return ({ draft: '草稿', approved: '已批准', retired: '已结束' }[status] || status || '-') }
function money(micros) { return Number.isFinite(Number(micros)) ? `¥${(Number(micros) / 1000000).toFixed(4)}` : '-' }
function exactPrices(node) {
  return (selectedBatch.value?.price_versions || []).filter(price => Number(price.process_version_id) === Number(node.process_version_id))
}

async function reload() {
  try {
    await state.loadBatches(statusFilter.value)
    if (selectedBatch.value?.id) await state.loadBatch(selectedBatch.value.id)
  } catch (error) {
    showToast(error.message || '发布批次加载失败', 'error')
  }
}

async function selectBatch(batchId) {
  try { await state.loadBatch(batchId) } catch (error) { showToast(error.message || '批次详情加载失败', 'error') }
}

function openCreate() {
  const route = props.defaultRouteVersion
  createForm.release_no = `MDR-${new Date().toISOString().slice(0, 10).replaceAll('-', '')}-01`
  createForm.revision_reason = route ? `发布路线 ${route.name} V${route.version}` : ''
  createForm.route_version_ids = route?.id ? [Number(route.id)] : []
  createForm.process_version_ids = [...new Set((route?.items || []).filter(node => node.process_version_status !== 'published').map(node => Number(node.process_version_id)))]
  createForm.price_version_ids = props.defaultPriceVersions.filter(price => price.status === 'draft').map(price => Number(price.id))
  showCreate.value = true
}

async function createSelected() {
  try {
    await state.createBatch(createForm)
    showCreate.value = false
    showToast('成组发布批次已创建')
  } catch (error) { showToast(error.message || '创建发布批次失败', 'error') }
}

async function submitSelected() {
  try { await state.submitBatch(); showToast('发布批次已提交审批') } catch (error) { showToast(error.message || '提交失败', 'error') }
}

async function approveSelected() {
  dispositionError.value = ''
  try {
    await state.approveBatch(Object.values(dispositions))
    showToast('主数据批次已原子发布')
    emit('published', selectedBatch.value)
  } catch (error) {
    dispositionError.value = error.message || '批准失败'
    showToast(dispositionError.value, 'error')
  }
}

async function rejectSelected() {
  const reason = globalThis.prompt?.('请输入驳回原因')
  if (!reason) return
  try { await state.rejectBatch(reason); showToast('发布批次已驳回') } catch (error) { showToast(error.message || '驳回失败', 'error') }
}

onMounted(reload)
</script>

<style scoped>
.release-panel { min-width:0; }
.release-header { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; padding-bottom:14px; border-bottom:1px solid var(--border-color); }
.release-header h3 { margin:0; font-size:18px; letter-spacing:0; }
.release-header p { margin:4px 0 0; color:var(--text-placeholder); font-size:12px; }
.release-header-actions { display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
.release-header-actions select { width:130px; }
.release-layout { display:grid; grid-template-columns:250px minmax(0, 1fr); min-height:520px; }
.batch-list { padding:12px 12px 12px 0; border-right:1px solid var(--border-color); }
.batch-row { width:100%; display:flex; align-items:center; justify-content:space-between; gap:8px; padding:10px; margin-bottom:6px; border:1px solid transparent; border-radius:5px; background:transparent; text-align:left; cursor:pointer; }
.batch-row:hover, .batch-row.active { border-color:var(--border-color); background:var(--bg-hover); }
.batch-row span:first-child { min-width:0; display:grid; gap:3px; }
.batch-row small { color:var(--text-placeholder); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.batch-detail { min-width:0; padding:16px 0 16px 18px; }
.batch-title, .dependency-line { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.batch-title h4 { margin:5px 0 0; font-size:15px; letter-spacing:0; }
.release-status { flex-shrink:0; padding:3px 8px; border:1px solid var(--border-color); border-radius:4px; font-size:12px; }
.status-published { color:var(--success); border-color:var(--success); }
.status-pending_approval { color:var(--warning-dark); border-color:var(--warning); }
.status-rejected { color:var(--danger); border-color:var(--danger); }
.dependency-summary { display:flex; gap:24px; padding:14px 0; margin-top:12px; border-top:1px solid var(--border-color); border-bottom:1px solid var(--border-color); }
.dependency-summary span { display:flex; align-items:baseline; gap:7px; color:var(--text-secondary); font-size:12px; }
.dependency-summary strong { color:var(--text-primary); font-size:20px; }
.dependency-section { padding:16px 0; border-bottom:1px solid var(--border-color); }
.dependency-section h5 { margin:0 0 10px; font-size:14px; letter-spacing:0; }
.dependency-item + .dependency-item { margin-top:16px; padding-top:16px; border-top:1px dashed var(--border-color); }
.dependency-line span { color:var(--text-placeholder); font-size:12px; }
.route-dependencies { margin:10px 0 14px; padding-left:22px; }
.route-dependencies li { display:flex; justify-content:space-between; gap:12px; padding:5px 0; font-size:13px; }
.route-dependencies li span:last-child { color:var(--text-placeholder); }
.price-line { display:grid; grid-template-columns:minmax(0, 1fr) 120px 90px; gap:12px; padding:7px 0; font-size:13px; }
.dependency-empty, .release-empty { padding:30px 10px; color:var(--text-placeholder); text-align:center; }
.disposition-row { display:grid; grid-template-columns:minmax(150px, 1fr) minmax(150px, .8fr) minmax(180px, 1.2fr); gap:10px; align-items:center; padding:8px 0; }
.disposition-row > div { display:grid; gap:2px; }
.disposition-row small { color:var(--text-placeholder); }
.release-error { color:var(--danger); font-size:13px; }
.batch-actions { display:flex; justify-content:flex-end; gap:8px; padding-top:16px; }
.create-form { display:grid; gap:14px; }
.create-form label { display:grid; gap:6px; }
.create-scope { display:flex; gap:18px; padding:10px 0; color:var(--text-secondary); font-size:13px; }
.release-modal { max-width:560px; }
@media (max-width:900px) { .release-layout { grid-template-columns:1fr; } .batch-list { border-right:0; border-bottom:1px solid var(--border-color); padding-right:0; max-height:220px; overflow:auto; } .batch-detail { padding-left:0; } }
@media (max-width:680px) { .release-header { flex-direction:column; } .release-header-actions { justify-content:flex-start; } .disposition-row { grid-template-columns:1fr; } }
</style>
