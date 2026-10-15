<template>
  <div>
    <div class="standard-filter-bar">
      <div class="standard-scope-buttons" aria-label="标准工时筛选">
        <button
          v-for="option in standardScopeOptions"
          :key="option.key"
          class="scope-btn"
          :class="{ active: standardFilters.scope === option.key }"
          @click="setStandardScope(option.key)"
        >
          {{ option.label }} <span>{{ option.count }}</span>
        </button>
      </div>
      <select class="form-input route-select" v-model="standardFilters.route_id" @change="onFilterRouteChange">
        <option value="">全部工序路线</option>
        <option v-for="route in processRoutes" :key="route.id" :value="route.id">{{ route.name }}</option>
      </select>
      <select class="form-input process-select" v-model="standardFilters.process_id" @change="load">
        <option value="">全部路线工序</option>
        <option v-for="p in filterRouteProcesses" :key="p.id" :value="p.id">{{ p.seqLabel }}{{ p.name }}</option>
      </select>
      <label class="history-toggle">
        <input type="checkbox" v-model="includeHistory" @change="load">
        查看历史路线版本
      </label>
      <button class="btn btn-default btn-sm" :disabled="!hasStandardFilters" @click="clearStandardFilters">清空筛选</button>
    </div>

    <div v-if="isLoading" class="empty">
      <div class="empty-icon">⏳</div>
      <div class="empty-text">正在加载标准工时...</div>
    </div>

    <template v-else>
      <div v-if="standardGroups.length" class="route-collapse-toolbar">
        <span class="standard-overview">当前显示 {{ visibleStandardItemCount }} 道工序 / {{ standardOverview.total }} 道</span>
        <button class="btn btn-default btn-sm" @click="collapseAllGroups">全部收起</button>
        <button class="btn btn-default btn-sm" @click="expandAllGroups">全部展开</button>
      </div>

      <div v-if="standardGroups.length" class="route-standard-list">
        <div
          v-for="group in standardGroups"
          :key="standardGroupKey(group)"
          class="route-standard-card"
          :class="{ 'route-standard-card-warning': unconfiguredStandardCount(group) > 0 }"
        >
          <div class="route-standard-header">
            <div class="route-header-main">
              <div class="route-standard-title-row">
                <div class="route-standard-title">{{ group.route_name || '未归属工序路线' }}</div>
                <span v-if="unconfiguredStandardCount(group)" class="warning-chip">未设置 {{ unconfiguredStandardCount(group) }} 道</span>
              </div>
              <div class="route-standard-meta">
                <span>当前显示 {{ group.items.length }} 道</span>
                <span>全部 {{ totalStandardCount(group) }} 道</span>
                <span>已配置 {{ configuredStandardCount(group) }} 道</span>
                <span>启用 {{ activeStandardCount(group) }} 道</span>
              </div>
            </div>
            <div class="route-header-actions">
              <button class="btn btn-default btn-sm" @click="toggleGroupCollapse(group)">{{ isGroupCollapsed(group) ? '展开' : '收起' }}</button>
              <button class="btn btn-default btn-sm" :disabled="!isEditableGroup(group)" @click="openStandardGroup(group)">
                {{ isEditableGroup(group) ? '批量编辑' : '仅查看' }}
              </button>
            </div>
          </div>
          <div v-show="!isGroupCollapsed(group)" class="table-wrap route-standard-table-wrap">
            <table class="data-table route-standard-table" style="min-width:1040px">
              <thead><tr>
                <th class="sequence-col">序号</th><th>顺序</th><th>工序路线版本</th><th>工序 / 版本</th><th>单件标准</th><th>准备工时</th><th>难度系数</th><th>生效日期</th><th>状态</th><th>备注</th><th class="operation-col">操作</th>
              </tr></thead>
              <tbody>
                <tr
                  v-for="(row, rowIndex) in group.items"
                  :key="row.id || `${group.route_id}-${row.process_id}`"
                  class="route-standard-row"
                  :class="{ 'row-unconfigured': !row.id, 'row-inactive': row.id && row.status !== 'active' }"
                >
                  <td class="sequence-cell">{{ rowIndex + 1 }}</td>
                  <td>{{ routeSeqLabel(row.route_seq_order) }}</td>
                  <td>V{{ row.route_version || '-' }}<small class="version-status">{{ row.route_version_status || '未绑定' }}</small></td>
                  <td><b>{{ row.process_name || '-' }}</b><small class="version-status">工序 V{{ row.process_version || '-' }}</small></td>
                  <td>{{ row.id ? `${row.standard_minutes_per_unit || 0} 分/件` : '-' }}</td>
                  <td>{{ row.id ? `${row.setup_minutes || 0} 分` : '-' }}</td>
                  <td>{{ row.id ? (row.difficulty_factor || 1) : '-' }}</td>
                  <td>{{ row.effective_from || '-' }}</td>
                  <td><span class="badge" :class="standardStatusClass(row)">{{ standardStatusLabel(row) }}</span></td>
                  <td class="remark-cell" :title="row.remark || ''">{{ row.remark || '-' }}</td>
                  <td class="operation-cell">
                    <button class="btn btn-default btn-sm" :disabled="!isEditableGroup(group)" @click="openStandardGroup(group)">
                      {{ isEditableGroup(group) ? '编辑路线' : '仅查看' }}
                    </button>
                    <button class="btn btn-default btn-sm" style="color:var(--danger)" :disabled="!isEditableGroup(group) || !row.id || row.status!=='active'" @click="deactivateStandard(row)">停用</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <div v-else class="empty">
        <div class="empty-icon">⏱️</div>
        <div class="empty-text">{{ hasStandardFilters ? '当前筛选条件下暂无标准工时' : '暂无工序路线标准工时' }}</div>
        <button class="btn btn-primary btn-sm" style="margin-top:var(--space-2)" @click="openStandardGroup()">按工序路线一次性添加</button>
      </div>
    </template>

    <teleport to="body">
      <div v-if="showStandardModal" class="modal-overlay route-standard-modal-overlay" @click.self="showStandardModal=false">
        <div class="modal route-standard-modal">
          <div class="modal-header"><h3>按工序路线批量维护标准工时</h3></div>
          <div class="modal-body route-standard-modal-body">
            <div class="form-row route-standard-form-row">
            <div class="form-group">
              <label>工序路线</label>
              <select class="form-input" v-model="standardForm.route_id" @change="onStandardRouteChange">
                <option value="">请选择工序路线</option>
                <option v-for="route in processRoutes" :key="route.id" :value="route.id">{{ route.name }}</option>
              </select>
            </div>
            <div class="form-group">
              <label>路线版本（精确绑定）</label>
              <select class="form-input" v-model="standardForm.route_version_id" @change="onStandardRouteVersionChange" :disabled="!routeVersionOptions.length">
                <option value="">请选择路线版本</option>
                <option v-for="version in routeVersionOptions" :key="version.route_version_id" :value="version.route_version_id">
                  V{{ version.route_version }} · {{ version.route_version_status }}{{ version.is_current_version ? ' · 当前' : '' }}
                </option>
              </select>
              <small class="form-help">未选择版本时仅允许查看；选择具体版本后才会写入精确路线/工序版本。</small>
            </div>
            <div class="form-group">
              <label>统一生效日期</label>
              <input class="form-input" type="date" v-model="standardForm.effective_from">
            </div>
          </div>
          <div v-if="standardForm.route_id && !standardRows.length" class="route-warning">
            当前工序路线没有配置工序，请先到“基础设置 > 工序路线”维护路线工序。
          </div>
          <div v-if="standardRows.length" class="batch-toolbar">
            <span>本次维护 {{ standardRows.length }} 道工序，已启用 {{ enabledRowsCount }} 道</span>
            <button class="btn btn-default btn-sm" @click="setAllStandardRows(true)">全部启用</button>
            <button class="btn btn-default btn-sm" @click="setAllStandardRows(false)">全部停用</button>
          </div>
          <div v-if="standardRows.length" class="batch-defaults">
            <label>默认单件<input class="form-input compact-input" type="number" min="0.1" step="0.1" v-model.number="batchDefaults.standard_minutes_per_unit"></label>
            <label>默认准备<input class="form-input compact-input" type="number" min="0" step="0.1" v-model.number="batchDefaults.setup_minutes"></label>
            <label>默认系数<input class="form-input compact-input" type="number" min="0.1" step="0.01" v-model.number="batchDefaults.difficulty_factor"></label>
            <button class="btn btn-default btn-sm" @click="fillEmptyRowsWithDefaults">默认值填充空白</button>
            <button class="btn btn-default btn-sm" @click="applyFirstEnabledRowToAll">首行应用到全部</button>
          </div>
            <div v-if="standardRows.length" class="table-wrap standard-edit-table-wrap">
              <table class="data-table route-standard-edit-table">
              <thead><tr>
                <th style="width:70px">启用</th><th style="width:70px">顺序</th><th class="standard-edit-process-col">工序</th><th>单件标准（分钟）</th><th>准备工时（分钟）</th><th>难度系数</th><th class="standard-edit-remark-col">备注</th><th class="operation-col">操作</th>
              </tr></thead>
              <tbody>
                <tr v-for="(row, index) in standardRows" :key="row.process_id">
                  <td><input type="checkbox" v-model="row.enabled"></td>
                  <td>{{ routeSeqLabel(row.seq) }}</td>
                  <td class="standard-edit-process"><b>{{ row.process_name }}</b></td>
                  <td><input class="form-input compact-input" type="number" min="0.1" step="0.1" :disabled="!row.enabled" v-model.number="row.standard_minutes_per_unit"></td>
                  <td><input class="form-input compact-input" type="number" min="0" step="0.1" :disabled="!row.enabled" v-model.number="row.setup_minutes"></td>
                  <td><input class="form-input compact-input" type="number" min="0.1" step="0.01" :disabled="!row.enabled" v-model.number="row.difficulty_factor"></td>
                  <td><input class="form-input standard-edit-remark" :disabled="!row.enabled" v-model="row.remark" placeholder="可选"></td>
                  <td class="operation-cell"><button class="btn btn-default btn-sm" :disabled="index === 0" @click="copyPreviousRow(index)">复制上一行</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-default" :disabled="isSaving" @click="showStandardModal=false">取消</button>
            <button class="btn btn-primary" :disabled="isSaving" @click="saveStandard">{{ isSaving ? '保存中...' : '保存整条路线工时' }}</button>
          </div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup>
