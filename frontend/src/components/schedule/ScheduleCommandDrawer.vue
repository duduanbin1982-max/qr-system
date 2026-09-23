<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
const props = defineProps({
  open: { type: Boolean, default: false },
  mode: { type: String, default: 'edit' },
  form: { type: Object, required: true },
  nodes: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'save'])
const drawerRef = ref(null)
const previousFocus = ref(null)

const title = props.mode === 'adjust' ? '调整生产节点排程' : '编辑订单排程'

function onKeydown(event) {
  if (!props.open) return
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
    return
  }
  if (event.key !== 'Tab' || !drawerRef.value) return
  const focusable = [...drawerRef.value.querySelectorAll('button, input, select, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter(node => !node.disabled && node.offsetParent !== null)
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function onOpen() {
  previousFocus.value = document.activeElement
  document.body.style.overflow = 'hidden'
  nextTick(() => drawerRef.value?.querySelector('input, select, button')?.focus())
}

function onClose() {
  document.body.style.overflow = ''
  previousFocus.value?.focus?.()
  previousFocus.value = null
}

onMounted(() => document.addEventListener('keydown', onKeydown))
watch(() => props.open, (open, wasOpen) => {
  if (open && !wasOpen) onOpen()
  if (!open && wasOpen) onClose()
}, { immediate: true })
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="schedule-command-drawer__overlay" @click.self="emit('close')">
      <aside ref="drawerRef" class="schedule-command-drawer" role="dialog" aria-modal="true" :aria-label="title">
        <header><div><div class="eyebrow">生产排程操作</div><h2>{{ title }}</h2></div><button type="button" class="btn-default" aria-label="关闭" @click="emit('close')">×</button></header>
        <form class="schedule-command-drawer__body" @submit.prevent="emit('save')">
          <template v-if="mode === 'adjust'">
            <label>生产节点<select v-model="form.production_node_id" class="form-input" required><option value="">选择生产节点</option><option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.process_name }} · {{ node.node_code }} · {{ node.node_name }}</option></select></label>
            <label>计划开始时间<input v-model="form.planned_start_at" type="datetime-local" class="form-input" required></label>
            <label>调整原因<input v-model="form.reason" class="form-input" required maxlength="512"></label>
            <label>幂等键<input v-model="form.idempotency_key" class="form-input" required maxlength="128"></label>
          </template>
          <template v-else>
            <label>开始日期<input v-model="form.plan_start" type="date" class="form-input" required></label>
            <label>结束日期<input v-model="form.plan_end" type="date" class="form-input" required></label>
          </template>
          <div class="schedule-command-drawer__notice">保存后会生成新的排程修订记录；正式结果必须经过审批和发布。</div>
          <footer><button type="button" class="btn-default" @click="emit('close')">取消</button><button type="submit" class="btn btn-primary" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button></footer>
        </form>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.schedule-command-drawer__overlay { position:fixed; inset:0; z-index:3150; background:rgb(15 23 42 / 42%); }
.schedule-command-drawer { position:absolute; top:0; right:0; width:min(520px,94vw); height:100%; display:flex; flex-direction:column; background:var(--bg-surface); box-shadow:-16px 0 48px rgb(15 23 42 / 22%); }
.schedule-command-drawer header { display:flex; justify-content:space-between; gap:12px; padding:20px 22px 16px; border-bottom:1px solid var(--border-light); }
.schedule-command-drawer h2 { margin:4px 0 0; font-size:var(--text-xl); }
.eyebrow { color:var(--primary); font-size:var(--text-xs); font-weight:700; }
.schedule-command-drawer__body { display:flex; flex-direction:column; gap:14px; flex:1; padding:20px 22px; overflow:auto; }
.schedule-command-drawer label { display:flex; flex-direction:column; gap:6px; color:var(--text-secondary); font-size:var(--text-sm); }
.schedule-command-drawer__notice { padding:10px 12px; border-left:3px solid var(--primary); background:var(--primary-light); color:var(--text-secondary); font-size:var(--text-xs); }
.schedule-command-drawer__body footer { display:flex; justify-content:flex-end; gap:8px; margin-top:auto; padding-top:12px; }
@media (max-width:700px) { .schedule-command-drawer { width:100%; } .schedule-command-drawer header,.schedule-command-drawer__body { padding-left:14px; padding-right:14px; } }
</style>
