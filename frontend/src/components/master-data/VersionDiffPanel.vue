<template>
  <section class="version-diff" aria-label="版本差异">
    <div class="panel-heading">
      <div>
        <h4>版本差异</h4>
        <span v-if="before && after">V{{ before.version }} → V{{ after.version }}</span>
      </div>
      <span class="change-count">{{ changes.length }} 项变化</span>
    </div>
    <div v-if="!before" class="panel-empty">首个版本，无前序版本可比较</div>
    <div v-else-if="!changes.length" class="panel-empty">版本内容未发生变化</div>
    <div v-else class="diff-table-wrap">
      <table class="data-table diff-table">
        <thead><tr><th>字段</th><th>前值</th><th>修订值</th></tr></thead>
        <tbody>
          <tr v-for="change in changes" :key="change.key">
            <td class="diff-field">{{ change.label }}</td>
            <td class="diff-before">{{ change.before }}</td>
            <td class="diff-after">{{ change.after }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  before: { type: Object, default: null },
  after: { type: Object, default: null },
})

const fields = [
  { key: 'name', label: '工序名称' },
  { key: 'category', label: '分类' },
  { key: 'description', label: '描述' },
  { key: 'seq_order', label: '排序序号' },
]

function display(value) {
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

const changes = computed(() => {
  if (!props.before || !props.after) return []
  return fields
    .filter((field) => display(props.before[field.key]) !== display(props.after[field.key]))
    .map((field) => ({
      ...field,
      before: display(props.before[field.key]),
      after: display(props.after[field.key]),
    }))
})
</script>

<style scoped>
.version-diff { min-width: 0; }
.panel-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; }
.panel-heading h4 { margin:0; font-size:15px; letter-spacing:0; }
.panel-heading span { color:var(--text-placeholder); font-size:12px; }
.change-count { padding:3px 8px; border:1px solid var(--border-color); border-radius:4px; white-space:nowrap; }
.panel-empty { padding:22px 12px; color:var(--text-placeholder); text-align:center; border-top:1px solid var(--border-color); }
.diff-table-wrap { overflow:auto; border-top:1px solid var(--border-color); }
.diff-table { min-width:520px; }
.diff-field { width:110px; font-weight:600; }
.diff-before { color:var(--text-placeholder); }
.diff-after { color:var(--text-primary); font-weight:600; }
</style>
