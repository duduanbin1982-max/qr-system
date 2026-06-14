// usePositions.js — Positions Composable
import { ref, reactive, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function usePositions() {
  const positions = ref([])
  const positionLoading = ref(false)
  const showPositionModal = ref(false)
  const positionModalEdit = ref(false)
  const positionForm = reactive({ name:'', description:'', status:'active', process_ids:[] })
  const allProcesses = ref([])

  async function loadPositions() {
    positionLoading.value = true
    try { const d = await api.get('/api/positions'); positions.value = d.positions||[] }
    catch(e) { showToast(e.message,'error') }
    finally { positionLoading.value = false }
  }
  async function loadAllProcesses() {
    try { const d = await api.get('/api/processes?limit=500'); allProcesses.value = d.processes||[] }
    catch(e) { allProcesses.value = [] }
  }
  function openAddPosition() {
    positionModalEdit.value = false
    Object.assign(positionForm, { name:'', description:'', status:'active', process_ids:[] })
    showPositionModal.value = true
  }
  function openEditPosition(pos) {
    positionModalEdit.value = true
    Object.assign(positionForm, { name:pos.name, description:pos.description||'', status:pos.status||'active', process_ids:pos.process_ids ? (Array.isArray(pos.process_ids) ? pos.process_ids : JSON.parse(pos.process_ids||'[]')) : [] })
    positionForm._id = pos.id
    showPositionModal.value = true
  }
  async function savePosition() {
    if (!positionForm.name) { showToast('岗位名称不能为空','error'); return }
    try {
      const body = { name:positionForm.name, description:positionForm.description, status:positionForm.status, process_ids:positionForm.process_ids }
      if (positionModalEdit.value) await api.updatePosition(positionForm._id, body)
      else await api.createPosition(body)
      showToast(positionModalEdit.value?'更新成功':'创建成功')
      showPositionModal.value = false
      loadPositions()
    } catch(e) { showToast(e.message,'error') }
  }
  async function deletePosition(pid) {
    let impactMsg = ''
    try {
      const res = await api.get('/api/positions/' + pid + '/impact')
      if (res.users > 0) {
        impactMsg = '\n\n' + res.users + ' 个员工正在使用此岗位，无法删除'
        showToast(impactMsg.trim(), 'warn')
        return
      }
    } catch(e) {}
    if (!confirm('确定删除该岗位？')) return
    try { await api.deletePosition(pid); showToast('删除成功'); loadPositions() }
    catch(e) { showToast(e.message,'error') }
  }
  function toggleProcessInPosition(pid) {
    const idx = positionForm.process_ids.indexOf(pid)
    if (idx >= 0) positionForm.process_ids.splice(idx, 1)
    else positionForm.process_ids.push(pid)
  }

  onMounted(() => { loadPositions(); loadAllProcesses() })

  return {
    positions, positionLoading, showPositionModal, positionModalEdit, positionForm, allProcesses,
    loadPositions, loadAllProcesses, openAddPosition, openEditPosition, savePosition, deletePosition, toggleProcessInPosition,
  }
}
