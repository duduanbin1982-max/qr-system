<template>
  <div class="route-page">
    <div class="summary-bar route-summary">
      <div class="summary-item"><div><div class="s-val">{{ summary.total_routes || total }}</div><div class="s-label">路线总数</div></div></div>
      <div class="summary-item"><div><div class="s-val text-primary">{{ summary.category_counts?.['结构件'] || 0 }}</div><div class="s-label">结构件路线</div></div></div>
      <div class="summary-item"><div><div class="s-val text-success">{{ summary.category_counts?.['机加工'] || 0 }}</div><div class="s-label">机加工路线</div></div></div>
      <div class="summary-item"><div><div class="s-val text-warning">{{ summary.process_nodes_total || 0 }}</div><div class="s-label">当前节点</div></div></div>
      <div class="summary-note">路线编码保持稳定，业务变更通过修订版生效。</div>
    </div>

    <div class="cat-tabs" aria-label="路线分类">
      <button class="cat-tab cat-tab-all" :class="{ active: activeCategory === 'all' }" @click="switchCategory('all')">全部路线</button>
      <button class="cat-tab cat-tab-struct" :class="{ active: activeCategory === '结构件' }" @click="switchCategory('结构件')">结构件路线</button>
      <button class="cat-tab cat-tab-mach" :class="{ active: activeCategory === '机加工' }" @click="switchCategory('机加工')">机加工路线</button>
    </div>

    <div class="toolbar-row route-toolbar">
      <div class="search-field">
        <input v-model="searchKeyword" class="form-input" placeholder="搜索路线名称或稳定编码" @keyup.enter="searchAndLoad">
        <button v-if="searchKeyword" type="button" class="clear-search" title="清空" @click="clearSearch">×</button>
      </div>
      <button type="button" class="btn btn-default btn-sm" @click="searchAndLoad">搜索</button>
      <button v-if="canViewReleases" type="button" class="btn btn-default btn-sm" @click="showReleaseModal = true">成组发布</button>
      <button v-if="canCreateVersion" type="button" class="btn btn-primary btn-sm" @click="openCreate">新建路线</button>
    </div>

    <div class="card route-list-card">
      <div class="card-header route-card-header"><h3>工序路线</h3><span>共 {{ total }} 项</span></div>
      <div class="card-body">
        <div class="table-wrap">
          <div v-if="loading" class="loading-state">加载中...</div>
          <table v-else-if="routes.length" class="data-table route-table">
            <thead><tr><th>稳定编码</th><th>路线名称</th><th>分类</th><th>当前版本</th><th>生命周期</th><th>修订状态</th><th>节点</th><th>引用</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="route in routes" :key="route.id">
                <td><code>{{ route.route_code || '-' }}</code></td>
                <td><button type="button" class="route-name-link" @click="openDetail(route)">{{ route.name }}</button><small>{{ route.description || '-' }}</small></td>
                <td><span class="badge" :class="route.category === '结构件' ? 'badge-info' : 'badge-warning'">{{ route.category }}</span></td>
                <td>{{ route.route_version ? `V${route.route_version}` : '未发布' }}</td>
                <td><span class="status-pill" :class="`lifecycle-${route.lifecycle_status || 'active'}`">{{ routeLifecycleLabel(route.lifecycle_status || 'active') }}</span></td>
                <td><span class="status-pill" :class="`version-${route.open_version_status || route.version_status || 'draft'}`">{{ routeVersionStatusLabel(route.open_version_status || route.version_status || 'draft') }}</span></td>
                <td>{{ route.processes?.length || 0 }}</td>
                <td><span class="reference-count">订单 {{ route.used_orders || 0 }} / 产品 {{ route.used_products || 0 }}</span></td>
                <td>
                  <div class="row-actions">
                    <button type="button" class="btn btn-default btn-sm" @click="openDetail(route)">查看版本</button>
                    <button v-if="canCreateVersion" type="button" class="btn btn-default btn-sm" :data-testid="`route-revision-${route.id}`" :disabled="busy" @click="startRevisionFromRow(route)">创建修订版</button>
                    <button v-if="canRetire && (route.lifecycle_status || 'active') === 'active'" type="button" class="btn btn-warning btn-sm" :disabled="busy" @click="startLifecycleFromRow(route, 'retire')">申请退休</button>
                    <button v-if="canReactivate && route.lifecycle_status === 'retired'" type="button" class="btn btn-default btn-sm" :disabled="busy" @click="startLifecycleFromRow(route, 'reactivate')">申请重新启用</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty"><div class="empty-text">暂无工序路线</div></div>
        </div>
        <div v-if="total > pageSize" class="pagination-bar">
          <button class="btn btn-sm btn-default" :disabled="page <= 1" @click="previousPage">上一页</button>
          <span>第 {{ page }} / {{ Math.ceil(total / pageSize) }} 页（共 {{ total }} 条）</span>
          <button class="btn btn-sm btn-default" :disabled="page * pageSize >= total" @click="nextPage">下一页</button>
        </div>
      </div>
    </div>

    <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
      <div class="modal route-create-modal">
        <div class="modal-header"><span>新建路线 V1 草稿</span><button type="button" class="modal-close" aria-label="关闭" @click="showCreateModal = false">×</button></div>
        <div class="modal-body">
          <RouteVersionEditor v-model="createForm" :process-options="processOptions" />
          <label class="reason-field">制单原因<textarea v-model="createForm.revision_reason" class="form-input" rows="3" placeholder="填写建立路线的业务依据"></textarea></label>
        </div>
        <div class="modal-footer"><button type="button" class="btn btn-default" :disabled="busy" @click="showCreateModal = false">取消</button><button type="button" class="btn btn-primary" :disabled="busy" @click="saveNewRoute">创建 V1 草稿</button></div>
      </div>
    </div>

    <div v-if="showDetailModal" class="modal-overlay" @click.self="closeDetail">
      <div class="modal route-detail-modal">
        <div class="modal-header detail-header">
          <div><code>{{ root?.route_code || selectedRoute?.route_code || '-' }}</code><span>{{ selectedVersion?.name || selectedRoute?.name }}</span></div>
          <button type="button" class="modal-close" aria-label="关闭" @click="closeDetail">×</button>
        </div>
        <div class="modal-body detail-body">
          <div v-if="loadingDetail" class="loading-state">正在读取路线版本...</div>
          <template v-else-if="selectedVersion">
            <div class="detail-toolbar">
              <div class="version-switcher" aria-label="版本切换">
                <button v-if="currentVersion" type="button" class="version-switch" :class="{ active: selectedVersion.id === currentVersion.id }" @click="chooseVersion(currentVersion)">当前版本 V{{ currentVersion.version }}</button>
                <button v-if="openVersion" type="button" class="version-switch" :class="{ active: selectedVersion.id === openVersion.id }" @click="chooseVersion(openVersion)">{{ routeVersionStatusLabel(openVersion.status) }} V{{ openVersion.version }}</button>
                <select v-if="historicalVersions.length" :value="historicalSelection" class="form-input history-select" aria-label="历史版本" @change="chooseHistory($event.target.value)">
                  <option value="">历史版本</option>
                  <option v-for="version in historicalVersions" :key="version.id" :value="version.id">V{{ version.version }} · {{ routeVersionStatusLabel(version.status) }}</option>
                </select>
              </div>
              <div class="detail-identities"><span>{{ routeLifecycleLabel(root?.lifecycle_status) }}</span><span>{{ routeVersionStatusLabel(selectedVersion.status) }}</span></div>
            </div>

            <div v-if="selectedVersion.status !== 'draft'" class="immutable-note">该版本内容已冻结，节点和审批要求只能通过新修订版调整。</div>
            <RouteVersionEditor v-model="editorForm" :readonly="selectedVersion.status !== 'draft'" :process-options="processOptions" />

            <section class="coverage-section">
              <div class="section-heading"><div><h4>工价覆盖</h4><span>按路线版本和工序版本精确匹配</span></div><span>{{ coveredNodeCount }} / {{ coverageRows.length }} 已覆盖</span></div>
              <div class="table-wrap">
                <table class="data-table coverage-table">
                  <thead><tr><th>节点</th><th>绑定版本</th><th>覆盖状态</th><th>可用工价版本</th></tr></thead>
                  <tbody>
                    <tr v-for="row in coverageRows" :key="row.process_version_id">
                      <td>{{ row.process_name_snapshot || row.process_id }}</td>
                      <td>V{{ row.process_version || row.process_version_id }}</td>
                      <td><span :class="exactApprovedPrice(row) ? 'text-success' : 'text-warning'">{{ exactApprovedPrice(row) ? '已批准覆盖' : row.price_versions.length ? '有草稿待处理' : '缺少精确工价' }}</span></td>
                      <td><span v-if="row.price_versions.length">{{ row.price_versions.map(price => `#${price.id} ${priceStatus(price.status)}`).join('、') }}</span><span v-else>-</span></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <div class="detail-insights">
              <VersionDiffPanel :before="comparisonBase" :after="selectedVersion" />
              <ImpactSummaryPanel :impact="impact" :loading="loadingContext" :error="contextError" />
            </div>
            <p v-if="operationError" class="operation-error">{{ operationError }}</p>
          </template>
        </div>
        <div v-if="selectedVersion" class="modal-footer detail-actions">
          <button v-if="canCreateVersion && !openVersion && currentVersion" type="button" class="btn btn-default" :disabled="busy" @click="openCommand('revision')">创建修订版</button>
          <button v-if="selectedVersion.status === 'draft' && canCreateVersion" type="button" class="btn btn-default" :disabled="busy" @click="saveDraft">保存草稿</button>
          <button v-if="selectedVersion.status === 'draft' && canSubmit" type="button" class="btn btn-primary" :disabled="busy" @click="submitVersion">提交审批</button>
          <button v-if="selectedVersion.status === 'pending_approval' && canReject" type="button" class="btn btn-default" :disabled="busy" @click="openCommand('reject')">驳回</button>
          <button v-if="selectedVersion.status === 'pending_approval' && canApprove" type="button" class="btn btn-primary" :disabled="busy" @click="openApproval">批准发布</button>
          <button v-if="canViewReleases" type="button" class="btn btn-default" @click="showReleaseModal = true">加入成组发布</button>
        </div>
      </div>
    </div>

    <div v-if="showCommandModal" class="modal-overlay" @click.self="showCommandModal = false">
      <div class="modal command-modal">
        <div class="modal-header"><span>{{ commandTitle }}</span><button type="button" class="modal-close" aria-label="关闭" @click="showCommandModal = false">×</button></div>
        <div class="modal-body"><label class="reason-field">{{ commandLabel }}<textarea v-model="commandReason" class="form-input" rows="4"></textarea></label></div>
        <div class="modal-footer"><button type="button" class="btn btn-default" @click="showCommandModal = false">取消</button><button type="button" class="btn btn-primary" :disabled="busy" @click="confirmCommand">确认</button></div>
      </div>
    </div>

    <div v-if="showApprovalModal" class="modal-overlay" @click.self="showApprovalModal = false">
      <div class="modal approval-modal">
        <div class="modal-header"><span>路线版本发布确认</span><button type="button" class="modal-close" aria-label="关闭" @click="showApprovalModal = false">×</button></div>
        <div class="modal-body">
          <div v-for="row in coverageRows" :key="row.process_id" class="approval-row">
            <div><strong>{{ row.process_name_snapshot || row.process_id }}</strong><small>工序版本 {{ row.process_version_id }}</small></div>
            <select v-model="approvalDispositions[row.process_id].disposition" class="form-input"><option value="">请选择工价处置</option><option value="price_version">使用精确工价版本</option><option value="not_applicable">不适用计件工价</option></select>
            <select v-if="approvalDispositions[row.process_id].disposition === 'price_version'" v-model.number="approvalDispositions[row.process_id].price_version_id" class="form-input"><option :value="null">请选择版本</option><option v-for="price in row.price_versions" :key="price.id" :value="price.id">#{{ price.id }} · {{ priceStatus(price.status) }}</option></select>
            <input v-else-if="approvalDispositions[row.process_id].disposition === 'not_applicable'" v-model="approvalDispositions[row.process_id].reason" class="form-input" placeholder="填写不适用原因">
          </div>
        </div>
        <div class="modal-footer"><button type="button" class="btn btn-default" @click="showApprovalModal = false">取消</button><button type="button" class="btn btn-primary" :disabled="busy" @click="approveVersion">确认发布</button></div>
      </div>
    </div>

    <div v-if="showReleaseModal" class="modal-overlay" @click.self="showReleaseModal = false">
      <div class="modal release-workbench-modal">
        <div class="modal-header"><span>主数据成组发布</span><button type="button" class="modal-close" aria-label="关闭" @click="showReleaseModal = false">×</button></div>
        <div class="modal-body"><ReleaseBatchPanel :default-route-version="selectedVersion" :default-price-versions="priceVersions" @published="afterBatchPublished" /></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

