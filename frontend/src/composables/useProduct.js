import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { router } from '@/lib/router.js'
import { showToast } from '@/lib/store.js'
import {
  MACHINING_SPECS,
  PRODUCT_CATEGORIES,
  STRUCTURAL_SPECS,
  createProductForm,
  normalizeProductPayload,
} from './productForm.js'
import {
  useProductAttachments,
  useProductBom,
  useProductImport,
  useProductTrash,
} from './useProductResources.js'


function categoryFromPage(page) {
  if (page === 'structure-products') return '结构件'
  if (page === 'machining-products') return '机加工'
  return ''
}


export function useProduct() {
  const products = ref([])
  const loading = ref(true)
  const searchKeyword = ref('')
  const filterCategory = ref(categoryFromPage(router.page))
  const page = ref(1)
  const limit = ref(20)
  const total = ref(0)
  const summary = ref({ total: 0, structural: 0, machining: 0 })
  let listRequest = 0

  const activeCat = computed(() => filterCategory.value || 'all')
  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / limit.value)))
  const structCount = computed(() => summary.value.structural || 0)
  const machCount = computed(() => summary.value.machining || 0)
  const totalProducts = computed(() => summary.value.total || 0)
  const pageTitle = computed(() => {
    if (filterCategory.value === '结构件') return '⚙️ 结构件产品'
    if (filterCategory.value === '机加工') return '⚙️ 机加工产品'
    return '📋 全部产品'
  })

  async function load() {
    const requestId = ++listRequest
    loading.value = true
    try {
      const params = { page: page.value, limit: limit.value }
      const keyword = searchKeyword.value.trim()
      if (keyword) params.keyword = keyword
      if (filterCategory.value) params.category = filterCategory.value
      const data = await api.domains.products.listProducts(params)
      if (requestId !== listRequest) return
      products.value = data.products || []
      total.value = data.total || 0
      summary.value = data.summary || { total: data.total || 0, structural: 0, machining: 0 }
      if (page.value > totalPages.value) {
        page.value = totalPages.value
        await load()
      }
    } catch (error) {
      if (requestId === listRequest) showToast(error.message || '加载失败', 'error')
    } finally {
      if (requestId === listRequest) loading.value = false
    }
  }
  async function searchAndLoad() {
    page.value = 1
    await load()
  }
  async function switchCat(category) {
    filterCategory.value = category === 'all' ? '' : category
    page.value = 1
    await load()
  }
  async function previousPage() {
    if (page.value <= 1) return
    page.value -= 1
    await load()
  }
  async function nextPage() {
    if (page.value >= totalPages.value) return
    page.value += 1
    await load()
  }

  const showModal = ref(false)
  const modalEdit = ref(false)
  const modalId = ref(null)
  const currentEditProductId = ref(null)
  const form = ref(createProductForm({}, filterCategory.value || '结构件'))
  const currentSpecOptions = computed(() => (
    form.value.category === '机加工' ? MACHINING_SPECS : STRUCTURAL_SPECS
  ))
  const canEdit = computed(() => can('products:edit'))
  const canCreate = computed(() => can('products:create'))
  const canDelete = computed(() => can('products:delete'))
  let previewRequest = 0
  let previewTimer

  function updateProductCode() {
    clearTimeout(previewTimer)
    if (!(form.value.product_name || '').trim()) {
      form.value.product_code = ''
      return
    }
    const requestId = ++previewRequest
    previewTimer = setTimeout(async () => {
      try {
        const payload = normalizeProductPayload(form.value)
        const data = await api.domains.products.previewProductCode(payload)
        if (requestId === previewRequest) form.value.product_code = data.product_code || ''
      } catch (_) {
        if (requestId === previewRequest) form.value.product_code = ''
      }
    }, 180)
  }

  const attachments = useProductAttachments(currentEditProductId)
  const bom = useProductBom(currentEditProductId, form)
  const importer = useProductImport(load)
  const trash = useProductTrash(load)

  function openAdd() {
    form.value = createProductForm({}, filterCategory.value || '结构件')
    modalEdit.value = false
    modalId.value = null
    currentEditProductId.value = null
    attachments.clearProductAttachments()
    bom.productBom.value = []
    bom.resetBomForm()
    showModal.value = true
  }
  async function openEdit(product) {
    form.value = createProductForm(product)
    modalEdit.value = true
    modalId.value = product.id
    currentEditProductId.value = product.id
    attachments.clearProductAttachments()
    await Promise.all([
      bom.loadMaterialOptions(),
      bom.loadProcessOptions(),
      bom.loadProductBom(product.id),
      attachments.loadProductAttachments(product.id),
    ])
    bom.resetBomForm()
    showModal.value = true
  }
  async function save() {
    if (!(form.value.product_name || '').trim()) {
      showToast('请输入产品名称', 'error')
      return
    }
    let payload
    try {
      payload = normalizeProductPayload(form.value)
    } catch (error) {
      showToast(error.message, 'error')
      return
    }
    try {
      if (modalEdit.value) {
        await api.domains.products.updateProduct(modalId.value, payload)
        showToast('更新成功')
      } else {
        await api.domains.products.createProduct(payload)
        showToast('创建成功')
      }
      showModal.value = false
      await load()
    } catch (error) {
      showToast(error.message || '保存失败', 'error')
    }
  }
  async function del(product) {
    if (!confirm(`确定将产品“${product.product_name}”移入回收站吗？`)) return
    try {
      await api.domains.products.deleteProduct(product.id)
      showToast('已移入回收站')
      await load()
    } catch (error) {
      showToast(error.message || '删除失败', 'error')
    }
  }

  watch(
    () => [
      form.value.product_name,
      form.value.model,
      form.value.spec,
      form.value.style,
      form.value.upper_opening,
      form.value.lower_opening,
      form.value.plate_thickness,
      form.value.category,
    ],
    updateProductCode,
  )
  watch(() => router.page, async routePage => {
    const category = categoryFromPage(routePage)
    if (filterCategory.value !== category) {
      filterCategory.value = category
      page.value = 1
      await load()
    }
  })
  onMounted(load)

  return {
    products, loading, searchKeyword, filterCategory, pageTitle, load, searchAndLoad,
    page, limit, total, totalPages, totalProducts, previousPage, nextPage,
    showModal, modalEdit, form, openAdd, openEdit, save, del,
    structCount, machCount, categories: PRODUCT_CATEGORIES,
    specOptions: currentSpecOptions, can, canEdit, canCreate, canDelete,
    updateProductCode, currentEditProductId, activeCat, switchCat,
    ...attachments, ...importer, ...trash, ...bom,
  }
}
