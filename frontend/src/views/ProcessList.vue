<template>
  <div class="process-page">
    <div class="summary-bar process-summary">
      <div class="summary-item">
        <div><div class="s-val">{{ processTotal }}</div><div class="s-label">工序总数</div></div>
      </div>
      <div class="summary-item">
        <div><div class="s-val text-primary">{{ structCount }}</div><div class="s-label">结构件</div></div>
      </div>
      <div class="summary-item">
        <div><div class="s-val text-success">{{ machCount }}</div><div class="s-label">机加工</div></div>
      </div>
      <div class="summary-note">所有变更通过修订版生效，已发布版本保持只读。</div>
    </div>

    <div class="cat-tabs" aria-label="工序分类">
      <button class="cat-tab cat-tab-all" :class="{ active: activeCat === 'all' }" @click="switchCat('all')">全部工序</button>
      <button class="cat-tab cat-tab-struct" :class="{ active: activeCat === '结构件' }" @click="switchCat('结构件')">结构件工序</button>
      <button class="cat-tab cat-tab-mach" :class="{ active: activeCat === '机加工' }" @click="switchCat('机加工')">机加工工序</button>
    </div>

    <div class="toolbar-row process-toolbar">
      <div class="search-field">
        <input
          v-model="searchKeyword"
          class="form-input"
          placeholder="搜索工序名称"
          @keyup.enter="searchAndLoad"
        >
        <button v-if="searchKeyword" class="clear-search" title="清空搜索" @click="clearSearch">&times;</button>
      </div>
      <button class="btn btn-default btn-sm" @click="searchAndLoad">搜索</button>
      <button v-if="canCreateVersion" class="btn btn-primary btn-sm" @click="openAdd">新建工序</button>
    </div>

    <div class="card process-list-card">
      <div class="card-header process-card-header">
        <h3>{{ pageTitle }}</h3>
        <span>共 {{ total || processes.length }} 项</span>
      </div>
      <div class="card-body">
        <div class="table-wrap">
          <div v-if="loading" class="loading-state">加载中...</div>
          <table v-else-if="processes.length" class="data-table process-table">
            <thead>
              <tr>
                <th class="col-seq">序号</th>
                <th>稳定编码</th>
                <th>工序名称</th>
                <th>分类</th>
                <th>当前版本</th>
                <th>生命周期</th>
                <th>修订状态</th>
                <th>引用数量</th>
                <th class="col-actions">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(process, index) in processes" :key="process.id">
                <td class="text-center"><span class="row-num">{{ (page - 1) * pageSize + index + 1 }}</span></td>
                <td><code>{{ process.process_code || processMeta(process).process_code || '-' }}</code></td>
                <td>
                  <button class="process-name-link" @click="openDetail(process)">{{ process.process_name }}</button>
                  <small>{{ process.description || '-' }}</small>
                </td>
                <td><span class="badge" :class="process.category === '结构件' ? 'badge-info' : 'badge-warning'">{{ process.category }}</span></td>
                <td>{{ versionNumber(process) }}</td>
                <td>
                  <span class="status-pill" :class="`lifecycle-${lifecycleStatus(process)}`">
                    {{ processLifecycleLabel(lifecycleStatus(process)) }}
                  </span>
                </td>
                <td>
                  <span class="status-pill" :class="`version-${revisionStatus(process)}`">
                    {{ processVersionStatusLabel(revisionStatus(process)) }}
                  </span>
                </td>
                <td>
                  <button class="reference-link" @click="openDetail(process)">{{ referenceDisplay(process) }}</button>
                </td>
                <td class="col-actions">
                  <div class="row-actions">
                    <button class="btn btn-default btn-sm" @click="openDetail(process)">查看版本</button>
                    <button
                      v-if="canCreateVersion"
                      class="btn btn-default btn-sm"
                      :disabled="busy"
                      @click="startRevisionFromRow(process)"
                    >创建修订版</button>
                    <button
                      v-if="canRetire && lifecycleStatus(process) === 'active'"
                      class="btn btn-warning btn-sm"
                      :disabled="busy"
                      @click="openLifecycleFromRow(process, 'retire')"
                    >申请退休</button>
                    <button
                      v-if="canReactivate && lifecycleStatus(process) === 'retired'"
                      class="btn btn-default btn-sm"
                      :disabled="busy"
                      @click="openLifecycleFromRow(process, 'reactivate')"
                    >申请重新启用</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty"><div class="empty-text">暂无工序数据</div></div>
        </div>
        <div v-if="total > pageSize" class="pagination-bar">
          <button class="btn btn-sm btn-default" :disabled="page <= 1" @click="prevPage">上一页</button>
          <span>第 {{ page }} / {{ Math.ceil(total / pageSize) }} 页（共 {{ total }} 条）</span>
          <button class="btn btn-sm btn-default" :disabled="page * pageSize >= total" @click="nextPage">下一页</button>
        </div>
      </div>
    </div>

    <div v-if="showCreateModal" class="modal-overlay" @click.self="closeCreateModal">
      <div class="modal process-form-modal">
        <div class="modal-header">
          <span>新建工序 V1 草稿</span>
          <button class="modal-close" aria-label="关闭" @click="closeCreateModal">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <label>工序名称 *<input v-model="createForm.name" class="form-input" placeholder="如：切割、焊接、喷涂"></label>
            <label>分类 *
              <select v-model="createForm.category" class="form-input">
                <option v-for="category in categories" :key="category" :value="category">{{ category }}</option>
              </select>
            </label>
            <label>排序序号<input v-model.number="createForm.seq_order" class="form-input" type="number" min="0"></label>
            <label class="form-span">描述<textarea v-model="createForm.description" class="form-input" rows="2"></textarea></label>
            <label class="form-span">制单原因 *<textarea v-model="createForm.revision_reason" class="form-input" rows="3" placeholder="说明新建工序的业务依据"></textarea></label>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" :disabled="busy" @click="closeCreateModal">取消</button>
          <button class="btn btn-primary" :disabled="busy" @click="saveNewProcess">{{ busy ? '创建中...' : '创建 V1 草稿' }}</button>
        </div>
      </div>
    </div>

    <div v-if="showDetailModal" class="modal-overlay" @click.self="closeDetail">
      <div class="modal version-detail-modal">
        <div class="modal-header version-modal-header">
          <div>
            <strong>{{ root?.process_code || selectedProcess?.process_code || '-' }}</strong>
            <span>{{ selectedVersion?.name || selectedProcess?.process_name || '工序版本' }}</span>
          </div>
          <button class="modal-close" aria-label="关闭" @click="closeDetail">&times;</button>
        </div>
        <div class="modal-body version-modal-body">
          <div v-if="loadingDetail" class="loading-state">正在读取版本详情...</div>
          <template v-else-if="selectedVersion">
            <div class="detail-toolbar">
              <div class="version-switcher" aria-label="版本切换">
                <button
                  v-if="currentVersion"
                  class="version-switch"
                  :class="{ active: selectedVersion.id === currentVersion.id }"
                  @click="chooseVersion(currentVersion)"
                >当前版本 V{{ currentVersion.version }}</button>
                <button
                  v-if="openVersion"
                  class="version-switch"
                  :class="{ active: selectedVersion.id === openVersion.id }"
                  @click="chooseVersion(openVersion)"
                >{{ processVersionStatusLabel(openVersion.status) }} V{{ openVersion.version }}</button>
                <select
                  v-if="historicalVersions.length"
                  class="form-input history-select"
                  :value="historicalSelectedId"
                  aria-label="历史版本"
                  @change="chooseHistoricalVersion"
                >
                  <option value="">历史版本</option>
                  <option v-for="version in historicalVersions" :key="version.id" :value="version.id">
                    V{{ version.version }} · {{ processVersionStatusLabel(version.status) }}
                  </option>
                </select>
              </div>
              <div class="detail-actions">
                <button
                  v-if="canCreateVersion && !openVersion"
                  class="btn btn-default btn-sm"
                  :disabled="busy"
                  @click="openRevisionDialog"
                >创建修订版</button>
                <button
                  v-if="canRetire && root?.lifecycle_status === 'active'"
                  class="btn btn-warning btn-sm"
                  :disabled="busy"
                  @click="openLifecycleDialog('retire')"
                >申请退休</button>
                <button
                  v-if="canReactivate && root?.lifecycle_status === 'retired'"
                  class="btn btn-default btn-sm"
                  :disabled="busy"
                  @click="openLifecycleDialog('reactivate')"
                >申请重新启用</button>
              </div>
            </div>

            <div class="version-meta">
              <div><span>版本</span><strong>V{{ selectedVersion.version }}</strong></div>
              <div><span>版本状态</span><strong>{{ processVersionStatusLabel(selectedVersion.status) }}</strong></div>
              <div><span>生命周期</span><strong>{{ processLifecycleLabel(root?.lifecycle_status) }}</strong></div>
              <div><span>制单人</span><strong>{{ selectedVersion.created_by_name || '-' }}</strong></div>
              <div><span>批准人</span><strong>{{ selectedVersion.approved_by_name || '-' }}</strong></div>
              <div><span>生效时间</span><strong>{{ selectedVersion.effective_from || '-' }}</strong></div>
            </div>

            <div v-if="operationError" class="operation-error" role="alert">{{ operationError }}</div>

            <div class="version-content-grid">
              <section class="version-editor">
                <div class="section-heading">
                  <div><h4>版本内容</h4><span>{{ versionEditable ? '草稿可编辑' : '已锁定，只读查看' }}</span></div>
                </div>
                <div class="form-grid">
                  <label>工序名称<input v-model="detailForm.name" class="form-input" :disabled="!versionEditable"></label>
                  <label>分类
                    <select v-model="detailForm.category" class="form-input" :disabled="!versionEditable">
                      <option v-for="category in categories" :key="category" :value="category">{{ category }}</option>
                    </select>
                  </label>
                  <label>排序序号<input v-model.number="detailForm.seq_order" class="form-input" type="number" min="0" :disabled="!versionEditable"></label>
                  <label class="form-span">描述<textarea v-model="detailForm.description" class="form-input" rows="3" :disabled="!versionEditable"></textarea></label>
                  <label class="form-span">修订原因<textarea class="form-input" rows="2" :value="selectedVersion.revision_reason || '-'" disabled></textarea></label>
                </div>
                <div class="workflow-actions">
                  <button
                    v-if="versionEditable && canCreateVersion"
                    class="btn btn-default"
                    :disabled="busy"
                    @click="saveDraft"
                  >{{ busy ? '保存中...' : '保存草稿' }}</button>
                  <button
                    v-if="selectedVersion.status === 'draft' && canSubmit"
                    class="btn btn-primary"
                    :disabled="busy || detailDirty"
                    @click="submitVersion"
                  >{{ detailDirty ? '先保存草稿' : (busy ? '提交中...' : '提交审批') }}</button>
                  <button
                    v-if="selectedVersion.status === 'pending_approval' && canApprove"
                    class="btn btn-primary"
                    :disabled="busy"
                    @click="approveVersion"
                  >{{ busy ? '批准中...' : '批准并发布' }}</button>
                  <button
                    v-if="selectedVersion.status === 'pending_approval' && canReject"
                    class="btn btn-danger"
                    :disabled="busy"
                    @click="openRejectDialog"
                  >驳回</button>
                </div>
              </section>

              <section class="version-side-panel">
                <VersionDiffPanel :before="comparisonBase" :after="selectedVersion" />
                <ImpactSummaryPanel :impact="impact" :loading="loadingImpact" :error="impactError" />
              </section>
            </div>
          </template>
          <div v-else class="empty"><div class="empty-text">该工序尚无版本数据</div></div>
        </div>
      </div>
    </div>

    <div v-if="showRevisionModal" class="modal-overlay dialog-overlay" @click.self="showRevisionModal = false">
      <div class="modal command-modal">
        <div class="modal-header"><span>创建修订版</span><button class="modal-close" aria-label="关闭" @click="showRevisionModal = false">&times;</button></div>
        <div class="modal-body">
          <p class="command-context">将基于 V{{ revisionBaseVersion?.version }} 创建下一修订版，原版本不会被修改。</p>
          <label class="command-label">修订原因 *<textarea v-model="revisionReason" class="form-input" rows="4" placeholder="说明本次变更目的和依据"></textarea></label>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" :disabled="busy" @click="showRevisionModal = false">取消</button>
          <button class="btn btn-primary" :disabled="busy" @click="createRevisionVersion">{{ busy ? '创建中...' : '创建修订版' }}</button>
        </div>
      </div>
    </div>

    <div v-if="showRejectModal" class="modal-overlay dialog-overlay" @click.self="showRejectModal = false">
      <div class="modal command-modal">
        <div class="modal-header"><span>驳回 V{{ selectedVersion?.version }}</span><button class="modal-close" aria-label="关闭" @click="showRejectModal = false">&times;</button></div>
        <div class="modal-body">
          <label class="command-label">驳回原因 *<textarea v-model="rejectReason" class="form-input" rows="4" placeholder="填写需要修正的内容"></textarea></label>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" :disabled="busy" @click="showRejectModal = false">取消</button>
          <button class="btn btn-danger" :disabled="busy" @click="rejectVersion">{{ busy ? '提交中...' : '确认驳回' }}</button>
        </div>
      </div>
    </div>

    <div v-if="showLifecycleModal" class="modal-overlay dialog-overlay" @click.self="showLifecycleModal = false">
      <div class="modal command-modal">
        <div class="modal-header">
          <span>{{ lifecycleAction === 'retire' ? '申请退休工序' : '申请重新启用工序' }}</span>
          <button class="modal-close" aria-label="关闭" @click="showLifecycleModal = false">&times;</button>
        </div>
        <div class="modal-body">
          <p class="command-context">{{ lifecycleAction === 'retire' ? '批准后，新业务将不能选择该工序；历史业务仍保留原版本。' : '重新启用前必须已有发布的新修订版。' }}</p>
          <label class="command-label">申请原因 *<textarea v-model="lifecycleReason" class="form-input" rows="4"></textarea></label>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" :disabled="busy" @click="showLifecycleModal = false">取消</button>
          <button class="btn" :class="lifecycleAction === 'retire' ? 'btn-warning' : 'btn-primary'" :disabled="busy" @click="requestLifecycleChange">
            {{ busy ? '提交中...' : '提交申请' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import ImpactSummaryPanel from '@/components/master-data/ImpactSummaryPanel.vue'
import VersionDiffPanel from '@/components/master-data/VersionDiffPanel.vue'
import { useProcessList } from '@/composables/masterData/useProcessList.js'

export default {
  components: { ImpactSummaryPanel, VersionDiffPanel },
  setup() {
    return useProcessList()
  },
}
</script>

<style scoped>
.process-page { padding:var(--space-6); }
.process-summary { align-items:stretch; }
.process-summary .summary-item { min-width:140px; }
.summary-note { margin-left:auto; display:flex; align-items:center; color:var(--text-placeholder); font-size:12px; }
.cat-tabs { display:flex; gap:4px; margin-bottom:var(--space-4); padding:3px; width:max-content; max-width:100%; background:var(--bg-hover); border-radius:6px; }
.cat-tab { min-height:32px; padding:5px 12px; border:0; border-radius:4px; background:transparent; color:var(--text-secondary); cursor:pointer; font-size:13px; white-space:nowrap; }
.cat-tab.active { background:var(--bg-surface); color:var(--primary); box-shadow:var(--shadow-sm); font-weight:600; }
.process-toolbar { display:flex; align-items:center; gap:var(--space-3); margin-bottom:var(--space-4); flex-wrap:wrap; }
.search-field { position:relative; flex:1; min-width:220px; }
.search-field .form-input { padding-right:34px; }
.clear-search { position:absolute; top:50%; right:5px; transform:translateY(-50%); width:28px; height:28px; border:0; background:transparent; color:var(--text-placeholder); cursor:pointer; font-size:18px; }
.process-list-card { margin:0; }
.process-card-header { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.process-card-header h3 { margin:0; font-size:16px; letter-spacing:0; }
.process-card-header span { color:var(--text-placeholder); font-size:12px; }
.loading-state { padding:42px 16px; text-align:center; color:var(--text-placeholder); }
.process-table { min-width:1120px; }
.process-table code { white-space:nowrap; font-size:12px; }
.process-table small { display:block; max-width:240px; margin-top:3px; color:var(--text-placeholder); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.process-name-link,.reference-link { padding:0; border:0; background:transparent; color:var(--primary); cursor:pointer; text-align:left; font:inherit; font-weight:600; }
.reference-link { min-width:34px; text-align:center; font-weight:500; }
.status-pill { display:inline-block; padding:3px 7px; border-radius:4px; white-space:nowrap; background:var(--bg-hover); color:var(--text-secondary); font-size:12px; }
.version-pending_approval,.lifecycle-retirement_pending,.lifecycle-reactivation_pending { background:var(--warning-light); color:var(--warning-dark); }
.version-published,.lifecycle-active { background:var(--success-light); color:var(--success-dark); }
.version-rejected,.version-retired,.lifecycle-retired { background:var(--danger-light); color:var(--danger-dark); }
.version-draft { background:var(--primary-light); color:var(--primary); }
.row-actions { display:flex; justify-content:flex-end; gap:5px; white-space:nowrap; }
.pagination-bar { display:flex; align-items:center; justify-content:flex-end; gap:12px; padding-top:var(--space-3); color:var(--text-placeholder); font-size:12px; }
.process-form-modal { width:min(620px,94vw); }
.version-detail-modal { width:min(1120px,96vw); max-width:1120px; max-height:92vh; display:flex; flex-direction:column; }
.version-modal-header > div { display:flex; align-items:baseline; gap:10px; min-width:0; }
.version-modal-header strong { font-family:monospace; font-size:13px; }
.version-modal-header span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.version-modal-body { overflow:auto; }
.detail-toolbar { display:flex; justify-content:space-between; align-items:center; gap:12px; padding-bottom:12px; border-bottom:1px solid var(--border-light); }
.version-switcher,.detail-actions { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
.version-switch { min-height:32px; padding:5px 10px; border:1px solid var(--border-light); border-radius:4px; background:var(--bg-surface); color:var(--text-secondary); cursor:pointer; font-size:12px; }
.version-switch.active { border-color:var(--primary); background:var(--primary-light); color:var(--primary); font-weight:600; }
.history-select { width:150px; min-height:32px; padding:5px 8px; }
.version-meta { display:grid; grid-template-columns:repeat(6,minmax(110px,1fr)); margin:12px 0; border:1px solid var(--border-light); border-radius:6px; overflow:hidden; }
.version-meta > div { min-width:0; padding:10px 12px; background:var(--bg-table-header); border-right:1px solid var(--border-light); }
.version-meta > div:last-child { border-right:0; }
.version-meta span,.version-meta strong { display:block; overflow-wrap:anywhere; }
.version-meta span { margin-bottom:4px; color:var(--text-placeholder); font-size:11px; }
.version-meta strong { color:var(--text-secondary); font-size:13px; }
.operation-error { margin-bottom:12px; padding:9px 12px; border:1px solid var(--danger); background:var(--danger-light); color:var(--danger-dark); font-size:13px; }
.version-content-grid { display:grid; grid-template-columns:minmax(0,1.05fr) minmax(360px,.95fr); gap:16px; }
.version-editor,.version-side-panel { min-width:0; }
.version-editor { border:1px solid var(--border-light); }
.version-side-panel { display:grid; align-content:start; gap:18px; padding:12px; border:1px solid var(--border-light); }
.section-heading { padding:11px 14px; border-bottom:1px solid var(--border-light); background:var(--bg-table-header); }
.section-heading h4 { margin:0; font-size:15px; letter-spacing:0; }
.section-heading span { color:var(--text-placeholder); font-size:12px; }
.form-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; padding:14px; }
.form-grid label,.command-label { display:grid; gap:6px; color:var(--text-secondary); font-size:13px; }
.form-span { grid-column:1/-1; }
.form-input:disabled { color:var(--text-secondary); background:var(--bg-hover); cursor:not-allowed; }
.workflow-actions { display:flex; justify-content:flex-end; gap:8px; padding:12px 14px; border-top:1px solid var(--border-light); }
.dialog-overlay { z-index:1100; }
.command-modal { width:min(500px,92vw); }
.command-context { margin:0 0 14px; padding:10px 12px; background:var(--bg-table-header); color:var(--text-secondary); font-size:13px; }
.modal-close { padding:0; }
@media (max-width:900px) {
  .summary-note { width:100%; margin-left:0; }
  .version-content-grid { grid-template-columns:1fr; }
  .version-meta { grid-template-columns:repeat(3,1fr); }
  .version-meta > div:nth-child(3n) { border-right:0; }
  .detail-toolbar { align-items:flex-start; flex-direction:column; }
}
@media (max-width:640px) {
  .process-page { padding:var(--space-3); }
  .cat-tabs { width:100%; overflow:auto; }
  .cat-tab { flex:0 0 auto; }
  .process-toolbar .btn { flex:1; }
  .version-meta { grid-template-columns:repeat(2,1fr); }
  .version-meta > div:nth-child(3n) { border-right:1px solid var(--border-light); }
  .version-meta > div:nth-child(2n) { border-right:0; }
  .form-grid { grid-template-columns:1fr; }
  .form-span { grid-column:auto; }
  .workflow-actions { flex-wrap:wrap; }
  .workflow-actions .btn { flex:1 1 130px; }
}
</style>
