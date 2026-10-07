<template>
  <details class="inventory-column-configurator">
    <summary aria-label="列显示配置">列显示 <span class="inventory-column-count">{{ visibleKeys.length }}/{{ columns.length }}</span></summary>
    <div class="inventory-column-menu">
      <div class="inventory-column-menu-title">选择显示列</div>
      <label v-for="column in columns" :key="column.key" class="inventory-column-option">
        <input
          type="checkbox"
          :checked="visibleKeys.includes(column.key)"
          :disabled="column.required"
          @change="toggle(column.key)"
        >
        <span>{{ column.label }}</span>
        <small v-if="column.required">必选</small>
      </label>
      <button class="btn btn-link btn-sm inventory-column-reset" type="button" @click="reset">恢复默认</button>
    </div>
  </details>
</template>

<script setup>
const props = defineProps({
  columns: { type: Array, default: () => [] },
  visibleKeys: { type: Array, default: () => [] },
})
const emit = defineEmits(['update', 'reset'])

function toggle(key) {
  const column = props.columns.find(item => item.key === key)
  if (column?.required) return
  const next = props.visibleKeys.includes(key)
    ? props.visibleKeys.filter(item => item !== key)
    : [...props.visibleKeys, key]
  emit('update', next)
}

function reset() { emit('reset') }
</script>

<style scoped>
.inventory-column-configurator { position:relative; min-width:118px; }
.inventory-column-configurator summary { list-style:none; cursor:pointer; min-height:34px; display:flex; align-items:center; justify-content:space-between; gap:8px; padding:7px 10px; border:1px solid var(--border-light); border-radius:var(--radius-md); background:var(--bg-surface); color:var(--text-secondary); font-size:13px; }
.inventory-column-configurator summary::-webkit-details-marker { display:none; }
.inventory-column-count { color:var(--primary); font-size:11px; font-weight:700; }
.inventory-column-menu { position:absolute; right:0; top:calc(100% + 5px); z-index:40; width:220px; padding:10px; border:1px solid var(--border-light); border-radius:var(--radius-md); background:var(--bg-surface); box-shadow:0 8px 24px rgba(15,23,42,.14); }
.inventory-column-menu-title { padding:2px 6px 8px; color:var(--text-primary); font-size:12px; font-weight:700; }
.inventory-column-option { display:flex; align-items:center; gap:8px; padding:7px 6px; border-radius:5px; color:var(--text-secondary); font-size:13px; cursor:pointer; }
.inventory-column-option:hover { background:var(--bg-hover); }.inventory-column-option small { margin-left:auto; color:var(--text-muted); font-size:11px; }
.inventory-column-reset { margin-top:6px; padding-left:6px; }
</style>
