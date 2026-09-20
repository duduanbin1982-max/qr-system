<script setup>
defineProps({
  groups: { type: Array, default: () => [] },
  selectedNodeId: { type: [Number, String], default: null },
  search: { type: String, default: '' },
  statusFilter: { type: String, default: '' },
  loading: Boolean,
  error: { type: String, default: '' },
  canCreate: { type: Boolean, default: true },
})

defineEmits([
  'update:search',
  'update:statusFilter',
  'select',
  'retry',
  'create',
])

function statusLabel(status) {
  return status === 'active' ? '启用' : '停用'
}
</script>

<template>
  <aside class="node-list-panel" aria-label="生产节点列表">
    <div class="node-list-panel__toolbar">
      <label>
        <span class="sr-only">搜索生产节点</span>
        <input
          data-test="node-search"
          class="form-input"
          type="search"
          placeholder="搜索编码、名称或工序"
          :value="search"
          @input="$emit('update:search', $event.target.value)"
        >
      </label>
      <label>
        <span class="sr-only">按状态筛选生产节点</span>
        <select
          data-test="node-status-filter"
          class="form-input"
          :value="statusFilter"
          @change="$emit('update:statusFilter', $event.target.value)"
        >
          <option value="">全部状态</option>
          <option value="active">启用</option>
          <option value="inactive">停用</option>
        </select>
      </label>
      <button
        v-if="canCreate"
        data-test="node-create"
        type="button"
        class="btn btn-primary"
        @click="$emit('create')"
      >
        新建节点
      </button>
    </div>

    <div class="node-list-panel__scroll">
      <div v-if="loading" class="node-list-panel__state" role="status">正在加载生产节点…</div>
      <div v-else-if="error" class="node-list-panel__state node-list-panel__state--error" role="alert">
        <p>{{ error }}</p>
        <button data-test="node-retry" type="button" class="btn btn-default" @click="$emit('retry')">重试</button>
      </div>
      <div v-else-if="!groups.length" class="node-list-panel__state">没有符合条件的生产节点</div>
      <section v-for="group in groups" v-else :key="group.process_id" class="node-list-panel__group">
        <h3>
          <span>{{ group.process_name }}</span>
          <small>{{ group.nodes.length }}</small>
        </h3>
        <button
          v-for="node in group.nodes"
          :key="node.id"
          type="button"
          class="node-list-panel__item"
          :class="{ 'node-list-panel__item--selected': String(selectedNodeId) === String(node.id) }"
          :data-test="`node-item-${node.id}`"
          :aria-current="String(selectedNodeId) === String(node.id) ? 'true' : undefined"
          @click="$emit('select', node)"
        >
          <span class="node-list-panel__item-heading">
            <code>{{ node.node_code }}</code>
            <span class="node-list-panel__status" :class="`node-list-panel__status--${node.status}`">
              {{ statusLabel(node.status) }}
            </span>
          </span>
          <strong>{{ node.node_name }}</strong>
          <small>{{ node.capacity_mode === 'shared' ? '共享产能' : '独占产能' }}</small>
        </button>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.node-list-panel {
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  border-right: 1px solid var(--border-light);
  background: var(--bg-secondary);
}

.node-list-panel__toolbar {
  display: grid;
  gap: 8px;
  padding: 14px;
  border-bottom: 1px solid var(--border-light);
}

.node-list-panel__toolbar label,
.node-list-panel__toolbar .form-input {
  width: 100%;
}

.node-list-panel__scroll {
  min-height: 0;
  overflow: auto;
  padding: 10px;
}

.node-list-panel__state {
  padding: 32px 12px;
  color: var(--text-placeholder);
  text-align: center;
}

.node-list-panel__state p {
  margin: 0 0 12px;
}

.node-list-panel__state--error {
  color: var(--danger);
}

.node-list-panel__group + .node-list-panel__group {
  margin-top: 14px;
}

.node-list-panel__group h3 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0;
  padding: 6px 8px;
  color: var(--text-secondary);
  font-size: 13px;
}

.node-list-panel__group h3 small {
  color: var(--text-placeholder);
  font-weight: 400;
}

.node-list-panel__item {
  width: 100%;
  display: grid;
  gap: 5px;
  margin-top: 6px;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
}

.node-list-panel__item:hover,
.node-list-panel__item--selected {
  border-color: var(--primary);
  box-shadow: var(--shadow-sm);
}

.node-list-panel__item--selected {
  background: var(--primary-light);
}

.node-list-panel__item-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.node-list-panel__item code {
  color: var(--primary);
  font-size: 12px;
}

.node-list-panel__item strong {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-list-panel__item > small {
  color: var(--text-placeholder);
}

.node-list-panel__status {
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 11px;
}

.node-list-panel__status--active {
  background: #e8f6ec;
  color: #23723b;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
