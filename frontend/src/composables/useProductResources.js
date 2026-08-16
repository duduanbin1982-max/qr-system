import { ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { positiveBomQuantity } from './productForm.js'


export function useProductAttachments(currentProductId) {
  const productAttachments = ref([])

  async function loadProductAttachments(productId) {
    if (!productId) { productAttachments.value = []; return }
    try {
      const data = await api.domains.products.listProductAttachments(productId)
      productAttachments.value = data.attachments || []
    } catch (_) {
      productAttachments.value = []
    }
  }
  function clearProductAttachments() { productAttachments.value = [] }
  function getAttachmentIcon(fileType) {
    const type = String(fileType || '').toLowerCase()
    if (type.includes('image')) return '🖼️'
    if (type.includes('pdf')) return '📕'
    if (type.includes('cad') || type.includes('dwg') || type.includes('dxf')) return '📐'
    if (type.includes('word') || type.includes('doc')) return '📝'
    if (type.includes('excel') || type.includes('sheet')) return '📊'
    return '📄'
  }
  function formatFileSize(bytes) {
    if (!bytes) return '0 B'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }
  const getThumbnailUrl = attId => `/api/product-attachments/${attId}/thumbnail`
  const openThumbnail = attId => window.open(`/api/product-attachments/${attId}/download`, '_blank')
  const openAttachment = att => window.open(`/api/product-attachments/${att.id}/download`, '_blank')
  function triggerAttachmentInput() {
    document.getElementById('product-attachment-input')?.click()
  }
  async function handleAttachmentUpload(event) {
    const files = [...(event.target.files || [])]
    if (!files.length) return
    if (!currentProductId.value) { showToast('请先保存产品', 'warning'); return }
    for (const file of files) {
      if (file.size > 10 * 1024 * 1024) {
        showToast(`${file.name} 超过10MB限制`, 'error')
        continue
      }
      const formData = new FormData()
      formData.append('file', file)
      try {
        await api.domains.products.uploadProductAttachment(currentProductId.value, formData)
      } catch (error) {
        showToast(error.message || '上传失败', 'error')
      }
    }
    event.target.value = ''
    await loadProductAttachments(currentProductId.value)
  }
  async function deleteProductAttachment(attId) {
    if (!confirm('确定删除此附件？')) return
    try {
      await api.domains.products.deleteProductAttachment(attId)
      showToast('删除成功')
      await loadProductAttachments(currentProductId.value)
    } catch (error) {
      showToast(error.message || '删除失败', 'error')
    }
  }
  return {
    productAttachments, loadProductAttachments, clearProductAttachments,
    getAttachmentIcon, formatFileSize, getThumbnailUrl, openThumbnail, openAttachment,
    triggerAttachmentInput, handleAttachmentUpload, deleteProductAttachment,
  }
}


export function useProductImport(reload) {
  const importFile = ref(null)
  const importLoading = ref(false)
  function triggerImport() { importFile.value?.click() }
  async function handleImport(event) {
    const file = event.target.files?.[0]
    if (!file) return
    if (file.size > 10 * 1024 * 1024) {
      showToast('文件大小超过10MB限制', 'error')
      event.target.value = ''
      return
    }
    const formData = new FormData()
    formData.append('file', file)
    importLoading.value = true
    showToast(`正在导入 ${file.name} ...`)
    try {
      const data = await api.domains.products.uploadProductImport(formData)
      const parts = [data.message || '导入完成']
      if (data.error_summary) parts.push(data.error_summary)
      if (data.columns_found?.length) parts.push(`识别列: ${data.columns_found.join(',')}`)
      showToast(parts.join(' | '))
      await reload()
    } catch (error) {
      showToast(error.message || '导入失败', 'error')
    } finally {
      importLoading.value = false
      event.target.value = ''
    }
  }
  return { importFile, importLoading, triggerImport, handleImport }
}


export function useProductTrash(reload) {
  const showTrash = ref(false)
  const trashedProducts = ref([])
  async function loadTrash() {
    try {
      const data = await api.domains.products.listProducts({ deleted: 1, page: 1, limit: 500 })
      trashedProducts.value = data.products || []
    } catch (error) {
      showToast(error.message || '加载失败', 'error')
    }
  }
  function toggleTrash() {
    showTrash.value = !showTrash.value
    if (showTrash.value) loadTrash()
  }
  async function restore(pid) {
    try {
      await api.domains.products.restoreProduct(pid)
      showToast('恢复成功')
      await Promise.all([loadTrash(), reload()])
    } catch (error) {
      showToast(error.message || '恢复失败', 'error')
    }
  }
  async function purge(pid, name) {
    if (!confirm(`永久删除“${name}”？该操作不可恢复。`)) return
    try {
      await api.domains.products.purgeProduct(pid)
      showToast('已永久删除')
      await Promise.all([loadTrash(), reload()])
    } catch (error) {
      showToast(error.message || '彻底删除失败', 'error')
    }
  }
  return { showTrash, trashedProducts, loadTrash, toggleTrash, restore, purge }
}


export function useProductBom(currentProductId, productForm) {
  const productBom = ref([])
  const bomForm = ref({ material_id: '', quantity: 1, process_id: null })
  const materialOptions = ref([])
  const processOptions = ref([])

  function resetBomForm() {
    const weight = Number(productForm.value.weight)
    bomForm.value = {
      material_id: '',
      quantity: Number.isFinite(weight) && weight > 0 ? weight : 1,
      process_id: processOptions.value.find(item => item.name === '下料')?.id || null,
    }
  }
  async function loadProductBom(pid) {
    if (!pid) { productBom.value = []; return }
    try {
      const data = await api.domains.products.listProductBom(pid)
      productBom.value = data.bom || []
    } catch (_) {
      productBom.value = []
    }
  }
  async function loadMaterialOptions() {
    try {
      const data = await api.domains.materials.listMaterials()
      materialOptions.value = data.materials || []
    } catch (error) {
      materialOptions.value = []
      showToast(error.message || '加载物料选项失败', 'error')
    }
  }
  async function loadProcessOptions() {
    try {
      const data = await api.domains.processes.listProcesses()
      processOptions.value = data.items || data.processes || []
      resetBomForm()
    } catch (error) {
      processOptions.value = []
      showToast(error.message || '加载工序选项失败', 'error')
    }
  }
  async function addBomItem() {
    if (!bomForm.value.material_id) { showToast('请选择物料', 'error'); return }
    let quantity
    try {
      quantity = positiveBomQuantity(bomForm.value.quantity)
    } catch (error) {
      showToast(error.message, 'error')
      return
    }
    try {
      await api.domains.products.addProductBom(currentProductId.value, {
        material_id: Number(bomForm.value.material_id),
        quantity_per_unit: quantity,
        process_id: bomForm.value.process_id ? Number(bomForm.value.process_id) : null,
      })
      resetBomForm()
      showToast('BOM已添加')
      await loadProductBom(currentProductId.value)
    } catch (error) {
      showToast(error.message || 'BOM添加失败', 'error')
    }
  }
  async function removeBomItem(bomId) {
    try {
      await api.domains.products.deleteProductBom(currentProductId.value, bomId)
      await loadProductBom(currentProductId.value)
    } catch (error) {
      showToast(error.message || 'BOM删除失败', 'error')
    }
  }
  return {
    productBom, bomForm, materialOptions, processOptions, resetBomForm,
    loadProductBom, loadMaterialOptions, loadProcessOptions, addBomItem, removeBomItem,
  }
}
