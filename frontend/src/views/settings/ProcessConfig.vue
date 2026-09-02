<template>
  <div class="process-config-page">
    <section class="card current-config-panel">
      <div class="card-header process-config-header">
        <div>
          <h3>工艺管理</h3>
          <p class="config-meta">
            当前生效 V{{ current.version || '-' }}
            <span v-if="current.updated_at"> · {{ current.updated_at }}</span>
            <span v-if="current.updated_by_name"> · {{ current.updated_by_name }}</span>
          </p>
        </div>
        <span class="access-state" :class="canEditDraft ? 'editable' : 'readonly'">
          {{ canEditDraft ? '可制单' : '仅查看' }}
        </span>
      </div>
      <div class="current-summary">
        <div><span>报工顺序</span><strong>{{ orderModeLabel(current.process_order_mode) }}</strong></div>
        <div><span>序列号规则</span><strong>{{ serialModeLabel(current.serial_process_report_mode) }}</strong></div>
        <div><span>上道工序上限</span><strong>{{ flagLabel(current.limit_by_prev_process) }}</strong></div>
        <div><span>订单数量上限</span><strong>{{ flagLabel(current.limit_by_order_qty) }}</strong></div>
        <div><span>报工审批</span><strong>{{ flagLabel(current.approval_enabled) }}</strong></div>
      </div>
    </section>

    <div v-if="operationError" class="operation-error" role="alert">
      <span>{{ operationError }}</span>
      <button type="button" class="btn btn-sm" @click="loadProcessConfig">重新加载</button>
    </div>

    <section class="card editor-panel">
      <div class="card-header process-config-header">
        <div>
          <h3>{{ openRevision ? '待处理修订版' : '新建工艺修订版' }}</h3>
          <p class="config-meta" v-if="openRevision">
            V{{ openRevision.version }} · {{ processConfigStatusLabel(openRevision.status) }}
            · 制单人 {{ openRevision.created_by_name || '-' }}
          </p>
          <p class="config-meta" v-else>所有变更先保存为草稿，经另一位用户批准后才会生效。</p>
        </div>
        <span v-if="openRevision" class="status-pill" :class="`status-${openRevision.status}`">
          {{ processConfigStatusLabel(openRevision.status) }}
        </span>
      </div>

      <div v-if="loading" class="empty-state">加载中...</div>
      <form v-else class="editor-body" @submit.prevent="save">
        <div v-if="pending" class="workflow-note pending-note">
          当前修订版等待审批。待审批内容已锁定，批准后将整体替换当前生效配置。
        </div>
        <div v-else-if="draft && !isDraftOwner" class="workflow-note locked-note">
          该草稿由 {{ draft.created_by_name || '其他用户' }} 制单，只有制单人可以继续编辑或提交。
        </div>

        <fieldset :disabled="!canEditDraft || busy || Boolean(pending)" class="config-fields">
          <div class="field-group">
            <span class="field-label">工序报工顺序</span>
            <div class="segmented-control" role="group" aria-label="工序报工顺序">
              <button type="button" :class="{ active: form.process_order_mode === 'sequential' }" @click="selectOrderMode('sequential')">按工艺顺序流转</button>
              <button type="button" :class="{ active: form.process_order_mode === 'out_of_order' }" @click="selectOrderMode('out_of_order')">允许跨工序补报</button>
            </div>
          </div>

          <div class="field-group">
            <span class="field-label">序列号报工规则</span>
            <div class="segmented-control" role="group" aria-label="序列号报工规则">
              <button type="button" :class="{ active: form.serial_process_report_mode === 'strict' }" @click="form.serial_process_report_mode = 'strict'">严格按当前工序</button>
              <button type="button" :class="{ active: form.serial_process_report_mode === 'controlled_backfill' }" @click="form.serial_process_report_mode = 'controlled_backfill'">受控跨工序补报</button>
            </div>
          </div>

          <div class="field-group full-width">
            <span class="field-label">报工数量上限</span>
            <ToggleSwitch v-model="form.limit_by_prev_process" label="上道工序累计上限" :disabled="form.process_order_mode !== 'sequential' || !canEditDraft || Boolean(pending)" />
            <p v-if="form.process_order_mode !== 'sequential'" class="field-hint">跨工序补报模式不适用上道工序累计上限，保存时自动关闭。</p>
            <ToggleSwitch v-model="form.limit_by_order_qty" label="订单总数上限" :disabled="!canEditDraft || Boolean(pending)" />
          </div>

          <div class="field-group full-width">
            <ToggleSwitch v-model="form.approval_enabled" label="启用报工审批" :disabled="!canEditDraft || Boolean(pending)" />
          </div>

          <label class="field-group full-width reason-field">
            <span class="field-label">修订原因</span>
            <textarea v-model="revisionReason" class="form-input" rows="3" maxlength="512" placeholder="说明本次工艺策略调整的业务原因" :readonly="!canEditDraft || Boolean(pending)"></textarea>
          </label>
        </fieldset>

        <div v-if="pending && openRevision.approved_at" class="workflow-note approved-note">
          已由 {{ openRevision.approved_by_name || '-' }} 于 {{ openRevision.approved_at }} 批准。
        </div>

        <div class="editor-actions">
          <button v-if="canEditDraft && processConfigDirty" type="button" class="btn" :disabled="busy" @click="discardChanges">撤销改动</button>
          <button v-if="canEditDraft" type="submit" class="btn btn-primary" :disabled="busy || !saveAllowed">
            {{ busy ? '处理中...' : (draft ? '保存草稿' : '保存为草稿') }}
          </button>
          <button v-if="draft && isDraftOwner && canSubmit" type="button" class="btn btn-primary" :disabled="busy || processConfigDirty" @click="submit">
            提交审批
          </button>
          <button v-if="pending && canReject && canApprovePending" type="button" class="btn btn-default" :disabled="busy || !rejectReason.trim()" @click="reject">驳回</button>
          <button v-if="pending && canApprove && canApprovePending" type="button" class="btn btn-primary" :disabled="busy" @click="approve">批准并发布</button>
        </div>
        <p v-if="pending && !canApprovePending && (canApprove || canReject)" class="field-hint action-hint">制单人不能审批或驳回自己的修订版，请使用其他账号。</p>
        <label v-if="pending && (canApprove || canReject)" class="reject-reason">
          <span>驳回原因（驳回时必填）</span>
          <input v-model="rejectReason" class="form-input" maxlength="512" placeholder="仅在驳回时填写">
        </label>
      </form>
    </section>

    <section v-if="canHistory" class="card history-panel">
      <div class="card-header process-config-header">
        <div><h3>修订历史</h3><p class="config-meta">已发布版本永久保留，只读可追溯。</p></div>
        <button type="button" class="btn btn-default btn-sm" :disabled="historyLoading" @click="loadHistory">刷新历史</button>
      </div>
      <div class="history-body">
        <div v-if="historyLoading" class="empty-state">加载中...</div>
        <div v-else-if="!revisions.length" class="empty-state">暂无修订记录</div>
        <div v-else class="table-wrap">
          <table class="history-table">
            <thead><tr><th>版本</th><th>状态</th><th>修订原因</th><th>变更字段</th><th>制单人</th><th>批准人</th><th>时间</th></tr></thead>
            <tbody>
              <tr v-for="revision in revisions" :key="revision.id">
                <td>V{{ revision.version }}</td>
                <td><span class="status-pill" :class="`status-${revision.status}`">{{ processConfigStatusLabel(revision.status) }}</span></td>
                <td>{{ revision.revision_reason || '-' }}</td>
                <td>{{ changedFields(revision) }}</td>
                <td>{{ revision.created_by_name || '-' }}</td>
                <td>{{ revision.approved_by_name || '-' }}</td>
                <td>{{ revision.updated_at || revision.created_at || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

import ToggleSwitch from '@/components/common/ToggleSwitch.vue'
import { useProcessConfig } from '@/composables/settings/useProcessConfig.js'
import { auth } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

const state = useProcessConfig()
const {
  config, current, openRevision, draft, pending, revisions, form, revisionReason,
  loading, historyLoading, busy, operationError,
  canCreate, canSubmit, canApprove, canReject, canEditDraft, isDraftOwner,
  canHistory,
  configValuesDirty, processConfigDirty,
  loadProcessConfig, loadHistory, saveDraft, submitRevision, approveRevision,
  rejectRevision, discardChanges, processConfigStatusLabel,
} = state

const rejectReason = ref('')
const currentUserId = computed(() => Number(auth.user?.id || auth.user?.user_id || 0))
const canApprovePending = computed(() => Number(pending.value?.created_by || 0) !== currentUserId.value)
const saveAllowed = computed(() => {
  if (!canEditDraft.value || !revisionReason.value.trim()) return false
  return Boolean(draft.value ? processConfigDirty.value : configValuesDirty.value)
})

const FIELD_LABELS = {
  process_order_mode: '报工顺序',
  serial_process_report_mode: '序列号规则',
  limit_by_prev_process: '上道工序上限',
  limit_by_order_qty: '订单数量上限',
  approval_enabled: '报工审批',
}

function orderModeLabel(value) {
  return value === 'out_of_order' ? '允许跨工序补报' : '按工艺顺序流转'
}
function serialModeLabel(value) {
  return value === 'controlled_backfill' ? '受控跨工序补报' : '严格按当前工序'
}
function flagLabel(value) { return [1, true, '1'].includes(value) ? '开启' : '关闭' }
function changedFields(revision) {
  return (revision.changed_fields || []).map(field => FIELD_LABELS[field] || field).join('、') || '-'
}
function selectOrderMode(value) {
  form.process_order_mode = value
  if (value === 'out_of_order') form.limit_by_prev_process = 0
}
async function save() {
  const wasDraft = Boolean(draft.value)
  try { await saveDraft(); showToast(wasDraft ? '草稿已保存' : '工艺修订草稿已创建') }
  catch (error) { showToast(error.message || operationError.value || '保存失败', 'error') }
}
async function submit() {
  try { await submitRevision(); showToast('工艺修订版已提交审批') }
  catch (error) { showToast(error.message || operationError.value || '提交失败', 'error') }
}
async function approve() {
  try { await approveRevision(); showToast('工艺修订版已批准并发布') }
  catch (error) { showToast(error.message || operationError.value || '批准失败', 'error') }
}
async function reject() {
  try {
    await rejectRevision(rejectReason.value)
    rejectReason.value = ''
    showToast('工艺修订版已驳回')
  } catch (error) { showToast(error.message || operationError.value || '驳回失败', 'error') }
}
function discard() { discardChanges(); rejectReason.value = '' }

defineExpose({ hasUnsavedChanges: state.hasUnsavedChanges })
</script>

<style scoped>
.process-config-page { display:grid; gap:var(--space-5); }
.process-config-header { align-items:flex-start; display:flex; gap:var(--space-4); justify-content:space-between; }
.process-config-header h3 { margin:0; }
.config-meta { color:var(--text-muted); font-size:var(--text-sm); margin:4px 0 0; }
.access-state { border:1px solid var(--border-light); border-radius:4px; flex:0 0 auto; font-size:var(--text-xs); padding:3px 8px; }
.access-state.editable { background:color-mix(in srgb, var(--success) 10%, transparent); color:var(--success); }
.access-state.readonly { background:var(--bg-hover); color:var(--text-muted); }
.current-summary { display:grid; gap:var(--space-3); grid-template-columns:repeat(5, minmax(0, 1fr)); padding:var(--space-4); }
.current-summary div { border-right:1px solid var(--border-light); display:grid; gap:4px; padding:0 var(--space-3); }
.current-summary div:first-child { padding-left:0; }
.current-summary div:last-child { border-right:0; }
.current-summary span { color:var(--text-muted); font-size:var(--text-xs); }
.current-summary strong { font-size:var(--text-sm); }
.operation-error { align-items:center; background:color-mix(in srgb, var(--danger) 8%, transparent); border:1px solid color-mix(in srgb, var(--danger) 25%, transparent); border-radius:4px; color:var(--danger); display:flex; justify-content:space-between; padding:var(--space-3); }
.editor-body { display:grid; gap:var(--space-4); padding:var(--space-5); }
.config-fields { border:0; display:grid; gap:var(--space-5); margin:0; min-width:0; padding:0; }
.field-group { display:grid; gap:var(--space-2); min-width:0; }
.full-width { grid-column:1 / -1; }
.field-label { color:var(--text-secondary); font-size:var(--text-sm); font-weight:600; }
.segmented-control { display:flex; gap:0; max-width:620px; }
.segmented-control button { background:var(--bg-surface); border:1px solid var(--border-light); color:var(--text-secondary); cursor:pointer; flex:1; min-height:38px; padding:8px 12px; }
.segmented-control button:first-child { border-radius:4px 0 0 4px; }
.segmented-control button:last-child { border-left:0; border-radius:0 4px 4px 0; }
.segmented-control button.active { background:var(--primary); border-color:var(--primary); color:#fff; }
.segmented-control button:disabled { cursor:default; opacity:.65; }
.field-hint { color:var(--text-muted); font-size:var(--text-xs); margin:0; }
.reason-field { max-width:760px; }
.workflow-note { border-radius:4px; font-size:var(--text-sm); padding:var(--space-3); }
.pending-note { background:color-mix(in srgb, var(--warning) 10%, transparent); border:1px solid color-mix(in srgb, var(--warning) 30%, transparent); color:var(--text-secondary); }
.locked-note { background:var(--bg-hover); border:1px solid var(--border-light); color:var(--text-muted); }
.approved-note { background:color-mix(in srgb, var(--success) 10%, transparent); border:1px solid color-mix(in srgb, var(--success) 30%, transparent); color:var(--text-secondary); }
.editor-actions { display:flex; flex-wrap:wrap; gap:var(--space-2); justify-content:flex-end; }
.action-hint { margin:0; text-align:right; }
.reject-reason { display:grid; gap:6px; margin-left:auto; max-width:520px; width:100%; }
.reject-reason span { color:var(--text-muted); font-size:var(--text-xs); }
.status-pill { border:1px solid var(--border-light); border-radius:4px; display:inline-block; font-size:var(--text-xs); padding:3px 8px; white-space:nowrap; }
.status-published { border-color:var(--success); color:var(--success); }
.status-pending_approval { border-color:var(--warning); color:var(--warning-dark); }
.status-rejected { border-color:var(--danger); color:var(--danger); }
.history-body { padding:0; }
.table-wrap { overflow:auto; }
.history-table { border-collapse:collapse; font-size:var(--text-sm); min-width:900px; width:100%; }
.history-table th, .history-table td { border-bottom:1px solid var(--border-light); padding:10px 12px; text-align:left; vertical-align:top; }
.history-table th { background:var(--bg-hover); color:var(--text-muted); font-weight:600; }
.empty-state { color:var(--text-placeholder); padding:36px; text-align:center; }
@media (max-width:900px) { .current-summary { grid-template-columns:repeat(2, minmax(0, 1fr)); } .current-summary div { border-right:0; padding:0; } }
@media (max-width:600px) { .current-summary { grid-template-columns:1fr; } .process-config-header { align-items:flex-start; flex-direction:column; } .segmented-control { flex-direction:column; } .segmented-control button, .segmented-control button:first-child, .segmented-control button:last-child { border-left:1px solid var(--border-light); border-radius:4px; } .segmented-control button + button { margin-top:4px; } }
</style>
