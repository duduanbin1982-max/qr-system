<template>
  <div class="position-page">
    <div class="summary-bar position-summary">
      <div class="summary-item"><div><div class="s-val">{{ positionTotal }}</div><div class="s-label">岗位总数</div></div></div>
      <div class="summary-item"><div><div class="s-val text-success">{{ activeCount }}</div><div class="s-label">生效中</div></div></div>
      <div class="summary-item"><div><div class="s-val text-primary">{{ pendingCount }}</div><div class="s-label">待办</div></div></div>
      <div class="summary-item"><div><div class="s-val">{{ retiredCount }}</div><div class="s-label">已退休</div></div></div>
    </div>

    <div class="position-toolbar">
      <div><h3>岗位管理</h3><span>共 {{ positions.length }} 条</span></div>
      <button v-if="canCreate" class="btn btn-primary btn-sm" title="新建岗位" @click="openCreateDialog">新建岗位</button>
    </div>

    <div class="card position-list-card">
      <div class="card-body">
        <div v-if="positionLoading" class="loading-state">加载中...</div>
        <div v-else-if="positions.length" class="table-wrap">
          <table class="data-table position-table">
            <thead><tr><th>稳定编码</th><th>岗位</th><th>当前版本</th><th>可报工工序</th><th>员工数</th><th>生命周期</th><th>待办</th><th class="actions-col">操作</th></tr></thead>
            <tbody>
              <tr v-for="position in positions" :key="position.id">
                <td><code>{{ position.position_code || '-' }}</code></td>
                <td class="position-name-cell">
                  <button v-if="canHistory" class="name-link" @click="openDetail(position)">{{ position.name }}</button>
                  <strong v-else>{{ position.name }}</strong>
                  <small>{{ position.description || '-' }}</small>
                </td>
                <td>{{ position.current_version ? `V${position.current_version.version}` : '-' }}</td>
                <td>
                  <div v-if="position.processes?.length" class="process-chips">
                    <span v-for="process in position.processes.slice(0, 3)" :key="process.process_id" class="process-chip">{{ process.process_name }}</span>
                    <span v-if="position.processes.length > 3" class="more-chip">+{{ position.processes.length - 3 }}</span>
                  </div>
                  <span v-else class="muted">-</span>
                </td>
                <td class="numeric">{{ position.employee_count ?? 0 }}</td>
                <td><span class="status-pill" :class="`lifecycle-${position.lifecycle_status || 'active'}`">{{ positionLifecycleLabel(position.lifecycle_status || 'active') }}</span></td>
                <td>
                  <span v-if="position.open_version" class="status-pill" :class="`version-${position.open_version.status}`">V{{ position.open_version.version }} {{ positionVersionStatusLabel(position.open_version.status) }}</span>
                  <span v-else-if="position.pending_lifecycle_request" class="status-pill version-pending_approval">{{ lifecycleActionLabel(position.pending_lifecycle_request.action) }}</span>
                  <span v-else class="muted">无</span>
                </td>
                <td class="actions-col">
                  <div class="row-actions">
                    <button v-if="canHistory" class="btn btn-default btn-sm" title="查看岗位版本" @click="openDetail(position)">版本详情</button>
                    <button v-if="canHistory && canCreate && position.lifecycle_status !== 'retired'" class="btn btn-default btn-sm" title="创建修订版" :disabled="commandBusy || Boolean(position.open_version)" @click="openRevisionFromRow(position)">创建修订</button>
                    <button v-if="canHistory && canRetire && position.lifecycle_status !== 'retired'" class="btn btn-warning btn-sm" title="申请退休岗位" :disabled="commandBusy || Boolean(position.pending_lifecycle_request)" @click="openLifecycleFromRow(position, 'retire')">申请退休</button>
                    <button v-if="canHistory && canReactivate && position.lifecycle_status === 'retired'" class="btn btn-default btn-sm" title="申请重新启用岗位" :disabled="commandBusy || Boolean(position.pending_lifecycle_request)" @click="openLifecycleFromRow(position, 'reactivate')">重新启用</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty"><div class="empty-text">暂无岗位数据</div></div>
      </div>
    </div>

    <div v-if="showCreateModal" class="modal-overlay" @click.self="closeCreateDialog">
      <div class="modal position-command-modal">
        <div class="modal-header"><span>新建岗位 V1 草稿</span><button class="modal-close" aria-label="关闭" @click="closeCreateDialog">&times;</button></div>
        <div class="modal-body">
          <div class="form-grid">
            <label>岗位名称 *<input v-model="createForm.name" class="form-input" maxlength="128"></label>
            <label class="form-span">描述<textarea v-model="createForm.description" class="form-input" rows="2" maxlength="512"></textarea></label>
            <label class="form-span">制单原因 *<textarea v-model="createForm.revision_reason" class="form-input" rows="3" maxlength="512"></textarea></label>
            <fieldset class="form-span process-selector">
              <legend>可报工工序</legend>
              <label v-for="process in allProcesses" :key="process.id" class="process-option"><input type="checkbox" :checked="createForm.process_ids.includes(process.id)" @change="toggleProcess(createForm.process_ids, process.id)"><span>{{ process.process_name || process.name }}</span></label>
              <span v-if="!allProcesses.length" class="muted">无可选工序</span>
            </fieldset>
          </div>
        </div>
        <div class="modal-footer"><button class="btn btn-default" :disabled="commandBusy" @click="closeCreateDialog">取消</button><button class="btn btn-primary" :disabled="commandBusy" @click="createPosition">{{ commandBusy ? '创建中...' : '创建 V1 草稿' }}</button></div>
      </div>
    </div>

    <div v-if="showDetailModal" class="modal-overlay" @click.self="closeDetail">
      <div class="modal position-detail-modal">
        <div class="modal-header detail-header"><div><strong>{{ root?.position_code || '-' }}</strong><span>{{ root?.name || '岗位版本' }}</span></div><button class="modal-close" aria-label="关闭" @click="closeDetail">&times;</button></div>
        <div class="position-tabs" role="tablist" aria-label="岗位版本视图">
          <button data-tab="current" :class="{ active: activeTab === 'current' }" @click="switchTab('current')">当前</button>
          <button data-tab="pending" :class="{ active: activeTab === 'pending' }" @click="switchTab('pending')">待办<span v-if="pending || pendingLifecycle" class="tab-count">1</span></button>
          <button data-tab="history" :class="{ active: activeTab === 'history' }" @click="switchTab('history')">历史</button>
          <button v-if="canImpact" data-tab="impact" :class="{ active: activeTab === 'impact' }" @click="switchTab('impact')">影响</button>
        </div>

        <div class="modal-body detail-body">
          <div v-if="loading" class="loading-state">正在读取岗位版本...</div>
          <template v-else>
            <div v-if="activeTab === 'history' && history.length" class="history-picker"><label>历史版本<select class="form-input" :value="selectedVersion?.id" @change="selectHistoryVersion"><option v-for="version in history" :key="version.id" :value="version.id">V{{ version.version }} · {{ positionVersionStatusLabel(version.status) }}</option></select></label></div>

            <template v-if="activeTab === 'impact'">
              <div class="impact-version-picker"><label>版本<select class="form-input" :value="selectedVersion?.id" @change="selectImpactVersion"><option v-for="version in versions" :key="version.id" :value="version.id">V{{ version.version }} · {{ positionVersionStatusLabel(version.status) }}</option></select></label></div>
              <ImpactSummaryPanel :impact="impact" :loading="impactLoading" :error="operationError" />
              <VersionDiffPanel v-if="selectedVersion" :before="diffBefore" :after="diffAfter" />
            </template>

            <template v-else-if="selectedVersion">
              <div class="version-meta">
                <div><span>版本</span><strong>V{{ selectedVersion.version }}</strong></div><div><span>状态</span><strong>{{ positionVersionStatusLabel(selectedVersion.status) }}</strong></div><div><span>制单人</span><strong>{{ selectedVersion.created_by_name || '-' }}</strong></div>
                <div><span>批准人</span><strong>{{ selectedVersion.approved_by_name || '-' }}</strong></div><div><span>生效时间</span><strong>{{ selectedVersion.effective_from || '-' }}</strong></div><div><span>修订原因</span><strong>{{ selectedVersion.revision_reason || '-' }}</strong></div>
              </div>
              <section class="version-editor">
                <div class="section-heading"><h4>版本内容</h4><span>{{ versionEditable ? '草稿' : '只读' }}</span></div>
                <div class="form-grid">
                  <label>岗位名称<input v-model="detailForm.name" class="form-input" :disabled="!versionEditable"></label>
                  <label class="form-span">描述<textarea v-model="detailForm.description" class="form-input" rows="2" :disabled="!versionEditable"></textarea></label>
                  <fieldset class="form-span process-selector" :disabled="!versionEditable">
                    <legend>可报工工序</legend>
                    <label v-for="process in allProcesses" :key="process.id" class="process-option"><input type="checkbox" :checked="detailForm.process_ids.includes(process.id)" :disabled="!versionEditable" @change="toggleProcess(detailForm.process_ids, process.id)"><span>{{ process.process_name || process.name }}</span></label>
                    <span v-if="!allProcesses.length" class="muted">无可选工序</span>
                  </fieldset>
                </div>
                <div v-if="activeTab === 'pending'" class="detail-actions">
                  <button v-if="versionEditable && canCreate" class="btn btn-default btn-sm" :disabled="commandBusy" @click="saveDraft">保存草稿</button>
                  <button v-if="selectedVersion.status === 'draft' && canSubmit" class="btn btn-primary btn-sm" :disabled="commandBusy" @click="submitVersion">提交审批</button>
                  <button v-if="selectedVersion.status === 'pending_approval' && canApprove" class="btn btn-primary btn-sm" :disabled="commandBusy || isVersionSelfApproval" @click="approveVersion">批准发布</button>
                  <button v-if="selectedVersion.status === 'pending_approval' && canReject" class="btn btn-danger btn-sm" :disabled="commandBusy || isVersionSelfApproval" @click="openRejectDialog('version')">驳回</button>
                  <button v-if="['draft','pending_approval'].includes(selectedVersion.status) && canSubmit" class="btn btn-default btn-sm" :disabled="commandBusy" @click="openRejectDialog('cancel')">取消修订</button>
                </div>
              </section>
              <VersionDiffPanel v-if="activeTab !== 'current'" :before="diffBefore" :after="diffAfter" />
            </template>
            <div v-else-if="activeTab !== 'pending'" class="empty compact-empty"><div class="empty-text">暂无对应版本</div></div>

            <section v-if="activeTab === 'pending' && pendingLifecycle" class="lifecycle-pending">
              <div class="section-heading"><h4>{{ lifecycleActionLabel(pendingLifecycle.action) }}</h4><span>待审批</span></div>
              <dl><div><dt>申请人</dt><dd>{{ pendingLifecycle.requested_by_name || '-' }}</dd></div><div><dt>申请原因</dt><dd>{{ pendingLifecycle.reason || '-' }}</dd></div></dl>
              <div class="detail-actions"><button v-if="canApprove" class="btn btn-primary btn-sm" :disabled="commandBusy || isLifecycleSelfApproval" @click="approveLifecycle">批准</button><button v-if="canReject" class="btn btn-danger btn-sm" :disabled="commandBusy || isLifecycleSelfApproval" @click="openRejectDialog('lifecycle')">驳回</button></div>
            </section>
            <div v-if="activeTab === 'pending' && !pending && !pendingLifecycle" class="empty compact-empty"><div class="empty-text">暂无待办</div></div>
            <div v-if="operationError && activeTab !== 'impact'" class="operation-error">{{ operationError }}</div>
          </template>
        </div>
        <div class="modal-footer detail-footer">
          <div><button v-if="canCreate && root?.lifecycle_status !== 'retired' && !pending" class="btn btn-default" :disabled="commandBusy" @click="openRevisionDialog">创建修订版</button><button v-if="canRetire && root?.lifecycle_status === 'active' && !pendingLifecycle" class="btn btn-warning" :disabled="commandBusy" @click="openLifecycleDialog('retire')">申请退休</button><button v-if="canReactivate && root?.lifecycle_status === 'retired' && !pendingLifecycle" class="btn btn-default" :disabled="commandBusy" @click="openLifecycleDialog('reactivate')">申请重新启用</button></div>
          <button class="btn btn-default" :disabled="commandBusy" @click="closeDetail">关闭</button>
        </div>
      </div>
    </div>

    <div v-if="showRevisionModal" class="modal-overlay command-overlay" @click.self="showRevisionModal = false"><div class="modal small-modal"><div class="modal-header"><span>创建修订版</span><button class="modal-close" aria-label="关闭" @click="showRevisionModal = false">&times;</button></div><div class="modal-body"><label>修订原因 *<textarea v-model="revisionReason" class="form-input" rows="4" maxlength="512"></textarea></label></div><div class="modal-footer"><button class="btn btn-default" :disabled="commandBusy" @click="showRevisionModal = false">取消</button><button class="btn btn-primary" :disabled="commandBusy" @click="createRevision">创建修订版</button></div></div></div>
    <div v-if="showRejectModal" class="modal-overlay command-overlay" @click.self="showRejectModal = false"><div class="modal small-modal"><div class="modal-header"><span>{{ rejectTitle }}</span><button class="modal-close" aria-label="关闭" @click="showRejectModal = false">&times;</button></div><div class="modal-body"><label>原因 *<textarea v-model="rejectReason" class="form-input" rows="4" maxlength="512"></textarea></label></div><div class="modal-footer"><button class="btn btn-default" :disabled="commandBusy" @click="showRejectModal = false">取消</button><button class="btn btn-danger" :disabled="commandBusy" @click="confirmReject">{{ rejectTarget === 'cancel' ? '确认取消' : '确认驳回' }}</button></div></div></div>
    <div v-if="showLifecycleModal" class="modal-overlay command-overlay" @click.self="showLifecycleModal = false"><div class="modal small-modal"><div class="modal-header"><span>{{ lifecycleAction === 'retire' ? '申请退休岗位' : '申请重新启用岗位' }}</span><button class="modal-close" aria-label="关闭" @click="showLifecycleModal = false">&times;</button></div><div class="modal-body"><label>申请原因 *<textarea v-model="lifecycleReason" class="form-input" rows="4" maxlength="512"></textarea></label></div><div class="modal-footer"><button class="btn btn-default" :disabled="commandBusy" @click="showLifecycleModal = false">取消</button><button class="btn" :class="lifecycleAction === 'retire' ? 'btn-warning' : 'btn-primary'" :disabled="commandBusy" @click="requestLifecycle">提交申请</button></div></div></div>
  </div>
