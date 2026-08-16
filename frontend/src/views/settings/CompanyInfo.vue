<template>
  <div class="company-info-page">
    <section class="card company-info-panel">
      <div class="card-header company-info-header">
        <div>
          <h3>公司资料</h3>
          <p v-if="updatedAt" class="company-info-meta">
            V{{ version }} · {{ updatedAt }}<span v-if="updatedByName"> · {{ updatedByName }}</span>
          </p>
        </div>
        <span class="access-state" :class="canEdit ? 'editable' : 'readonly'">
          {{ canEdit ? '可编辑' : '仅查看' }}
        </span>
      </div>

      <div class="card-body">
        <div v-if="loading" class="company-info-empty">加载中...</div>
        <form v-else class="company-info-form" @submit.prevent="saveSettings">
          <label class="field-row">
            <span>公司名称</span>
            <input v-model="edits.company_name" class="form-input" :readonly="!canEdit" maxlength="200">
          </label>
          <div class="field-grid">
            <label class="field-row">
              <span>联系人</span>
              <input v-model="edits.contact" class="form-input" :readonly="!canEdit" maxlength="100">
            </label>
            <label class="field-row">
              <span>联系电话</span>
              <input v-model="edits.phone" class="form-input" :readonly="!canEdit" maxlength="50" inputmode="tel">
            </label>
          </div>
          <label class="field-row">
            <span>公司地址</span>
            <input v-model="edits.address" class="form-input" :readonly="!canEdit" maxlength="500">
          </label>
          <label class="field-row">
            <span>公司简介</span>
            <textarea v-model="edits.description" class="form-input" :readonly="!canEdit" maxlength="2000" rows="4"></textarea>
          </label>

          <div v-if="conflict" class="conflict-banner">
            <span>服务器中已有更新，当前草稿不能直接覆盖。</span>
            <button type="button" class="btn btn-sm" @click="reloadAfterConflict">刷新资料</button>
          </div>

          <div v-if="canEdit" class="form-actions">
            <button type="button" class="btn" :disabled="!companyInfoDirty || saving" @click="discardChanges">
              撤销改动
            </button>
            <button type="submit" class="btn btn-primary" :disabled="!companyInfoDirty || saving || conflict">
              {{ saving ? '保存中...' : '保存资料' }}
            </button>
          </div>
        </form>
      </div>
    </section>

    <section class="card company-history-panel">
      <div class="card-header company-info-header">
        <div>
          <h3>修订历史</h3>
          <p class="company-info-meta">
            保留三年<span v-if="historyRedacted"> · 联系人、电话和地址已脱敏</span>
          </p>
        </div>
        <span v-if="canAuditHistory" class="access-state audit">完整历史</span>
      </div>
      <div class="card-body history-body">
        <div v-if="historyLoading" class="company-info-empty">加载中...</div>
        <div v-else-if="!revisions.length" class="company-info-empty">暂无修订记录</div>
        <div v-else class="table-wrap">
          <table class="history-table">
            <thead>
              <tr><th>版本</th><th>时间</th><th>操作人</th><th>变更字段</th><th>公司名称</th><th>联系人</th><th>电话</th><th>地址</th><th>公司简介</th></tr>
            </thead>
            <tbody>
              <tr v-for="revision in revisions" :key="revision.id">
                <td>V{{ revision.version }}</td>
                <td>{{ revision.created_at }}</td>
                <td>{{ revision.actor_name || '系统迁移' }}</td>
                <td>{{ (revision.changed_fields || []).map(fieldLabel).join('、') || '-' }}</td>
                <td>{{ revision.company_name || '-' }}</td>
                <td>{{ revision.contact || '-' }}</td>
                <td>{{ revision.phone || '-' }}</td>
                <td class="address-cell">{{ revision.address || '-' }}</td>
                <td class="description-cell">{{ revision.description || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
</template>

<script>
import { useCompanyInfo } from '@/composables/settings/useCompanyInfo.js'

const FIELD_LABELS = {
  company_name: '公司名称',
  contact: '联系人',
  phone: '联系电话',
  address: '公司地址',
  description: '公司简介',
}

export default {
  setup() {
    return {
      ...useCompanyInfo(),
      fieldLabel: field => FIELD_LABELS[field] || field,
    }
  },
}
</script>

<style scoped>
.company-info-page { display:grid; gap:var(--space-5); }
.company-info-panel, .company-history-panel { margin:0; }
.company-info-header { display:flex; align-items:flex-start; justify-content:space-between; gap:var(--space-4); }
.company-info-header h3 { margin:0; }
.company-info-meta { margin:4px 0 0; color:var(--text-muted); font-size:var(--text-sm); }
.access-state { flex:0 0 auto; padding:3px 8px; border-radius:4px; font-size:var(--text-xs); border:1px solid var(--border-light); }
.access-state.editable { color:var(--success); background:color-mix(in srgb, var(--success) 10%, transparent); }
.access-state.readonly { color:var(--text-muted); background:var(--bg-hover); }
.access-state.audit { color:var(--primary); background:color-mix(in srgb, var(--primary) 10%, transparent); }
.company-info-form { max-width:760px; display:grid; gap:var(--space-4); }
.field-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:var(--space-4); }
.field-row { display:grid; gap:6px; color:var(--text-secondary); font-size:var(--text-sm); font-weight:500; }
.field-row input[readonly], .field-row textarea[readonly] { background:var(--bg-hover); color:var(--text-secondary); cursor:default; }
.form-actions { display:flex; justify-content:flex-end; gap:var(--space-2); padding-top:var(--space-2); }
.conflict-banner { display:flex; align-items:center; justify-content:space-between; gap:var(--space-3); padding:var(--space-3); color:var(--danger); background:color-mix(in srgb, var(--danger) 8%, transparent); border:1px solid color-mix(in srgb, var(--danger) 25%, transparent); border-radius:4px; }
.company-info-empty { padding:32px; text-align:center; color:var(--text-placeholder); }
.history-body { padding:0; }
.table-wrap { overflow:auto; }
.history-table { width:100%; min-width:1200px; border-collapse:collapse; font-size:var(--text-sm); }
.history-table th, .history-table td { padding:10px 12px; text-align:left; border-bottom:1px solid var(--border-light); vertical-align:top; }
.history-table th { color:var(--text-muted); font-weight:600; background:var(--bg-hover); }
.address-cell { min-width:180px; max-width:320px; white-space:normal; }
.description-cell { min-width:200px; max-width:360px; white-space:normal; }
@media (max-width:700px) {
  .field-grid { grid-template-columns:1fr; }
  .company-info-header { align-items:center; }
  .conflict-banner { align-items:flex-start; flex-direction:column; }
}
</style>
