<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  form: { type: Object, required: true },
  processOptions: { type: Array, default: () => [] },
  calendars: { type: Array, default: () => [] },
  canManage: Boolean,
  saving: Boolean,
  onReset: { type: Function, default: () => {} },
  onSave: { type: Function, required: true },
})

const emit = defineEmits(['dirty-change', 'saved'])
const digest = value => JSON.stringify(value || {})
const initialDigest = ref(digest(props.form))

const processLabel = computed(() => (
  props.processOptions.find(item => String(item.id) === String(props.form.process_id))?.name
  || `工序 #${props.form.process_id || '-'}`
))
const calendarLabel = computed(() => {
  const calendar = props.calendars.find(item => String(item.id) === String(props.form.calendar_id))
  return calendar?.calendar_name || calendar?.name || `日历 #${props.form.calendar_id || '-'}`
})
const capacityLabel = computed(() => ({
  exclusive: '独占产能',
  batch: '批处理产能',
  shared: '共享产能',
}[props.form.capacity_mode] || props.form.capacity_mode || '-'))
const statusLabel = computed(() => ({
  active: '启用',
  maintenance: '维护中',
  inactive: '停用',
}[props.form.status] || props.form.status || '-'))

watch(
  () => props.form,
  value => {
    initialDigest.value = digest(value)
    emit('dirty-change', false)
  },
)

watch(
  () => props.form,
  value => emit('dirty-change', digest(value) !== initialDigest.value),
  { deep: true },
)

async function submit() {
  const result = await props.onSave()
  if (!result) return
  initialDigest.value = digest(props.form)
  emit('dirty-change', false)
  emit('saved', result)
}
</script>

<template>
  <section class="node-editor-panel" aria-labelledby="node-editor-title">
    <header class="node-editor-panel__header">
      <div>
        <h3 id="node-editor-title">{{ form.id ? '编辑生产节点' : '新建生产节点' }}</h3>
        <p>{{ form.id ? '修改节点基本信息，所属工序不可变更。' : '配置节点所属工序、产能模式和工作日历。' }}</p>
      </div>
    </header>

    <form v-if="canManage" class="node-editor-panel__form" @submit.prevent="submit">
      <label>
        <span>所属工序</span>
        <select
          v-model.number="form.process_id"
          data-test="node-process"
          class="form-input"
          :disabled="Boolean(form.id)"
          required
        >
          <option value="">请选择工序</option>
          <option v-for="process in processOptions" :key="process.id" :value="process.id">{{ process.name }}</option>
        </select>
      </label>
      <label>
        <span>节点编码</span>
        <input v-model="form.node_code" data-test="node-code" class="form-input" required>
      </label>
      <label>
        <span>节点名称</span>
        <input v-model="form.node_name" data-test="node-name" class="form-input" required>
      </label>
      <label>
        <span>产能模式</span>
        <select v-model="form.capacity_mode" data-test="node-capacity-mode" class="form-input">
          <option value="exclusive">独占产能</option>
          <option value="batch">批处理产能</option>
          <option value="shared">共享产能</option>
        </select>
      </label>
      <label>
        <span>工作日历</span>
        <select v-model.number="form.calendar_id" data-test="node-calendar" class="form-input" required>
          <option value="">请选择工作日历</option>
          <option v-for="calendar in calendars" :key="calendar.id" :value="calendar.id">
            {{ calendar.calendar_name || calendar.name || `日历 #${calendar.id}` }}
          </option>
        </select>
      </label>
      <label>
        <span>状态</span>
        <select v-model="form.status" data-test="node-status" class="form-input">
          <option value="active">启用</option>
          <option value="maintenance">维护中</option>
          <option value="inactive">停用</option>
        </select>
      </label>
      <label class="node-editor-panel__wide">
        <span>变更原因</span>
        <textarea v-model="form.reason" data-test="node-reason" class="form-input" rows="3" required />
      </label>
      <label class="node-editor-panel__wide">
        <span>幂等键</span>
        <input v-model="form.idempotency_key" data-test="node-idempotency-key" class="form-input" required>
      </label>
      <div class="node-editor-panel__actions">
        <button data-test="node-reset" type="button" class="btn btn-default" @click="onReset">
          新建节点
        </button>
        <button data-test="node-save" type="submit" class="btn btn-primary" :disabled="saving">
          {{ saving ? '正在保存…' : (form.id ? '保存节点修改' : '创建生产节点') }}
        </button>
      </div>
    </form>

    <dl v-else class="node-editor-panel__readonly">
      <div><dt>所属工序</dt><dd>{{ processLabel }}</dd></div>
      <div><dt>节点编码</dt><dd>{{ form.node_code || '-' }}</dd></div>
      <div><dt>节点名称</dt><dd>{{ form.node_name || '-' }}</dd></div>
      <div><dt>产能模式</dt><dd>{{ capacityLabel }}</dd></div>
      <div><dt>工作日历</dt><dd>{{ calendarLabel }}</dd></div>
      <div><dt>状态</dt><dd>{{ statusLabel }}</dd></div>
      <div><dt>变更原因</dt><dd>{{ form.reason || '-' }}</dd></div>
      <div><dt>幂等键</dt><dd>{{ form.idempotency_key || '-' }}</dd></div>
    </dl>
  </section>
</template>

<style scoped>
.node-editor-panel {
  max-width: 980px;
  margin: 0 auto;
}

.node-editor-panel__header {
  margin-bottom: 20px;
}

.node-editor-panel__header h3,
.node-editor-panel__header p {
  margin: 0;
}

.node-editor-panel__header p {
  margin-top: 6px;
  color: var(--text-secondary);
}

.node-editor-panel__form,
.node-editor-panel__readonly {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.node-editor-panel__form label {
  display: grid;
  gap: 7px;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.node-editor-panel__wide,
.node-editor-panel__actions {
  grid-column: 1 / -1;
}

.node-editor-panel__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 4px;
}

.node-editor-panel__readonly {
  margin: 0;
}

.node-editor-panel__readonly div {
  padding: 14px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
}

.node-editor-panel__readonly dt {
  color: var(--text-placeholder);
  font-size: 12px;
}

.node-editor-panel__readonly dd {
  margin: 6px 0 0;
  color: var(--text-primary);
  overflow-wrap: anywhere;
}

@media (max-width: 699px) {
  .node-editor-panel__form,
  .node-editor-panel__readonly {
    grid-template-columns: 1fr;
  }
}
</style>