</template>

<script>
import ImpactSummaryPanel from '@/components/master-data/ImpactSummaryPanel.vue'
import VersionDiffPanel from '@/components/master-data/VersionDiffPanel.vue'
import { usePositionsWorkspace } from '@/composables/settings/usePositionsWorkspace.js'

export default {
  components: { ImpactSummaryPanel, VersionDiffPanel },
  setup() {
    return usePositionsWorkspace()
  },
}
</script>

<style scoped>
.position-page { min-width:0; }
.position-summary { align-items:stretch; margin-bottom:16px; }
.position-summary .summary-item { min-width:120px; }
.position-toolbar { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:12px; }
.position-toolbar h3 { margin:0; font-size:16px; letter-spacing:0; }
.position-toolbar span { color:var(--text-placeholder); font-size:12px; }
.position-list-card { margin:0; }
.position-table { min-width:1050px; }
.position-table th, .position-table td { vertical-align:middle; }
.position-name-cell { min-width:150px; }
.position-name-cell small { display:block; margin-top:3px; color:var(--text-placeholder); max-width:260px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.name-link { padding:0; border:0; background:transparent; color:var(--primary); font:inherit; font-weight:600; cursor:pointer; }
.process-chips { display:flex; flex-wrap:wrap; gap:4px; min-width:180px; }
.process-chip, .more-chip { display:inline-flex; align-items:center; min-height:24px; padding:2px 7px; border:1px solid var(--border-color); border-radius:4px; background:var(--bg-hover); font-size:12px; white-space:nowrap; }
.more-chip, .muted { color:var(--text-placeholder); }
.numeric { text-align:right; font-variant-numeric:tabular-nums; }
.actions-col { min-width:260px; }
.row-actions { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
.status-pill { display:inline-flex; align-items:center; min-height:24px; padding:2px 8px; border:1px solid var(--border-color); border-radius:4px; font-size:12px; white-space:nowrap; }
.lifecycle-active, .version-published { color:#23653a; background:#edf8f0; border-color:#aed8b9; }
.lifecycle-retired, .version-retired, .version-cancelled { color:#59636e; background:#f2f4f6; border-color:#cbd2d8; }
.version-draft { color:#245d8f; background:#edf6fc; border-color:#b4d3ea; }
.version-pending_approval { color:#925d00; background:#fff7df; border-color:#ebcf83; }
.version-rejected { color:#a63832; background:#fff0ef; border-color:#edbbb7; }
.position-command-modal { width:min(720px, calc(100vw - 24px)); }
.position-detail-modal { width:min(1040px, calc(100vw - 24px)); max-height:calc(100vh - 32px); display:flex; flex-direction:column; }
.detail-header > div { min-width:0; display:flex; align-items:center; gap:12px; }
.detail-header strong { flex:0 0 auto; }
.detail-header span { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.position-tabs { display:flex; gap:2px; padding:8px 18px 0; border-bottom:1px solid var(--border-color); background:var(--bg-hover); overflow-x:auto; }
.position-tabs button { min-width:82px; min-height:36px; padding:7px 12px; border:0; border-bottom:2px solid transparent; background:transparent; color:var(--text-secondary); cursor:pointer; white-space:nowrap; }
.position-tabs button.active { color:var(--primary); border-bottom-color:var(--primary); font-weight:600; background:var(--bg-surface); }
.tab-count { display:inline-flex; align-items:center; justify-content:center; min-width:18px; height:18px; margin-left:5px; border-radius:50%; background:var(--warning); color:#fff; font-size:11px; }
.detail-body { overflow:auto; min-height:360px; }
.version-meta { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:1px; margin-bottom:18px; background:var(--border-color); border:1px solid var(--border-color); }
.version-meta > div { min-width:0; display:grid; gap:4px; padding:10px 12px; background:var(--bg-surface); }
.version-meta span { color:var(--text-placeholder); font-size:11px; }
.version-meta strong { min-width:0; overflow-wrap:anywhere; font-size:13px; }
.version-editor, .lifecycle-pending { padding:0 0 18px; border-bottom:1px solid var(--border-color); margin-bottom:18px; }
.section-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; }
.section-heading h4 { margin:0; font-size:15px; letter-spacing:0; }
.section-heading span { color:var(--text-placeholder); font-size:12px; }
.form-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:14px; }
.form-grid label, .small-modal label, .history-picker label, .impact-version-picker label { display:grid; gap:6px; font-size:13px; color:var(--text-secondary); }
.form-span { grid-column:1 / -1; }
.process-selector { grid-column:1 / -1; min-width:0; display:flex; flex-wrap:wrap; gap:7px; margin:0; padding:10px; border:1px solid var(--border-color); }
.process-selector legend { padding:0 5px; color:var(--text-secondary); font-size:13px; }
.process-option { display:inline-flex !important; grid-auto-flow:column; align-items:center; gap:6px !important; min-height:30px; padding:4px 8px; border:1px solid var(--border-color); border-radius:4px; background:var(--bg-surface); cursor:pointer; }
.process-option input { margin:0; }
.process-selector:disabled .process-option { cursor:default; opacity:.78; }
.detail-actions { display:flex; justify-content:flex-end; gap:8px; flex-wrap:wrap; margin-top:14px; }
.history-picker, .impact-version-picker { display:flex; justify-content:flex-end; margin-bottom:14px; }
.history-picker label, .impact-version-picker label { width:min(280px, 100%); }
.lifecycle-pending dl { display:grid; gap:8px; margin:0; }
.lifecycle-pending dl > div { display:grid; grid-template-columns:90px minmax(0, 1fr); gap:12px; }
.lifecycle-pending dt { color:var(--text-placeholder); }
.lifecycle-pending dd { margin:0; overflow-wrap:anywhere; }
.operation-error { margin-top:12px; padding:9px 11px; border:1px solid var(--danger); background:var(--danger-light); color:var(--danger-dark); font-size:12px; }
.compact-empty { padding:34px 0; }
.detail-footer { justify-content:space-between; gap:12px; }
.detail-footer > div { display:flex; gap:8px; flex-wrap:wrap; }
.command-overlay { z-index:1010; }
.small-modal { width:min(500px, calc(100vw - 24px)); }
@media (max-width:760px) { .position-summary { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); } .position-summary .summary-item { min-width:0; } .position-toolbar { align-items:flex-end; } .version-meta { grid-template-columns:repeat(2, minmax(0, 1fr)); } .form-grid { grid-template-columns:1fr; } .form-span { grid-column:auto; } .detail-footer { align-items:stretch; flex-direction:column; } .detail-footer > div { width:100%; } }
@media (max-width:460px) { .position-toolbar { align-items:stretch; flex-direction:column; } .version-meta { grid-template-columns:1fr; } .position-tabs button { min-width:70px; } .lifecycle-pending dl > div { grid-template-columns:1fr; gap:2px; } }
</style>
