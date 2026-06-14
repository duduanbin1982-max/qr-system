<!-- components/common/ToggleSwitch.vue -->
<template>
  <label style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;padding:var(--space-2) 12px;background:var(--bg-table-header);border-radius:var(--radius-md);margin-bottom:var(--space-2)">
    <span style="font-size:var(--text-base)">{{ label }}</span>
    <span @click.prevent="$emit('update:modelValue', modelValue ? 0 : 1)"
      :style="{
        display:'inline-block', width:'44px', height:'24px', borderRadius:'12px',
        background: modelValue ? 'var(--success)' : 'var(--border)',
        position:'relative', transition:'background .2s', cursor:'pointer'
      }">
      <span :style="{
        display:'block', width:'20px', height:'20px', borderRadius:'50%',
        background:'var(--bg-surface)', position:'absolute', top:'2px',
        left: modelValue ? '22px' : '2px',
        transition:'left .2s', boxShadow:'0 1px 3px rgba(0,0,0,.2)'
      }"></span>
    </span>
  </label>
</template>
<script>
export default {
  props: { modelValue: [Boolean, Number], label: String },
  emits: ['update:modelValue']
}
</script>
