import { onMounted } from 'vue'

import { auth } from '@/lib/auth.js'
import { useCompletionFocus } from './order/useCompletionFocus.js'
import { useOrderAttachments } from './order/useOrderAttachments.js'
import { useOrderEditor } from './order/useOrderEditor.js'
import { useOrderMaterials } from './order/useOrderMaterials.js'
import { useOrderProgress } from './order/useOrderProgress.js'
import { useOrderQuery } from './order/useOrderQuery.js'
import { useOrderRework } from './order/useOrderRework.js'
import { useOrderTrash } from './order/useOrderTrash.js'
import { useQrcode } from './useQrcode.js'


export function useOrder() {
  const query = useOrderQuery()
  const editor = useOrderEditor({
    customers: query.customers,
    products: query.products,
    processRoutes: query.processRoutes,
    loadDropdownData: query.loadDropdownData,
    load: query.load,
  })
  const materials = useOrderMaterials({
    modalId: editor.modalId,
    products: query.products,
  })
  const attachments = useOrderAttachments({
    orders: query.orders,
    expandedId: query.expandedId,
    toggleExpand: query.toggleExpand,
    isCompletedOrder: editor.isCompletedOrder,
    completedReadonlyToast: editor.completedReadonlyToast,
  })
  const rework = useOrderRework({
    load: query.load,
    isCompletedOrder: editor.isCompletedOrder,
    completedReadonlyToast: editor.completedReadonlyToast,
  })
  const trash = useOrderTrash({ load: query.load })
  const progress = useOrderProgress()
  const completionFocus = useCompletionFocus()
  const qr = useQrcode()

  async function openEdit(order) {
    const opened = await editor.openEdit(order)
    if (opened) await materials.prepareOrderMaterials(order)
  }

  onMounted(async () => {
    await query.loadDropdownData()
    query.load()
  })

  return {
    ...query,
    ...editor,
    openEdit,
    auth,
    ...qr,
    ...attachments,
    ...trash,
    ...progress,
    ...completionFocus,
    ...materials,
    ...rework,
  }
}
