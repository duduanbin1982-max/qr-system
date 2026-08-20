// usePositions.js — Positions Composable
import { ref, reactive, computed, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

export function normalizePositionProcessIds(position = {}) {
  let raw = position.process_ids
  if (typeof raw === 'string') {
    try { raw = JSON.parse(raw) }
    catch (_) { raw = raw.split(',') }
  }
  if (!Array.isArray(raw)) {
    raw = (position.processes || []).map(item => item.process_id ?? item.id)
  }
  return [...new Set(raw
    .map(value => Number(value))
    .filter(value => Number.isInteger(value) && value > 0))]
}

export function usePositions({ autoLoad = true } = {}) {
  const positions = ref([])
  const positionLoading = ref(false)
  const showPositionModal = ref(false)
  const positionModalEdit = ref(false)
  const positionForm = reactive({ name:'', description:'', status:'active', process_ids:[] })
  const allProcesses = ref([])
  const canCreate = computed(() => can('positions:create'))
  const canEdit = computed(() => can('positions:edit'))
  const canDelete = computed(() => can('positions:delete'))

  async function loadPositions() {
    positionLoading.value = true
    try { const d = await api.domains.positions.listPositions(); positions.value = d.positions||[] }
    catch(e) { showToast(e.message,'error') }
    finally { positionLoading.value = false }
  }
  async function loadAllProcesses() {
    try { const d = await api.domains.processes.listProcesses({ limit: 500 }); allProcesses.value = d.processes||[] }
    catch(e) { allProcesses.value = [] }
  }
  function openAddPosition() {
    if (!canCreate.value) { showToast('无权新增岗位','error'); return }
    positionModalEdit.value = false
    Object.assign(positionForm, { name:'', description:'', status:'active', process_ids:[], _id:null, _originalStatus:'active' })
    showPositionModal.value = true
  }
  function openEditPosition(pos) {
    if (!canEdit.value) { showToast('无权编辑岗位','error'); return }
    positionModalEdit.value = true
    Object.assign(positionForm, {
      name: pos.name,
      description: pos.description || '',
      status: pos.status || 'active',
      process_ids: normalizePositionProcessIds(pos),
      _id: pos.id,
      _originalStatus: pos.status || 'active',
    })
    showPositionModal.value = true
  }
  async function savePosition() {
    if (positionModalEdit.value ? !canEdit.value : !canCreate.value) {
      showToast('无权保存岗位','error')
      return false
    }
    if (!positionForm.name.trim()) { showToast('岗位名称不能为空','error'); return false }
    if (positionModalEdit.value && positionForm._originalStatus === 'active' && positionForm.status === 'inactive') {
      let impact
      try { impact = await api.domains.positions.getPositionImpact(positionForm._id) }
      catch(e) { showToast(e.message || '检查岗位使用情况失败','error'); return false }
      if ((impact.users || 0) > 0) {
        showToast(impact.users + ' 个员工正在使用此岗位，无法停用','warn')
        return false
      }
    }
    try {
      const body = { name:positionForm.name.trim(), description:positionForm.description, status:positionForm.status, process_ids:[...positionForm.process_ids] }
      if (positionModalEdit.value) await api.domains.positions.updatePosition(positionForm._id, body)
      else await api.domains.positions.createPosition(body)
      showToast(positionModalEdit.value?'更新成功':'创建成功')
      showPositionModal.value = false
      loadPositions()
      return true
    } catch(e) { showToast(e.message,'error'); return false }
  }
  async function deletePosition(pid) {
    if (!canDelete.value) { showToast('无权删除岗位','error'); return false }
    try {
      const res = await api.domains.positions.getPositionImpact(pid)
      if (res.users > 0) {
        showToast(res.users + ' 个员工正在使用此岗位，无法删除', 'warn')
        return false
      }
    } catch(e) {
      showToast(e.message || '检查岗位使用情况失败', 'error')
      return false
    }
    if (!confirm('确定删除该岗位？')) return false
    try { await api.domains.positions.deletePosition(pid); showToast('删除成功'); loadPositions(); return true }
    catch(e) { showToast(e.message,'error'); return false }
  }
  function toggleProcessInPosition(pid) {
    const idx = positionForm.process_ids.indexOf(pid)
    if (idx >= 0) positionForm.process_ids.splice(idx, 1)
    else positionForm.process_ids.push(pid)
  }

  if (autoLoad) onMounted(() => { loadPositions(); loadAllProcesses() })

  return {
    positions, positionLoading, showPositionModal, positionModalEdit, positionForm, allProcesses,
    canCreate, canEdit, canDelete,
    loadPositions, loadAllProcesses, openAddPosition, openEditPosition, savePosition, deletePosition, toggleProcessInPosition,
  }
}
