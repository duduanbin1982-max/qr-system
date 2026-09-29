<template>
  <div class="inventory-view-tabs" role="tablist" aria-label="库存视图">
    <button :class="{ active: modelValue === 'order' }" role="tab" :aria-selected="modelValue === 'order'" @click="$emit('update:modelValue', 'order')">按订单</button>
    <button :class="{ active: modelValue === 'product' }" role="tab" :aria-selected="modelValue === 'product'" :disabled="!productEnabled" @click="$emit('update:modelValue', 'product')">按产品编码</button>
    <span v-if="!productEnabled" class="inventory-view-hint">产品视图尚未启用</span>
  </div>
</template>

<script setup>
defineProps({ modelValue: { type: String, default: 'order' }, productEnabled: Boolean })
defineEmits(['update:modelValue'])
</script>

<style scoped>
.inventory-view-tabs { display:flex; align-items:center; gap:8px; margin:0 0 14px; }
.inventory-view-tabs button { border:1px solid var(--border-light); background:#fff; border-radius:8px; padding:8px 16px; cursor:pointer; color:var(--text-secondary); }
.inventory-view-tabs button.active { color:var(--primary); border-color:var(--primary); background:var(--primary-light, #eef2ff); font-weight:600; }
.inventory-view-tabs button:disabled { cursor:not-allowed; opacity:.55; }
.inventory-view-hint { color:var(--text-muted); font-size:12px; }
</style>
