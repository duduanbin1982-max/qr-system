<template>
  <section class="route-version-editor" aria-label="路线版本内容">
    <div class="route-fields">
      <label>路线名称
        <input v-model="draft.name" class="form-input" :disabled="readonly">
      </label>
      <label>分类
        <select v-model="draft.category" class="form-input" :disabled="readonly">
          <option value="结构件">结构件</option>
          <option value="机加工">机加工</option>
        </select>
      </label>
      <label class="full-field">描述
        <textarea v-model="draft.description" class="form-input" rows="2" :disabled="readonly"></textarea>
      </label>
    </div>

    <div class="node-heading">
      <div><h4>路线节点</h4><span>绑定精确工序版本和审批要求</span></div>
      <button v-if="!readonly" type="button" class="btn btn-default btn-sm" @click="addNode">添加节点</button>
    </div>

    <div v-if="!draft.items?.length" class="node-empty">尚未添加路线节点</div>
    <div v-else class="node-table-wrap">
      <table class="data-table node-table">
        <thead><tr><th>#</th><th>工序版本</th><th>必须</th><th>需审批</th><th v-if="!readonly">排序</th></tr></thead>
        <tbody>
          <tr v-for="(node, index) in draft.items" :key="node.id || `node-${index}`">
            <td class="node-index">{{ index + 1 }}</td>
            <td>
              <select
                v-if="!readonly"
                :value="node.process_version_id"
                class="form-input node-select"
                :disabled="readonly"
                @change="selectProcess(index, $event.target.value)"
              >
                <option value="">请选择同分类已发布工序</option>
                <option v-for="process in filteredProcessOptions" :key="process.process_version_id" :value="process.process_version_id">
                  {{ optionLabel(process) }}
                </option>
              </select>
              <div v-else class="node-identity">
                <strong>{{ node.process_name_snapshot || processName(node) }}</strong>
                <span>{{ node.process_code_snapshot || processCode(node) }} · V{{ node.process_version || processVersion(node) }}</span>
              </div>
            </td>
            <td><input v-model="node.is_required" type="checkbox" :true-value="1" :false-value="0" :disabled="readonly" aria-label="必须节点"></td>
            <td><input v-model="node.required_audit" type="checkbox" :true-value="1" :false-value="0" :disabled="readonly" aria-label="需要审批"></td>
            <td v-if="!readonly">
              <div class="node-actions">
                <button type="button" class="icon-action" title="上移" :disabled="index === 0" @click="moveNode(index, -1)">↑</button>
                <button type="button" class="icon-action" title="下移" :disabled="index === draft.items.length - 1" @click="moveNode(index, 1)">↓</button>
                <button type="button" class="icon-action danger" title="移除" @click="removeNode(index)">×</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Object, required: true },
  readonly: { type: Boolean, default: false },
  processOptions: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue'])

function clone(value) {
  return JSON.parse(JSON.stringify(value || { name: '', category: '结构件', description: '', items: [] }))
}

function serialized(value) {
  return JSON.stringify(value || {})
}

const draft = ref(clone(props.modelValue))

watch(() => props.modelValue, value => {
  if (serialized(value) !== serialized(draft.value)) draft.value = clone(value)
}, { deep: true })

watch(draft, value => {
  if (serialized(value) !== serialized(props.modelValue)) emit('update:modelValue', clone(value))
}, { deep: true })

const filteredProcessOptions = computed(() => props.processOptions.filter(process => (
  process.category === draft.value.category
  && (process.version_status || process.process_version_status) === 'published'
  && Number(process.process_version_id) > 0
)))

function optionLabel(process) {
  return `${process.process_code || ''} ${process.process_name || process.name || ''} · V${process.process_version || process.version || '-'}`.trim()
}

function processOption(node) {
  return props.processOptions.find(process => Number(process.process_version_id) === Number(node.process_version_id))
}

function processName(node) {
  const process = processOption(node)
  return process?.process_name || process?.name || `工序 ${node.process_id}`
}

function processCode(node) {
  return processOption(node)?.process_code || `PROC-${node.process_id}`
}

function processVersion(node) {
  return processOption(node)?.process_version || '-'
}

function resequence() {
  draft.value.items.forEach((node, index) => { node.seq_order = (index + 1) * 10 })
}

function addNode() {
  draft.value.items ||= []
  draft.value.items.push({
    process_id: null,
    process_version_id: null,
    seq_order: (draft.value.items.length + 1) * 10,
    is_required: 1,
    required_audit: 0,
  })
}

function selectProcess(index, processVersionId) {
  const process = props.processOptions.find(item => Number(item.process_version_id) === Number(processVersionId))
  if (!process) return
  draft.value.items[index] = {
    ...draft.value.items[index],
    process_id: Number(process.id || process.process_id),
    process_version_id: Number(process.process_version_id),
    process_code_snapshot: process.process_code || '',
    process_name_snapshot: process.process_name || process.name || '',
    process_category: process.category,
    process_version: Number(process.process_version || process.version),
    process_version_status: process.version_status || process.process_version_status,
  }
}

function moveNode(index, offset) {
  const target = index + offset
  if (target < 0 || target >= draft.value.items.length) return
  const [node] = draft.value.items.splice(index, 1)
  draft.value.items.splice(target, 0, node)
  resequence()
}

function removeNode(index) {
  draft.value.items.splice(index, 1)
  resequence()
}
</script>

<style scoped>
.route-version-editor { min-width:0; }
.route-fields { display:grid; grid-template-columns:minmax(0, 2fr) minmax(160px, 1fr); gap:14px; }
.route-fields label { display:grid; gap:6px; color:var(--text-secondary); font-size:13px; }
.full-field { grid-column:1 / -1; }
.node-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:20px 0 10px; }
.node-heading h4 { margin:0; font-size:15px; letter-spacing:0; }
.node-heading span { color:var(--text-placeholder); font-size:12px; }
.node-empty { padding:26px; border:1px dashed var(--border-color); color:var(--text-placeholder); text-align:center; }
.node-table-wrap { overflow:auto; border:1px solid var(--border-color); border-radius:6px; }
.node-table { min-width:620px; }
.node-table th:nth-child(1), .node-index { width:44px; text-align:center; }
.node-table th:nth-child(3), .node-table th:nth-child(4) { width:72px; text-align:center; }
.node-table td:nth-child(3), .node-table td:nth-child(4) { text-align:center; }
.node-select { min-width:280px; }
.node-identity { display:grid; gap:3px; }
.node-identity span { color:var(--text-placeholder); font-size:12px; }
.node-actions { display:flex; gap:4px; justify-content:flex-end; }
.icon-action { width:30px; height:30px; border:1px solid var(--border-color); border-radius:4px; background:#fff; cursor:pointer; }
.icon-action:disabled { opacity:.4; cursor:not-allowed; }
.icon-action.danger { color:var(--danger); }
@media (max-width:720px) { .route-fields { grid-template-columns:1fr; } .full-field { grid-column:auto; } }
</style>
