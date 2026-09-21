<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  node: { type: Object, default: null },
  calendar: { type: Object, default: null },
  calendarLoading: Boolean,
  calendarError: { type: String, default: '' },
  overrides: { type: Array, default: () => [] },
  form: { type: Object, required: true },
  loading: Boolean,
  error: { type: String, default: '' },
  saving: Boolean,
  canManage: Boolean,
  onRetry: { type: Function, required: true },
  onRetryCalendar: { type: Function, default: () => {} },
  onSave: { type: Function, required: true },
  onCancelOverride: { type: Function, required: true },
})

const emit = defineEmits(['dirty-change', 'saved'])
const digest = value => JSON.stringify(value || {})
const initialDigest = ref(digest(props.form))
const submitting = ref(false)
const formDisabled = computed(() => props.saving || submitting.value)

const calendarName = computed(() => (
  props.calendar?.calendar_name || props.calendar?.name || `日历 #${props.node?.calendar_id || '-'}`
))
const shiftMinutes = computed(() => (props.calendar?.shifts || []).reduce((total, shift) => {
  const start = Number(shift.start_minute)
  const end = Number(shift.end_minute)
  return total + (Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, end - start) : 0)
}, 0))
const effectiveMinutes = computed(() => (
  props.calendar?.daily_minutes
  ?? props.calendar?.effective_minutes
  ?? (props.calendar?.shifts?.length ? shiftMinutes.value : null)
  ?? props.node?.capacity_minutes
  ?? 0
))
const orderedOverrides = computed(() => [...props.overrides].sort((left, right) => {
  const leftTime = Date.parse(left.created_at || left.start_at || '') || 0
  const rightTime = Date.parse(right.created_at || right.start_at || '') || 0
  return rightTime - leftTime
}))

const typeLabel = value => ({
  unavailable: '不可用',
  maintenance: '维护',
  overtime: '加班',
  holiday: '停工假日',
}[value] || value || '-')
const statusLabel = value => {
  const normalized = String(value || '').toLowerCase()
  return ({
    active: '生效中',
    cancelled: '已取消',
    canceled: '已取消',
    completed: '已完成',
    expired: '已过期',
  }[normalized] || value || '-')
}
const isCancelable = value => String(value || '').toLowerCase() === 'active'

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

watch(
  () => props.form,
  value => {
    initialDigest.value = digest(value)
    if (!submitting.value) emit('dirty-change', false)
  },
)

watch(
  () => props.form,
  value => {
    if (!submitting.value) emit('dirty-change', digest(value) !== initialDigest.value)
  },
  { deep: true },
)