import ImpactSummaryPanel from '@/components/master-data/ImpactSummaryPanel.vue'
import ReleaseBatchPanel from '@/components/master-data/ReleaseBatchPanel.vue'
import RouteVersionEditor from '@/components/master-data/RouteVersionEditor.vue'
import VersionDiffPanel from '@/components/master-data/VersionDiffPanel.vue'
import {
  routeLifecycleLabel,
  routeVersionStatusLabel,
  useRouteVersions,
} from '@/composables/useRouteVersions.js'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

const state = useRouteVersions()
const {
  selectedRoute, root, selectedVersion, currentVersion, openVersion, historicalVersions,
  comparisonBase, impact, priceVersions, coverageRows, loadingDetail, loadingContext,
  busy, operationError, contextError,
} = state

const routes = ref([])
const processOptions = ref([])
const loading = ref(false)
const searchKeyword = ref('')
const categoryFilter = ref('')
const page = ref(1)
const pageSize = 20
const total = ref(0)
const summary = ref({ total_routes: 0, category_counts: {}, process_nodes_total: 0 })
const showCreateModal = ref(false)
const showDetailModal = ref(false)
const showCommandModal = ref(false)
const showApprovalModal = ref(false)
const showReleaseModal = ref(false)
const commandType = ref('')
const commandReason = ref('')
const editorForm = ref(emptyRoute())
const createForm = ref(emptyRoute(true))
const approvalDispositions = reactive({})

