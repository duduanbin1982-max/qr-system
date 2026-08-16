<template>
  <section class="impact-summary" aria-label="影响摘要">
    <div class="panel-heading">
      <div>
        <h4>影响摘要</h4>
        <span>引用 {{ totalReferences }} 条</span>
      </div>
      <span class="impact-level" :class="totalReferences ? 'has-impact' : 'no-impact'">
        {{ totalReferences ? '需要联动处置' : '无业务引用' }}
      </span>
    </div>
    <div v-if="loading" class="panel-empty">正在读取影响范围...</div>
    <div v-else-if="error" class="panel-error">{{ error }}</div>
    <div v-else-if="!references.length" class="panel-empty">当前没有受影响的业务数据</div>
    <div v-else class="impact-list">
      <div v-for="item in references" :key="item.key" class="impact-row">
        <div class="impact-main">
          <strong>{{ item.label }}</strong>
          <span>{{ item.suggested_action || '发布前复核关联业务' }}</span>
        </div>
        <div class="impact-meta">
          <span class="impact-badge" :class="`level-${item.impact_level || 'review'}`">{{ item.impact_level || 'review' }}</span>
          <strong>{{ item.count }}</strong>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  impact: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const references = computed(() => props.impact?.references || [])
const totalReferences = computed(() => Number(
  props.impact?.total_references
  ?? references.value.reduce((sum, item) => sum + Number(item.count || 0), 0)
))
</script>

<style scoped>
.impact-summary { min-width:0; }
.panel-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; }
.panel-heading h4 { margin:0; font-size:15px; letter-spacing:0; }
.panel-heading span { color:var(--text-placeholder); font-size:12px; }
.impact-level { padding:3px 8px; border-radius:4px; border:1px solid transparent; white-space:nowrap; }
.impact-level.has-impact { color:#925d00; background:#fff7df; border-color:#ebcf83; }
.impact-level.no-impact { color:#23653a; background:#edf8f0; border-color:#aed8b9; }
.panel-empty { padding:22px 12px; color:var(--text-placeholder); text-align:center; border-top:1px solid var(--border-color); }
.panel-error { padding:14px 12px; color:var(--danger-dark); background:var(--danger-light); border-top:1px solid var(--danger); font-size:12px; }
.impact-list { border-top:1px solid var(--border-color); }
.impact-row { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:11px 0; border-bottom:1px solid var(--border-color); }
.impact-main { min-width:0; display:grid; gap:3px; }
.impact-main strong { font-size:14px; }
.impact-main span { color:var(--text-placeholder); font-size:12px; overflow-wrap:anywhere; }
.impact-meta { display:flex; align-items:center; gap:10px; flex:0 0 auto; }
.impact-meta > strong { min-width:30px; text-align:right; font-variant-numeric:tabular-nums; }
.impact-badge { padding:2px 6px; border-radius:4px; background:#eef2f6; color:#4d5a67; font-size:11px; }
.level-blocking, .level-high { background:#fff0ef; color:#a63832; }
.level-review, .level-medium { background:#fff7df; color:#925d00; }
@media (max-width:640px) { .impact-row { align-items:flex-start; } .impact-meta { flex-direction:column; align-items:flex-end; gap:4px; } }
</style>
