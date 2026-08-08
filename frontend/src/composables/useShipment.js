import { computed, onMounted } from 'vue'

import { can } from '@/lib/auth.js'
import { useDeliveryNote } from '@/composables/shipment/useDeliveryNote.js'
import { useShipmentActions } from '@/composables/shipment/useShipmentActions.js'
import { useShipmentEditor } from '@/composables/shipment/useShipmentEditor.js'
import { useShipmentQuery } from '@/composables/shipment/useShipmentQuery.js'


const statusMap = {
  pending: { label: '待出库', cls: 'badge-info' },
  completed: { label: '已出库', cls: 'badge-success' },
  received: { label: '已签收', cls: 'badge-primary' },
  cancelled: { label: '已取消', cls: 'badge-info' },
  reversed: { label: '已冲销', cls: 'badge-danger' },
}

const paymentStatusMap = {
  unpaid: { label: '未收款', cls: 'badge-info' },
  partial: { label: '部分收', cls: 'badge-warning' },
  paid: { label: '已收清', cls: 'badge-success' },
}

export function useShipment() {
  const query = useShipmentQuery()
  const editor = useShipmentEditor({ reload: query.load })
  const actions = useShipmentActions({ reload: query.load })
  const deliveryNote = useDeliveryNote()

  const canCreate = computed(() => can('shipments:create'))
  const canEdit = computed(() => can('shipments:edit'))
  const canDelete = computed(() => can('shipments:delete'))
  const canComplete = computed(() => can('shipments:complete'))
  const canCancel = computed(() => can('shipments:cancel'))
  const canReceive = computed(() => can('shipments:receive'))
  const canFinance = computed(() => can('shipments:finance'))
  const canLogistics = computed(() => can('shipments:logistics'))

  onMounted(async () => {
    await editor.loadInventory()
    query.load()
  })

  return {
    ...query,
    ...editor,
    ...actions,
    ...deliveryNote,
    statusMap,
    paymentStatusMap,
    canCreate,
    canEdit,
    canDelete,
    canComplete,
    canCancel,
    canReceive,
    canFinance,
    canLogistics,
  }
}