const canCreateVersion = computed(() => can('route_versions:create'))
const canSubmit = computed(() => can('route_versions:submit'))
const canApprove = computed(() => can('route_versions:approve'))
const canReject = computed(() => can('route_versions:reject'))
const canRetire = computed(() => can('process_routes:retire'))
const canReactivate = computed(() => can('process_routes:reactivate'))
const canViewReleases = computed(() => can('master_data_releases:view'))
const activeCategory = computed(() => categoryFilter.value || 'all')
const historicalSelection = computed(() => historicalVersions.value.some(version => version.id === selectedVersion.value?.id) ? selectedVersion.value.id : '')
const coveredNodeCount = computed(() => coverageRows.value.filter(exactApprovedPrice).length)
const commandTitle = computed(() => ({ revision: '创建路线修订版', reject: '驳回路线版本', retire: '申请路线退休', reactivate: '申请重新启用' }[commandType.value] || '路线操作'))
const commandLabel = computed(() => commandType.value === 'revision' ? '修订原因' : commandType.value === 'reject' ? '驳回原因' : '申请原因')

watch(selectedVersion, version => { if (version) editorForm.value = clone(version) }, { deep: true })

function clone(value) { return JSON.parse(JSON.stringify(value || {})) }
function emptyRoute(withReason = false) {
  return { name: '', category: '结构件', description: '', items: [], ...(withReason ? { revision_reason: '' } : {}) }
}
function priceStatus(status) { return ({ draft: '草稿', approved: '已批准', retired: '已结束' }[status] || status || '-') }
function exactApprovedPrice(row) { return row.price_versions?.find(price => price.status === 'approved') || null }