import { useWorkTimeStandardsPanel } from '@/composables/workTime/useWorkTimeStandardsPanel.js'

const props = defineProps({
  keyword: { type: String, default: '' },
  processRoutes: { type: Array, default: () => [] },
  processes: { type: Array, default: () => [] },
})
const emit = defineEmits(['changed'])

const {
  today,
  processRoutesRef,
  standardRows,
  enabledRowsCount,
  normalizeRouteProcesses,
  buildStandardRows,
  setAllStandardRows,
  validateStandardRows,
  buildSavePayload,
  standards,
  allStandardGroups,
  collapsedGroupKeys,
  isLoading,
  isSaving,
  showStandardModal,
  standardFilters,
  includeHistory,
  standardForm,
  routeVersionOptions,
  batchDefaults,
  filterRouteProcesses,
  standardGroups,
  standardOverview,
  visibleStandardItemCount,
  hasStandardFilters,
  standardScopeOptions,
  groupAllItems,
  activeStandardCount,
  configuredStandardCount,
  unconfiguredStandardCount,
  totalStandardCount,
  matchesStandardScope,
  setStandardScope,
  clearStandardFilters,
  standardGroupKey,
  isEditableGroup,
  isGroupCollapsed,
  toggleGroupCollapse,
  collapseAllGroups,
  expandAllGroups,
  standardStatusLabel,
  standardStatusClass,
  load,
  onFilterRouteChange,
  onStandardRouteChange,
  onStandardRouteVersionChange,
  openStandardGroup,
  isEmptyValue,
  copyStandardValues,
  fillEmptyRowsWithDefaults,
  applyFirstEnabledRowToAll,
  copyPreviousRow,
  saveStandard,
  deactivateStandard,
  routeSeqLabel
} = useWorkTimeStandardsPanel(props, emit)

