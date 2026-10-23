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
              <div class="section-heading">
                <div>
                  <h4>工价覆盖</h4>
                  <span v-if="selectedVersion.status === 'draft'">提交审批后即可在本页填写精确工价</span>
                  <span v-else>按路线版本和工序版本精确匹配</span>
                </div>
                <div class="coverage-heading-actions">
                  <span>{{ coveredNodeCount }} / {{ coverageRows.length }} 已覆盖</span>
                  <button
                    v-if="selectedVersion.status === 'pending_approval' && canPreparePrice && missingCoverageRows.length"
                    type="button"
                    class="btn btn-primary btn-sm"
                    data-testid="create-missing-route-prices"
                    @click="openPriceVersion(missingCoverageRows[0])"
                  >建立缺失工价</button>
                </div>
              </div>
              <div class="table-wrap">
                <table class="data-table coverage-table">
                  <thead><tr><th>节点</th><th>绑定版本</th><th>覆盖状态</th><th>参考旧工价</th><th>精确新工价</th><th>操作</th></tr></thead>
                  <tbody>
                    <tr v-for="row in coverageRows" :key="row.process_version_id">
                      <td>{{ row.process_name_snapshot || row.process_id }}</td>
                      <td>V{{ row.process_version || row.process_version_id }}</td>
                      <td><span :class="coverageStatusClass(row.coverage_status)">{{ coverageStatusLabel(row.coverage_status, selectedVersion.status) }}</span></td>
                      <td><span v-if="row.reference_price">{{ money(row.reference_price.normal_unit_price_micros) }}</span><span v-else>-</span><small v-if="row.reference_price">仅供参考</small></td>
                      <td><span v-if="row.price_versions.length">{{ row.price_versions.map(price => `#${price.id} ${priceStatus(price.status)} ${money(price.normal_unit_price_micros)}`).join('、') }}</span><span v-else>-</span></td>
                      <td>
                        <button
                          v-if="selectedVersion.status === 'draft' && canSubmit && canPreparePrice"
                          type="button"
                          class="btn btn-primary btn-sm"
                          :data-testid="`submit-and-create-exact-price-${row.process_version_id}`"
                          :disabled="busy"
                          @click="submitAndOpenPrice(row)"
                        >提交审批并填写工价</button>
                        <button
                          v-else
                          type="button"
                          class="btn btn-default btn-sm"
                          :data-testid="`create-exact-price-${row.process_version_id}`"
                          :disabled="selectedVersion.status !== 'pending_approval' || !canPreparePrice"
                          @click="openPriceVersion(row)"
                        >{{ selectedVersion.status === 'pending_approval' ? '填写工价' : '提交审批后可定价' }}</button>
                      </td>
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
import ImpactSummaryPanel from '@/components/master-data/ImpactSummaryPanel.vue'
import ReleaseBatchPanel from '@/components/master-data/ReleaseBatchPanel.vue'
import RouteVersionEditor from '@/components/master-data/RouteVersionEditor.vue'
import VersionDiffPanel from '@/components/master-data/VersionDiffPanel.vue'
import { useRouteList } from '@/composables/masterData/useRouteList.js'



const {
  selectedRoute,
  root,
  selectedVersion,
  currentVersion,
  openVersion,
  historicalVersions,
  comparisonBase,
  impact,
  priceVersions,
  coverageRows,
  loadingDetail,
  loadingContext,
  busy,
  operationError,
  contextError,
  routes,
  processOptions,
  loading,
  searchKeyword,
  categoryFilter,
  page,
  pageSize,
  total,
  summary,
  showCreateModal,
  showDetailModal,
  showCommandModal,
  showApprovalModal,
  showReleaseModal,
  commandType,
  commandReason,
  editorForm,
  createForm,
  approvalDispositions,
  canCreateVersion,
  canSubmit,
  canApprove,
  canReject,
  canRetire,
  canReactivate,
  canViewReleases,
  canPreparePrice,
  activeCategory,
  historicalSelection,
  coveredNodeCount,
  missingCoverageRows,
  commandTitle,
  commandLabel,
  clone,
  emptyRoute,
  priceStatus,
  exactApprovedPrice,
  money,
  coverageStatusLabel,
  coverageStatusClass,
  openPriceVersion,
  submitAndOpenPrice,
  load,
  loadProcesses,
  switchCategory,
  searchAndLoad,
  clearSearch,
  previousPage,
  nextPage,
  openCreate,
  saveNewRoute,
  openDetail,
  closeDetail,
  chooseVersion,
  chooseHistory,
  startRevisionFromRow,
  startLifecycleFromRow,
  openCommand,
  confirmCommand,
  saveDraft,
  submitVersion,
  openApproval,
  approveVersion,
  afterBatchPublished,
  routeLifecycleLabel,
  routeVersionStatusLabel
} = useRouteList()
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
