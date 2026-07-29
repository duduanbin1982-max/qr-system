import { computed, onMounted, ref } from 'vue'

import { can } from '@/lib/auth.js'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { useMaterialActivity } from '@/composables/material/useMaterialActivity.js'
import { useMaterialCatalog } from '@/composables/material/useMaterialCatalog.js'
import { useSupplierCatalog } from '@/composables/material/useSupplierCatalog.js'


export function useMaterial() {
  const catalog = useMaterialCatalog()
  const supplierCatalog = useSupplierCatalog()
  const selectedMaterial = ref(null)
  const activity = useMaterialActivity(selectedMaterial)

  const showForm = ref(false)
  const showStock = ref(false)
  const showSupplierForm = ref(false)
  const editing = ref(null)
  const saving = ref(false)
  const stockSaving = ref(false)
  const consumeSaving = ref(false)
  const supplierSaving = ref(false)

  const form = ref(emptyMaterialForm())
  const stockForm = ref({ type: 'in', quantity: 0, remark: '' })
  const supplierForm = ref({ name: '', contact: '', phone: '' })
  const consumeForm = ref({ order_id: null, process_id: null, quantity: 0, notes: '' })
  const orderSearch = ref('')
  const orderResults = ref([])
  const orderDropdown = ref(false)

  const canEdit = computed(() => can('materials:edit'))
  const canDelete = computed(() => can('materials:delete'))
  const canCreate = computed(() => can('materials:create'))
  const canStock = computed(() => can('materials:stock'))
  const canConsume = computed(() => can('materials:consume'))
  const canViewSuppliers = computed(() => can('suppliers:view'))
  const canCreateSupplier = computed(() => can('suppliers:create'))
  const canDeleteSupplier = computed(() => can('suppliers:delete'))

  const stockGap = computed(() => (form.value.quantity || 0) - (form.value.safe_stock || 0))
  const stockStatus = computed(() => {
    const gap = stockGap.value
    if (gap > 0) return { icon: 'passed', cls: 'stock-ok', text: '库存充足' }
    if (gap === 0) return { icon: 'warn', cls: 'stock-warn', text: '库存紧张' }
    return { icon: 'danger', cls: 'stock-danger', text: `低于安全库存 ${Math.abs(gap)}` }
  })
  const showStockWarning = computed(() => editing.value && stockGap.value < 0)

  function emptyMaterialForm() {
    return {
      name: '',
      spec: '',
      unit: '件',
      quantity: 0,
      unit_price: 0,
      safe_stock: 0,
      location: '',
      supplier_id: null,
      material_type: '',
      remark: '',
    }
  }

  function openCreate() {
    editing.value = null
    form.value = emptyMaterialForm()
    showForm.value = true
  }

  function openEdit(material) {
    editing.value = material.id
    form.value = {
      name: material.name || '',
      spec: material.spec || '',
      unit: material.unit || '件',
      quantity: Number(material.quantity || 0),
      unit_price: Number(material.unit_price || 0),
      safe_stock: Number(material.safe_stock || 0),
      location: material.location || '',
      supplier_id: material.supplier_id || null,
      material_type: material.material_type || '',
      remark: material.remark || '',
    }
    showForm.value = true
  }

  async function save() {
    if (saving.value) return
    if (!form.value.name.trim()) {
      showToast('名称必填', 'error')
      return
    }
    saving.value = true
    try {
      const payload = { ...form.value }
      for (const field of ['quantity', 'unit_price', 'safe_stock']) {
        if (payload[field] == null || payload[field] === '' || Number.isNaN(payload[field])) {
          payload[field] = 0
        }
      }
      if (!payload.supplier_id) payload.supplier_id = null
      if (editing.value) {
        delete payload.quantity
        await api.domains.materials.updateMaterial(editing.value, payload)
      } else {
        await api.domains.materials.createMaterial(payload)
      }
      showForm.value = false
      showToast('保存成功')
      await catalog.load()
    } catch (error) {
      showToast(error.message || '保存失败', 'error')
    } finally {
      saving.value = false
    }
  }

  async function remove(material) {
    if (!confirm(`确定删除物料「${material.name}」？`)) return
    try {
      const impact = await api.domains.materials.getMaterialImpact(material.id)
      if (impact && Number(impact.refs || 0) > 0) {
        showToast(`该物料正在被 ${impact.refs} 个地方引用，无法删除`, 'error')
        return
      }
      await api.domains.materials.deleteMaterial(material.id)
      showToast('已删除')
      await catalog.refreshAfterDelete()
    } catch (error) {
      showToast(error.message || '删除失败', 'error')
    }
  }

  function openStock(material) {
    selectedMaterial.value = material
    stockForm.value = { type: 'in', quantity: 0, remark: '' }
    showStock.value = true
  }

  async function doStock() {
    if (stockSaving.value) return
    if (stockForm.value.quantity <= 0) {
      showToast('数量必须大于0', 'error')
      return
    }
    stockSaving.value = true
    try {
      const result = await api.domains.materials.materialStockChange(
        selectedMaterial.value.id,
        stockForm.value,
      )
      selectedMaterial.value.quantity = result.new_quantity
      showStock.value = false
      showToast('操作成功')
      await catalog.load()
    } catch (error) {
      showToast(error.message || '库存调整失败', 'error')
    } finally {
      stockSaving.value = false
    }
  }

  function openConsume(material) {
    consumeForm.value = { order_id: null, process_id: null, quantity: 0, notes: '' }
    orderSearch.value = ''
    orderResults.value = []
    orderDropdown.value = false
    return activity.openConsume(material)
  }

  async function searchOrders() {
    if (!orderSearch.value.trim()) {
      orderResults.value = []
      orderDropdown.value = false
      return
    }
    try {
      const result = await api.domains.orders.listOrders({
        keyword: orderSearch.value.trim(),
        limit: 8,
      })
      orderResults.value = result.orders || []
      orderDropdown.value = true
    } catch {
      orderResults.value = []
      orderDropdown.value = false
    }
  }

  function selectOrder(order) {
    consumeForm.value.order_id = order.id
    orderSearch.value = `${order.order_no} ${order.product_name || ''}`.trim()
    orderDropdown.value = false
  }

  async function doConsume() {
    if (consumeSaving.value) return
    if (consumeForm.value.quantity <= 0) {
      showToast('数量必须大于0', 'error')
      return
    }
    consumeSaving.value = true
    try {
      const result = await api.domains.materials.createMaterialConsumption(
        selectedMaterial.value.id,
        consumeForm.value,
      )
      selectedMaterial.value.quantity = result.new_quantity
      showToast('消耗已记录')
      consumeForm.value.quantity = 0
      consumeForm.value.notes = ''
      await Promise.all([activity.refreshConsumptions(), catalog.load()])
    } catch (error) {
      showToast(error.message || '消耗记录失败', 'error')
    } finally {
      consumeSaving.value = false
    }
  }

  async function undoConsume(consumption) {
    const reason = prompt('请输入撤销原因')
    if (reason === null) return
    if (!reason.trim()) {
      showToast('请填写撤销原因', 'error')
      return
    }
    try {
      const result = await api.domains.materials.deleteMaterialConsumption(
        consumption.id,
        { reason: reason.trim() },
      )
      selectedMaterial.value.quantity = result.new_quantity
      showToast('已撤销')
      await Promise.all([activity.refreshConsumptions(), catalog.load()])
    } catch (error) {
      showToast(error.message || '撤销失败', 'error')
    }
  }

  function openSupplierAdd() {
    supplierForm.value = { name: '', contact: '', phone: '' }
    showSupplierForm.value = true
    return supplierCatalog.loadSuppliers()
  }

  async function addSupplier() {
    if (supplierSaving.value) return
    if (!supplierForm.value.name.trim()) {
      showToast('供应商名称必填', 'error')
      return
    }
    supplierSaving.value = true
    try {
      const result = await api.domains.materials.createSupplier(supplierForm.value)
      supplierForm.value = { name: '', contact: '', phone: '' }
      supplierCatalog.supplierPage.value = 1
      await supplierCatalog.refreshSuppliersAfterMutation()
      if (result.id) form.value.supplier_id = result.id
      showToast('供应商已添加')
    } catch (error) {
      showToast(error.message || '添加失败', 'error')
    } finally {
      supplierSaving.value = false
    }
  }

  async function deleteSupplier(supplier) {
    if (!confirm(`确定删除供应商「${supplier.name}」？如有业务关联将无法删除。`)) return
    try {
      await api.domains.materials.deleteSupplier(supplier.id)
      await supplierCatalog.refreshSuppliersAfterMutation()
      showToast('供应商已删除')
    } catch (error) {
      showToast(error.message || '删除失败', 'error')
    }
  }

  function fmtDate(value) {
    if (!value) return ''
    const match = value.match(/^\d{4}-\d{2}-\d{2}/)
    return match ? match[0] : value
  }

  function logTypeText(type) {
    return {
      in: '入库',
      out: '出库',
      baseline: '历史基线',
      reversal: '撤销回补',
    }[type] || type
  }

  function logQuantityText(log) {
    if (log.type === 'baseline') return `=${log.quantity}`
    return `${['in', 'reversal'].includes(log.type) ? '+' : '-'}${log.quantity}`
  }

  onMounted(() => {
    catalog.load()
    if (canViewSuppliers.value) {
      supplierCatalog.loadSuppliers()
      supplierCatalog.loadSupplierOptions()
    }
  })

  return {
    ...catalog,
    ...supplierCatalog,
    ...activity,
    selectedMaterial,
    showForm,
    showStock,
    showSupplierForm,
    editing,
    saving,
    stockSaving,
    consumeSaving,
    supplierSaving,
    form,
    stockForm,
    supplierForm,
    consumeForm,
    orderSearch,
    orderResults,
    orderDropdown,
    canEdit,
    canDelete,
    canCreate,
    canStock,
    canConsume,
    canViewSuppliers,
    canCreateSupplier,
    canDeleteSupplier,
    stockGap,
    stockStatus,
    showStockWarning,
    openCreate,
    openEdit,
    save,
    remove,
    openStock,
    doStock,
    openConsume,
    searchOrders,
    selectOrder,
    doConsume,
    undoConsume,
    openSupplierAdd,
    addSupplier,
    deleteSupplier,
    fmtDate,
    logTypeText,
    logQuantityText,
  }
}
