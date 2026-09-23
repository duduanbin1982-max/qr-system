<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  order: { type: Object, default: null },
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'save'])
const drawerRef = ref(null)
const previousFocus = ref(null)
const form = ref({ priority_level: 3, is_expedited: false, schedule_change_reason: '' })

watch(() => props.open, (open, wasOpen) => {
  if (open && !wasOpen) {
    form.value = {
      priority_level: Number(props.order?.priority_level || props.order?.priority || 3),
      is_expedited: Boolean(props.order?.is_expedited),
      schedule_change_reason: '',
    }
    previousFocus.value = document.activeElement
    document.body.style.overflow = 'hidden'
    nextTick(() => drawerRef.value?.querySelector('select, input, button')?.focus())
  }
  if (!open && wasOpen) {
    document.body.style.overflow = ''
    previousFocus.value?.focus?.()
    previousFocus.value = null
  }
}, { immediate: true })

function onKeydown(event) {
  if (!props.open) return
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
    return
  }
  if (event.key !== 'Tab' || !drawerRef.value) return
  const focusable = [...drawerRef.value.querySelectorAll('button, select, input, textarea')]
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

function save() {
  const reason = String(form.value.schedule_change_reason || '').trim()
  if (!reason) return
  emit('save', { ...form.value, schedule_change_reason: reason })
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="schedule-priority-drawer__overlay" @click.self="emit('close')">
      <aside ref="drawerRef" class="schedule-priority-drawer" role="dialog" aria-modal="true" aria-labelledby="schedule-priority-title">
        <header>
          <div><div class="eyebrow">订单排程优先级</div><h2 id="schedule-priority-title">调整 {{ order?.order_no || '订单' }}</h2></div>
          <button type="button" class="btn-default" aria-label="关闭优先级调整" @click="emit('close')">×</button>
        </header>
        <form class="schedule-priority-drawer__body" @submit.prevent="save">
          <label>优先级
            <select v-model.number="form.priority_level" class="form-input" required>
              <option :value="1">P1 · 最高</option><option :value="2">P2 · 高</option><option :value="3">P3 · 普通</option><option :value="4">P4 · 较低</option><option :value="5">P5 · 最低</option>
            </select>
          </label>
          <label class="schedule-priority-drawer__check"><input v-model="form.is_expedited" type="checkbox"> 标记为加急订单</label>
          <label>调整原因
            <textarea v-model="form.schedule_change_reason" class="form-input" rows="4" maxlength="512" required placeholder="请说明为什么调整优先级或加急状态"></textarea>
          </label>
          <div class="schedule-priority-drawer__notice">保存后会增加优先级版本、保留历史记录，并将订单标记为待重新排程。</div>
          <footer><button type="button" class="btn-default" @click="emit('close')">取消</button><button type="submit" class="btn btn-primary" :disabled="saving || !String(form.schedule_change_reason || '').trim()">{{ saving ? '保存中…' : '保存调整' }}</button></footer>
        </form>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.schedule-priority-drawer__overlay { position:fixed; inset:0; z-index:3250; background:rgb(15 23 42 / 45%); }
.schedule-priority-drawer { position:absolute; top:0; right:0; width:min(520px,94vw); height:100%; display:flex; flex-direction:column; background:var(--bg-surface); box-shadow:-16px 0 48px rgb(15 23 42 / 22%); }
.schedule-priority-drawer header { display:flex; justify-content:space-between; gap:12px; padding:20px 22px 16px; border-bottom:1px solid var(--border-light); }
.schedule-priority-drawer h2 { margin:4px 0 0; font-size:var(--text-xl); }
.eyebrow { color:var(--primary); font-size:var(--text-xs); font-weight:700; }
.schedule-priority-drawer__body { display:flex; flex-direction:column; gap:14px; flex:1; padding:20px 22px; overflow:auto; }
.schedule-priority-drawer label { display:flex; flex-direction:column; gap:6px; color:var(--text-secondary); font-size:var(--text-sm); }
.schedule-priority-drawer__check { flex-direction:row !important; align-items:center; cursor:pointer; }
.schedule-priority-drawer__notice { padding:10px 12px; border-left:3px solid var(--primary); background:var(--primary-light); color:var(--text-secondary); font-size:var(--text-xs); }
.schedule-priority-drawer footer { display:flex; justify-content:flex-end; gap:8px; margin-top:auto; padding-top:12px; }
@media (max-width:700px) { .schedule-priority-drawer { width:100%; } .schedule-priority-drawer header,.schedule-priority-drawer__body { padding-left:14px; padding-right:14px; } }
</style>