async function load() {
  loading.value = true
  try {
    const payload = await api.domains.processRoutes.listProcessRoutes({
      category: categoryFilter.value,
      search: searchKeyword.value.trim(),
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    routes.value = payload.routes || []
    total.value = payload.total ?? routes.value.length
    summary.value = payload.summary || summary.value
  } catch (error) { showToast(error.message || '路线加载失败', 'error') }
  finally { loading.value = false }
}

async function loadProcesses() {
  try {
    const payload = await api.domains.processes.listProcesses({ selectable: true, limit: 200 })
    processOptions.value = payload.processes || []
  } catch (error) { showToast(error.message || '工序版本选项加载失败', 'error') }
}

function switchCategory(category) { categoryFilter.value = category === 'all' ? '' : category; page.value = 1; load() }
function searchAndLoad() { page.value = 1; load() }
function clearSearch() { searchKeyword.value = ''; searchAndLoad() }
function previousPage() { if (page.value > 1) { page.value -= 1; load() } }
function nextPage() { if (page.value * pageSize < total.value) { page.value += 1; load() } }

function openCreate() { createForm.value = emptyRoute(true); showCreateModal.value = true }
async function saveNewRoute() {
  if (!createForm.value.name.trim() || !createForm.value.items.length || !createForm.value.revision_reason.trim()) {
    showToast('请填写路线名称、至少一个节点和制单原因', 'error'); return
  }
  try {
    await state.createRoute(createForm.value)
    showCreateModal.value = false
    showDetailModal.value = true
    await load()
    showToast('路线 V1 草稿已创建')
  } catch (error) { showToast(error.message || '路线创建失败', 'error') }
}

async function openDetail(route) {
  showDetailModal.value = true
  try { await state.openRoute(route) } catch (error) { showToast(error.message || '路线版本加载失败', 'error') }
}
function closeDetail() { showDetailModal.value = false; showApprovalModal.value = false; state.reset() }
async function chooseVersion(version) { await state.selectVersion(version) }
async function chooseHistory(versionId) { if (versionId) await state.selectVersion(versionId) }

async function startRevisionFromRow(route) {
  await openDetail(route)
  if (openVersion.value) { showToast('该路线已有开放修订版', 'warn'); return }
  openCommand('revision')
}
async function startLifecycleFromRow(route, action) { await openDetail(route); openCommand(action) }
function openCommand(type) { commandType.value = type; commandReason.value = ''; showCommandModal.value = true }
async function confirmCommand() {
  if (!commandReason.value.trim()) { showToast(`${commandLabel.value}不能为空`, 'error'); return }
  try {
    if (commandType.value === 'revision') await state.createRevision({ ...editorForm.value, revision_reason: commandReason.value })
    else if (commandType.value === 'reject') await state.transition('reject', commandReason.value)
    else await state.requestLifecycle(commandType.value, commandReason.value)
    showCommandModal.value = false
    await load()
    showToast('路线版本操作已完成')
  } catch (error) { showToast(error.message || '路线版本操作失败', 'error') }
}

async function saveDraft() {
  try { await state.updateDraft(editorForm.value); showToast('路线草稿已保存') } catch (error) { showToast(error.message || '保存失败', 'error') }
}
async function submitVersion() {
  try { await state.transition('submit'); await load(); showToast('路线版本已提交审批') } catch (error) { showToast(error.message || '提交失败', 'error') }
}
function openApproval() {
  Object.keys(approvalDispositions).forEach(key => delete approvalDispositions[key])
  coverageRows.value.forEach(row => { approvalDispositions[row.process_id] = { process_id: Number(row.process_id), disposition: '', price_version_id: null, reason: '' } })
  showApprovalModal.value = true
}
async function approveVersion() {
  try {
    await state.approveSelected(Object.values(approvalDispositions))
    showApprovalModal.value = false
    await load()
    showToast('路线版本已批准发布')
  } catch (error) { showToast(error.message || '发布失败', 'error') }
}
async function afterBatchPublished() { if (root.value?.id) await state.loadRoute(root.value.id); await load() }

onMounted(async () => { await Promise.all([loadProcesses(), load()]) })
</script>

<style scoped>
.route-page { padding:var(--space-6); min-width:0; }
.route-summary { flex-wrap:wrap; }
.summary-note { margin-left:auto; color:var(--text-placeholder); font-size:12px; }
.route-toolbar { gap:8px; }
.search-field { position:relative; flex:1; min-width:220px; }
.clear-search { position:absolute; right:8px; top:50%; width:28px; height:28px; transform:translateY(-50%); border:0; background:transparent; cursor:pointer; }
.route-card-header span { color:var(--text-placeholder); font-size:12px; }
.route-table { min-width:1120px; }
.route-table td:nth-child(2) { min-width:190px; }
.route-table td:nth-child(9) { min-width:260px; }
.route-table td small { display:block; margin-top:3px; color:var(--text-placeholder); }
.route-name-link { padding:0; border:0; background:none; color:var(--text-primary); font-weight:600; cursor:pointer; }
.route-name-link:hover { color:var(--primary); }
.reference-count { color:var(--text-secondary); font-size:12px; white-space:nowrap; }
.row-actions { display:flex; gap:5px; flex-wrap:wrap; }
.status-pill { display:inline-block; padding:3px 7px; border:1px solid var(--border-color); border-radius:4px; font-size:12px; white-space:nowrap; }
.lifecycle-retired, .version-rejected, .version-retired { color:var(--danger); }
.version-pending_approval, .lifecycle-retirement_pending, .lifecycle-reactivation_pending { color:var(--warning-dark); }
.version-published, .lifecycle-active { color:var(--success); }
.route-create-modal { width:min(880px, calc(100vw - 32px)); max-width:880px; }
.route-detail-modal { width:min(1120px, calc(100vw - 24px)); max-width:1120px; max-height:92vh; }
.detail-header > div { display:flex; align-items:center; gap:12px; }
.detail-body { overflow:auto; }
.detail-toolbar { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:14px; }
.version-switcher { display:flex; gap:6px; flex-wrap:wrap; }
.version-switch { padding:7px 10px; border:1px solid var(--border-color); border-radius:4px; background:#fff; cursor:pointer; }
.version-switch.active { border-color:var(--primary); color:var(--primary); background:var(--primary-light); }
.history-select { width:170px; }
.detail-identities { display:flex; gap:6px; color:var(--text-placeholder); font-size:12px; }
.detail-identities span { padding:4px 7px; border:1px solid var(--border-color); border-radius:4px; }
.immutable-note { margin-bottom:14px; padding:10px 12px; border-left:3px solid var(--warning); background:var(--bg-hover); color:var(--text-secondary); font-size:13px; }
.coverage-section { margin-top:20px; padding-top:16px; border-top:1px solid var(--border-color); }
.section-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px; }
.section-heading h4 { margin:0; font-size:15px; letter-spacing:0; }
.section-heading span { color:var(--text-placeholder); font-size:12px; }
.coverage-table { min-width:680px; }
.detail-insights { display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-top:20px; padding-top:16px; border-top:1px solid var(--border-color); }
.operation-error { color:var(--danger); font-size:13px; }
.detail-actions { flex-wrap:wrap; }
.reason-field { display:grid; gap:6px; margin-top:18px; color:var(--text-secondary); font-size:13px; }
.command-modal { max-width:520px; }
.approval-modal { max-width:820px; }
.approval-row { display:grid; grid-template-columns:minmax(140px, 1fr) minmax(160px, 1fr) minmax(180px, 1.2fr); gap:10px; align-items:center; padding:8px 0; border-bottom:1px solid var(--border-color); }
.approval-row > div { display:grid; gap:3px; }
.approval-row small { color:var(--text-placeholder); }
.release-workbench-modal { width:min(1180px, calc(100vw - 24px)); max-width:1180px; max-height:94vh; }
.release-workbench-modal .modal-body { overflow:auto; }
@media (max-width:800px) { .route-page { padding:var(--space-4) 12px; } .summary-note { width:100%; margin-left:0; } .detail-toolbar { align-items:flex-start; flex-direction:column; } .detail-insights { grid-template-columns:1fr; } .approval-row { grid-template-columns:1fr; } }
</style>
