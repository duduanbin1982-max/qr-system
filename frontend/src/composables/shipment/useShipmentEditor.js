import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


function createEmptyForm() {
  return {
    shipment_no: '',
    customer: '',
    contact_person: '',
    contact_phone: '',
    address: '',
    remark: '',
    status: 'pending',
    material_bill_no: '',
    receivable_amount: 0,
  }
}

function createEmptyItem() {
  return {
    inventory_id: '',
    product_model: '',
    product_name: '',
    quantity: 1,
    unit: '件',
    remark: '',
    _search: '',
    _showDrop: false,
  }
}

export function useShipmentEditor({ reload }) {
  const saving = ref(false)
  const inventory = ref([])
  const showModal = ref(false)
  const modalEdit = ref(false)
  const modalId = ref(null)
  const form = ref(createEmptyForm())
  const items = ref([])

  async function loadInventory() {
    try {
      const data = await api.domains.inventory.listInventory()
      inventory.value = data.items || []
    } catch (error) {
      showToast('加载库存列表失败', 'warn')
    }
  }

  async function openAdd() {
    form.value = createEmptyForm()
    items.value = []
    modalEdit.value = false
    modalId.value = null
    try {
      const data = await api.domains.shipments.draftShipment()
      form.value.shipment_no = data.shipment_no
    } catch (error) {
      showToast('自动生成出库单号失败，请手动输入', 'warn')
    }
    showModal.value = true
  }

  function openEdit(shipment) {
    form.value = {
      shipment_no: shipment.shipment_no,
      material_bill_no: shipment.material_bill_no || '',
      customer: shipment.customer || '',
      contact_person: shipment.contact_person || '',
      contact_phone: shipment.contact_phone || '',
      address: shipment.address || '',
      remark: shipment.remark || '',
      status: shipment.status || 'pending',
      receivable_amount: shipment.receivable_amount || 0,
    }
    items.value = []
    modalEdit.value = true
    modalId.value = shipment.id
    showModal.value = true
  }

  function updateReceivable() {
    form.value.receivable_amount = items.value.reduce((total, item) => {
      const inventoryItem = inventory.value.find(row => row.id === item.inventory_id)
      return total + ((inventoryItem?.price || 0) * (item.quantity || 0))
    }, 0)
  }

  function addItem() {
    items.value.push(createEmptyItem())
  }

  function resetItem(index) {
    if (!items.value[index]) return
    items.value[index] = createEmptyItem()
    updateReceivable()
  }

  function removeItem(index) {
    items.value.splice(index, 1)
    updateReceivable()
  }

  function focusItem(index) {
    if (items.value[index]) items.value[index]._showDrop = true
  }

  function blurItem(index) {
    setTimeout(() => {
      if (items.value[index]) items.value[index]._showDrop = false
    }, 150)
  }

  function updateItemSearch(index, value) {
    if (!items.value[index]) return
    items.value[index]._search = value
    items.value[index]._showDrop = true
  }

  function updateItemQuantity(index, value) {
    if (!items.value[index]) return
    items.value[index].quantity = Number(value) || 0
    updateReceivable()
  }

  function selectInventory(index, inventoryItem) {
    const current = items.value[index]
    if (!current) return
    current.inventory_id = inventoryItem.id
    current.product_model = inventoryItem.product_model
    current.product_name = inventoryItem.product_name || ''
    current.unit = inventoryItem.unit || '件'
    current._showDrop = false
    current._search = ''
    updateReceivable()
  }

  async function save() {
    if (saving.value) return
    if (!modalEdit.value && !items.value.length) {
      showToast('请添加出库产品', 'error')
      return
    }
    saving.value = true
    try {
      const data = { ...form.value }
      if (modalEdit.value) {
        await api.domains.shipments.updateShipment(modalId.value, data)
        showToast('更新成功')
      } else {
        data.items = items.value.filter(item => item.inventory_id)
        if (!data.items.length) {
          showToast('请选择出库产品', 'error')
          return
        }
        const result = await api.domains.shipments.createShipment(data)
        showToast(result.warning || '创建成功', result.warning ? 'warn' : undefined)
      }
      showModal.value = false
      await reload()
    } catch (error) {
      showToast(error.message || '保存失败', 'error')
    } finally {
      saving.value = false
    }
  }

  return {
    saving,
    inventory,
    showModal,
    modalEdit,
    form,
    items,
    loadInventory,
    openAdd,
    openEdit,
    addItem,
    removeItem,
    resetItem,
    focusItem,
    blurItem,
    updateItemSearch,
    updateItemQuantity,
    selectInventory,
    save,
  }
}
