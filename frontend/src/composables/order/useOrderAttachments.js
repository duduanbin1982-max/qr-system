import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


export function useOrderAttachments({
  orders,
  expandedId,
  toggleExpand,
  isCompletedOrder,
  completedReadonlyToast,
}) {
  const attachments = ref({})
  const attachmentsLoading = ref({})
  const uploadInputRef = ref(null)

  async function loadAttachments(orderId) {
    attachmentsLoading.value = { ...attachmentsLoading.value, [orderId]: true }
    try {
      const data = await api.domains.orderAttachments.listOrderAttachments(orderId)
      attachments.value = { ...attachments.value, [orderId]: data.attachments || [] }
    } catch (error) {
      showToast(`加载附件失败: ${error.message || ''}`, 'error')
    } finally {
      attachmentsLoading.value = { ...attachmentsLoading.value, [orderId]: false }
    }
  }

  function getAttachments(orderId) {
    return attachments.value[orderId] || []
  }

  function isAttachmentsLoading(orderId) {
    return !!attachmentsLoading.value[orderId]
  }

  async function handleAttachmentUpload(orderId, event) {
    const order = orders.value.find(item => item.id === orderId)
    if (isCompletedOrder(order)) {
      completedReadonlyToast()
      event.target.value = ''
      return
    }
    const file = event.target.files?.[0]
    if (!file) return
    const formData = new FormData()
    formData.append('file', file)
    try {
      await api.domains.orderAttachments.uploadOrderAttachment(orderId, formData)
      showToast('上传成功')
      await loadAttachments(orderId)
    } catch (error) {
      showToast(`上传失败: ${error.message || ''}`, 'error')
    } finally {
      event.target.value = ''
    }
  }

  async function delAttachment(attachmentId, orderId) {
    const order = orders.value.find(item => item.id === orderId)
    if (isCompletedOrder(order)) { completedReadonlyToast(); return }
    if (!confirm('确定删除此附件吗？')) return
    try {
      await api.domains.orderAttachments.deleteAttachment(attachmentId)
      showToast('删除成功')
      await loadAttachments(orderId)
    } catch (error) {
      showToast(`删除失败: ${error.message || ''}`, 'error')
    }
  }

  function downloadAttachment(attachmentId) {
    window.open(api.domains.orderAttachments.downloadAttachment(attachmentId), '_blank')
  }

  function getFileIcon(fileType) {
    if (!fileType) return '📎'
    const type = fileType.toLowerCase()
    if (type.includes('image')) return '🖼️'
    if (type.includes('pdf')) return '📄'
    if (type.includes('word') || type.includes('document')) return '📝'
    if (type.includes('spreadsheet') || type.includes('excel')) return '📊'
    if (type.includes('cad') || type.includes('dwg') || type.includes('dxf')) return '📐'
    if (type.includes('zip') || type.includes('rar') || type.includes('compress')) return '📦'
    return '📎'
  }

  function formatFileSize(bytes) {
    if (!bytes) return '0 B'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  function toggleExpandAndLoad(id) {
    toggleExpand(id)
    if (expandedId.value === id && !attachments.value[id]) loadAttachments(id)
  }

  return {
    uploadInputRef,
    getAttachments, isAttachmentsLoading, handleAttachmentUpload,
    delAttachment, downloadAttachment, getFileIcon, formatFileSize, toggleExpandAndLoad,
  }
}
