<template>
  <section class="card exception-panel">
    <div class="card-header"><div><h3>数据异常</h3><p>异常保留来源快照，需在来源系统或人工确认流程中处理。</p></div><span class="exception-count">{{ total }} 条</span></div>
    <div class="card-body table-wrap">
      <table v-if="items.length" class="data-table exception-table"><thead><tr><th>异常类型</th><th>员工 / 来源</th><th>说明</th><th>来源快照</th><th>状态</th><th>创建时间</th></tr></thead><tbody><tr v-for="item in items" :key="item.id"><td><strong>{{ typeLabel(item.exception_type) }}</strong><small>#{{ item.id }}</small></td><td>{{ item.employee_name_snapshot || item.snapshot?.employee_name || '-' }}<small>{{ item.source_type || item.snapshot?.source_type || '-' }}</small></td><td>{{ item.message || item.reason || item.description || '-' }}</td><td><code>{{ snapshotText(item.snapshot) }}</code></td><td><span class="exception-status">{{ statusLabel(item.status) }}</span></td><td>{{ item.created_at || '-' }}</td></tr></tbody></table>
      <p v-else class="empty">当前批次没有数据异常。</p>
    </div>
  </section>
</template>

<script>
export default {
  props: { items: { type: Array, default: () => [] }, total: { type: Number, default: 0 } },
  methods: {
    typeLabel(type) { return { missing_position: '缺少岗位', missing_position_target: '缺少岗位目标', position_target_mismatch: '岗位目标不匹配', ambiguous_quality_source: '质量来源歧义', unresolved_quality_source: '质量来源未确认', source_mapping_missing: '来源映射缺失' }[type] || type || '数据异常' },
    statusLabel(status) { return { pending: '待确认', resolved: '已解决', confirmed_insufficient: '确认数据不足', excluded: '已排除' }[status] || status || '-' },
    snapshotText(snapshot) { if (!snapshot || typeof snapshot !== 'object') return '-'; const text = Object.entries(snapshot).slice(0, 4).map(([key, value]) => `${key}=${value ?? ''}`).join('；'); return text || '-' },
  },
}
</script>

<style scoped>
.exception-panel{margin:0}.exception-panel h3{margin:0}.exception-panel p{margin:4px 0 0;color:var(--text-placeholder);font-size:var(--text-xs-alt)}.exception-count{font-weight:700;color:var(--warning)}.exception-table{min-width:1000px}.exception-table strong,.exception-table small{display:block}.exception-table small{color:var(--text-placeholder);margin-top:3px}.exception-table code{display:block;max-width:320px;white-space:normal;word-break:break-word;color:var(--text-secondary)}.exception-status{white-space:nowrap;padding:3px 6px;border-radius:4px;background:var(--warning-light);color:var(--warning)}
</style>
