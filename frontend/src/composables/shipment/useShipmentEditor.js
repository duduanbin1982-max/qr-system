import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


const INVENTORY_SEARCH_DEBOUNCE_MS = 250
const INVENTORY_SEARCH_LIMIT = 50


function createEmptyForm() {
  return {
    shipment_no: '',
    customer: '',
    contact_person: '',
    contact_phone: '',
    address: '',
    remark: '',
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
    _options: null,
    _loading: false,
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

  // Search timers/sequences live outside the reactive item payload so the
  // picker keeps rendering only plain data.
  const searchTimers = new WeakMap()
  const searchSequences = new WeakMap()

  function cancelPendingSearch(item) {
    if (!item) return
    const timer = searchTimers.get(item)
    if (timer) {
      clearTimeout(timer)
      searchTimers.delete(item)
    }
    // Invalidate any in-flight response for this item.
    searchSequences.set(item, (searchSequences.get(item) || 0) + 1)
  }

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
    const current = items.value[index]
    if (!current) return
    cancelPendingSearch(current)
    items.value[index] = createEmptyItem()
    updateReceivable()
  }

  function removeItem(index) {
    const current = items.value[index]
    if (current) cancelPendingSearch(current)
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

  /**
   * Search inventory on the server side.
   *
   * The picker used to filter only the first inventory page (100 rows sorted by
   * updated_at desc), so any inventory row outside that window (for example a
   * completed order that has not been touched for months) could never be
   * selected when creating a shipment. The keyword search below hits
   * GET /api/inventory, whose SQL also matches orders.order_no.
   */
  function updateItemSearch(index, value) {
    const current = items.value[index]
    if (!current) return
    const keyword = String(value || '').trim()
    current._search = value
    current._showDrop = true
    cancelPendingSearch(current)
    if (!keyword) {
      current._options = null
      current._loading = false
      return
    }
    const sequence = (searchSequences.get(current) || 0) + 1
    searchSequences.set(current, sequence)
    current._loading = true
    const timer = setTimeout(async () => {
      searchTimers.delete(current)
      try {
        const data = await api.domains.inventory.listInventory({
          keyword,
          limit: INVENTORY_SEARCH_LIMIT,
        })
        if (searchSequences.get(current) !== sequence) return
        if (String(current._search || '').trim() !== keyword) return
        current._options = data.items || []
      } catch (error) {
        if (searchSequences.get(current) === sequence) {
          current._options = []
        }
        showToast('库存搜索失败', 'warn')
      } finally {
        if (searchSequences.get(current) === sequence) {
          current._loading = false
        }
      }
    }, INVENTORY_SEARCH_DEBOUNCE_MS)
    searchTimers.set(current, timer)
  }

  function updateItemQuantity(index, value) {
    if (!items.value[index]) return
    items.value[index].quantity = Number(value) || 0
    updateReceivable()
  }

  function selectInventory(index, inventoryItem) {
    const current = items.value[index]
    if (!current) return
    cancelPendingSearch(current)
    current.inventory_id = inventoryItem.id
    current.product_model = inventoryItem.product_model
    current.product_name = inventoryItem.product_name || ''
    current.unit = inventoryItem.unit || '件'
    current._showDrop = false
    current._search = ''
    current._options = null
    current._loading = false
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
        await api.domains.shipments.updateShipment(modalId.value, {
          customer: data.customer,
          contact_person: data.contact_person,
          contact_phone: data.contact_phone,
          address: data.address,
          remark: data.remark,
          receivable_amount: data.receivable_amount,
        })
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