async function submit() {
  submitting.value = true
  try {
    const result = await props.onSave()
    if (!result) return
    initialDigest.value = digest(props.form)
    emit('dirty-change', false)
    emit('saved', result)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="node-calendar-panel" aria-labelledby="node-calendar-title">
    <header class="node-calendar-panel__header">
      <div>
        <h3 id="node-calendar-title">工作日历</h3>
        <p>{{ node ? `${node.node_code || ''} ${node.node_name || ''}`.trim() : '请选择生产节点' }}</p>
      </div>
    </header>

    <div v-if="!node" class="node-calendar-panel__notice">请选择生产节点查看工作日历</div>
    <template v-else>
      <section class="node-calendar-panel__region" aria-labelledby="base-calendar-title">
        <h4 id="base-calendar-title">基础日历</h4>
        <div v-if="calendarLoading" class="node-calendar-panel__notice" role="status">
          正在加载基础工作日历…
        </div>
        <div v-else-if="calendarError && !calendar" class="node-calendar-panel__notice node-calendar-panel__notice--error" role="alert">
          <span>{{ calendarError }}</span>
          <button
            data-test="base-calendar-retry"
            type="button"
            class="btn btn-default"
            @click="onRetryCalendar"
          >重试</button>
        </div>
        <template v-else>
          <div v-if="calendarError" class="node-calendar-panel__notice node-calendar-panel__notice--error" role="alert">
            <span>{{ calendarError }}，显示最近一次工作日历。</span>
            <button
              data-test="base-calendar-retry"
              type="button"
              class="btn btn-default"
              @click="onRetryCalendar"
            >重试</button>
          </div>
          <dl class="node-calendar-panel__summary">
            <div><dt>日历名称</dt><dd>{{ calendarName }}</dd></div>
            <div><dt>每日有效分钟</dt><dd>{{ effectiveMinutes }} 分钟</dd></div>
          </dl>
        </template>
      </section>

      <section class="node-calendar-panel__region" aria-labelledby="calendar-overrides-title">
        <div class="node-calendar-panel__section-heading">
          <h4 id="calendar-overrides-title">日历例外</h4>
          <span>{{ orderedOverrides.length }} 条</span>
        </div>

        <div v-if="error" class="node-calendar-panel__notice node-calendar-panel__notice--error" role="alert">
          <span>{{ error }}</span>
          <button data-test="calendar-retry" type="button" class="btn btn-default" :disabled="loading" @click="onRetry">
            重试
          </button>
        </div>
        <div v-else-if="loading" class="node-calendar-panel__notice" role="status">正在加载日历例外…</div>
        <div v-else-if="!orderedOverrides.length" class="node-calendar-panel__notice">暂无日历例外</div>
        <div v-else class="node-calendar-panel__table-wrap">
          <table class="node-calendar-panel__table">
            <thead>
              <tr>
                <th>类型</th>
                <th>开始时间</th>
                <th>结束时间</th>
                <th>状态</th>
                <th>原因</th>
                <th v-if="canManage">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in orderedOverrides" :key="item.id" data-test="override-row">
                <td>{{ typeLabel(item.override_type) }}</td>
                <td>{{ formatDateTime(item.start_at) }}</td>
                <td>{{ formatDateTime(item.end_at) }}</td>
                <td>{{ statusLabel(item.status) }}</td>
                <td>{{ item.reason || '-' }}</td>
                <td v-if="canManage">
                  <button
                    v-if="isCancelable(item.status)"
                    data-test="override-cancel"
                    type="button"
                    class="btn btn-default"
                    :disabled="saving"
                    @click="onCancelOverride(item)"
                  >
                    取消
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="canManage" class="node-calendar-panel__region" aria-labelledby="add-override-title">
        <h4 id="add-override-title">新增日历例外</h4>
        <form class="node-calendar-panel__form" @submit.prevent="submit">
          <fieldset data-test="override-fields" class="node-calendar-panel__fields" :disabled="formDisabled">
            <label>
              <span>开始时间</span>
              <input v-model="form.start_at" data-test="override-start" type="datetime-local" class="form-input" required>
            </label>
            <label>
              <span>结束时间</span>
              <input v-model="form.end_at" data-test="override-end" type="datetime-local" class="form-input" required>
            </label>
            <label>
              <span>例外类型</span>
              <select v-model="form.override_type" data-test="override-type" class="form-input">
                <option value="unavailable">不可用</option>
                <option value="maintenance">维护</option>
                <option value="overtime">加班</option>
                <option value="holiday">停工假日</option>
              </select>
            </label>
            <label class="node-calendar-panel__wide">
              <span>调整原因</span>
              <textarea v-model="form.reason" data-test="override-reason" class="form-input" rows="3" required />
            </label>
            <label class="node-calendar-panel__wide">
              <span>幂等键</span>
              <input v-model="form.idempotency_key" data-test="override-idempotency-key" class="form-input" required>
            </label>
            <div class="node-calendar-panel__actions">
              <button data-test="override-save" type="submit" class="btn btn-primary">
                {{ formDisabled ? '正在保存…' : '保存日历例外' }}
              </button>
            </div>
          </fieldset>
        </form>
      </section>
    </template>
  </section>
</template>

<style scoped>
.node-calendar-panel {
  max-width: 1080px;
  margin: 0 auto;
}

.node-calendar-panel__header,
.node-calendar-panel__section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.node-calendar-panel__header h3,
.node-calendar-panel__header p,
.node-calendar-panel__region h4 {
  margin: 0;
}

.node-calendar-panel__header p {
  margin-top: 6px;
  color: var(--text-secondary);
}

.node-calendar-panel__region {
  margin-top: 18px;
  padding: 16px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
}

.node-calendar-panel__section-heading span {
  color: var(--text-placeholder);
  font-size: 12px;
}

.node-calendar-panel__summary,
.node-calendar-panel__fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin: 14px 0 0;
}

.node-calendar-panel__fields {
  min-width: 0;
  padding: 0;
  border: 0;
}

.node-calendar-panel__summary div {
  padding: 12px;
  background: var(--bg-subtle);
  border-radius: var(--radius-sm);
}

.node-calendar-panel__summary dt {
  color: var(--text-placeholder);
  font-size: 12px;
}

.node-calendar-panel__summary dd {
  margin: 5px 0 0;
  color: var(--text-primary);
  font-weight: 600;
}

.node-calendar-panel__notice {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 64px;
  margin-top: 12px;
  color: var(--text-placeholder);
  text-align: center;
}

.node-calendar-panel__notice--error {
  color: var(--danger);
}

.node-calendar-panel__table-wrap {
  margin-top: 12px;
  overflow-x: auto;
}

.node-calendar-panel__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.node-calendar-panel__table th,
.node-calendar-panel__table td {
  padding: 10px;
  border-bottom: 1px solid var(--border-light);
  text-align: left;
  vertical-align: top;
}

.node-calendar-panel__table th {
  color: var(--text-secondary);
  white-space: nowrap;
}

.node-calendar-panel__fields label {
  display: grid;
  gap: 7px;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.node-calendar-panel__wide,
.node-calendar-panel__actions {
  grid-column: 1 / -1;
}

.node-calendar-panel__actions {
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 899px) {
  .node-calendar-panel__summary,
  .node-calendar-panel__fields {
    grid-template-columns: 1fr;
  }
}
</style>