defineExpose({ load, openStandardGroup })
</script>

<style scoped>
.standard-filter-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  flex-wrap: wrap;
}
.standard-scope-buttons {
  display: flex;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
}
.scope-btn {
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: var(--text-sm);
  padding: 6px 10px;
  white-space: nowrap;
}
.scope-btn.active {
  background: var(--primary-color);
  color: #fff;
}
.scope-btn span {
  margin-left: 4px;
  opacity: .82;
}
.route-select { width: 240px; }
.process-select { width: 200px; }
.history-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  white-space: nowrap;
}
.standard-overview {
  margin-right: auto;
  color: var(--text-secondary);
  font-size: var(--text-sm);
}
.route-standard-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.route-standard-card {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  background: var(--bg-primary);
  overflow: hidden;
}
.route-standard-card-warning {
  border-color: var(--warning);
}
.route-collapse-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  justify-content: flex-end;
  margin-bottom: var(--space-3);
}
.route-standard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
}
.route-header-main { min-width: 0; }
.route-standard-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.route-header-actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
  white-space: nowrap;
}
.route-standard-title {
  font-weight: 700;
  color: var(--text-primary);
}
.warning-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  background: var(--warning-light);
  color: var(--warning-dark);
  font-size: var(--text-xs);
  padding: 2px 8px;
}
.route-standard-meta {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-top: 4px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.route-standard-table-wrap {
  border: 0;
  border-radius: 0;
}
.route-standard-table {
  border-collapse: separate;
  border-spacing: 0 8px;
}
.sequence-col,
.sequence-cell {
  width: 64px;
  min-width: 64px;
  text-align: center;
  white-space: nowrap;
}
.route-standard-row td {
  background: var(--bg-primary);
  border-top: 1px solid var(--border-color);
  border-bottom: 1px solid var(--border-color);
}
.route-standard-row td:first-child {
  border-left: 1px solid var(--border-color);
  border-radius: var(--radius-md) 0 0 var(--radius-md);
}
.route-standard-row td:last-child {
  border-right: 1px solid var(--border-color);
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
}
.row-unconfigured td { background: rgba(245, 158, 11, .08); }
.row-inactive td { color: var(--text-secondary); }
.remark-cell {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.operation-col {
  width: 170px;
  min-width: 170px;
  white-space: nowrap;
}
.operation-cell {
  white-space: nowrap;
}
.operation-cell .btn + .btn {
  margin-left: var(--space-1);
}
.route-warning {
  padding: 10px 12px;
  background: var(--warning-light);
  color: var(--warning-dark);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-3);
}
.batch-toolbar,
.batch-defaults {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  color: var(--text-secondary);
  flex-wrap: wrap;
}
.batch-defaults {
  padding: var(--space-3);
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
}
.batch-defaults label {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-sm);
  white-space: nowrap;
}
.compact-input {
  min-width: 110px;
}
.route-standard-modal-overlay {
  position: fixed;
  inset: 0;
  align-items: flex-start;
  box-sizing: border-box;
  padding: 24px;
  overflow: hidden;
  overscroll-behavior: contain;
  animation: none;
}
.route-standard-modal {
  width: min(1180px, calc(100vw - 48px));
  max-width: calc(100vw - 48px);
  max-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: none;
  transform: none;
}
.route-standard-modal-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.route-standard-modal .modal-footer {
  flex-shrink: 0;
}
.route-standard-form-row {
  align-items: flex-end;
}
.standard-edit-table-wrap {
  max-height: 52vh;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  margin: 0;
  overflow: auto;
}
.route-standard-edit-table {
  min-width: 1040px;
}
.route-standard-edit-table th {
  position: sticky;
  top: 0;
  z-index: 2;
}
.route-standard-edit-table td {
  vertical-align: middle;
}
.standard-edit-process-col,
.standard-edit-process {
  min-width: 180px;
  max-width: 260px;
}
.standard-edit-process {
  white-space: normal;
  line-height: 1.45;
}
.standard-edit-remark-col,
.standard-edit-remark {
  min-width: 180px;
}
.route-standard-edit-table .compact-input {
  width: 100%;
  min-width: 96px;
}
@media (max-width: 768px) {
  .standard-filter-bar,
  .route-standard-header,
  .route-collapse-toolbar,
  .batch-toolbar,
  .batch-defaults {
    align-items: stretch;
    flex-direction: column;
  }
  .standard-scope-buttons {
    overflow-x: auto;
  }
  .route-select,
  .process-select,
  .standard-filter-bar .btn,
  .route-header-actions,
  .route-header-actions .btn,
  .route-collapse-toolbar .btn,
  .batch-toolbar .btn,
  .batch-defaults .btn {
    width: 100%;
  }
  .route-header-actions {
    flex-direction: column;
  }
  .standard-overview {
    margin-right: 0;
  }
  .route-standard-meta {
    gap: var(--space-2);
  }
  .route-standard-modal-overlay {
    padding: 12px;
  }
  .route-standard-modal {
    width: calc(100vw - 24px);
    max-width: calc(100vw - 24px);
    max-height: calc(100vh - 24px);
  }
  .route-standard-modal-body {
    padding: var(--space-4);
  }
  .standard-edit-table-wrap {
    max-height: 48vh;
    margin: 0 -4px;
  }
}
</style>
