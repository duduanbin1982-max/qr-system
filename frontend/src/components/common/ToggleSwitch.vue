<template>
  <label class="toggle-row" :class="{ disabled }">
    <span>{{ label }}</span>
    <button
      type="button"
      class="toggle-control"
      :class="{ on: Boolean(modelValue), disabled }"
      role="switch"
      :aria-checked="Boolean(modelValue)"
      :aria-label="label"
      :disabled="disabled"
      @click="$emit('update:modelValue', modelValue ? 0 : 1)"
    >
      <span class="toggle-thumb"></span>
    </button>
  </label>
</template>

<script>
export default {
  props: {
    modelValue: [Boolean, Number],
    label: String,
    disabled: Boolean,
  },
  emits: ['update:modelValue'],
}
</script>

<style scoped>
.toggle-row {
  align-items: center;
  background: var(--bg-table-header);
  border-radius: var(--radius-md);
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  margin-bottom: var(--space-2);
  padding: var(--space-2) 12px;
}
.toggle-row.disabled { cursor: default; opacity: .65; }
.toggle-control {
  background: var(--border);
  border: 0;
  border-radius: 12px;
  cursor: pointer;
  display: inline-block;
  height: 24px;
  padding: 0;
  position: relative;
  transition: background .2s;
  width: 44px;
}
.toggle-control.on { background: var(--success); }
.toggle-control.disabled { cursor: default; }
.toggle-thumb {
  background: var(--bg-surface);
  border-radius: 50%;
  box-shadow: 0 1px 3px rgba(0,0,0,.2);
  display: block;
  height: 20px;
  left: 2px;
  position: absolute;
  top: 2px;
  transition: left .2s;
  width: 20px;
}
.toggle-control.on .toggle-thumb { left: 22px; }
</style>
