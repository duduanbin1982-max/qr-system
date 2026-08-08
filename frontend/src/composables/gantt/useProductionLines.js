import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


export function useProductionLines({ canManageLines }) {
  const productionLines = ref([])
  const showLineMgr = ref(false)
  const lineForm = ref({ name: '', remark: '', capacity_per_day: 10 })

  async function loadLines() {
    try {
      const data = await api.domains.production.listProductionLines()
      productionLines.value = data.lines || data || []
    } catch (error) {
      console.warn('Production lines load failed:', error)
      productionLines.value = []
    }
  }

  async function addLine() {
    if (!canManageLines.value) return
    if (!lineForm.value.name.trim()) {
      showToast('产线名称必填', 'error')
      return
    }
    try {
      await api.domains.production.createProductionLine(lineForm.value)
      showToast('产线已添加')
      lineForm.value = { name: '', remark: '', capacity_per_day: 10 }
      await loadLines()
    } catch (error) {
      showToast(error.message || '添加失败', 'error')
    }
  }

  async function delLine(line) {
    if (!canManageLines.value) return
    if (!confirm(`确定删除产线「${line.name}」？`)) return
    try {
      await api.domains.production.deleteProductionLine(line.id)
      showToast('已删除')
      await loadLines()
    } catch (error) {
      showToast(error.message || '删除失败', 'error')
    }
  }

  return {
    productionLines,
    showLineMgr,
    lineForm,
    loadLines,
    addLine,
    delLine,
  }
}
