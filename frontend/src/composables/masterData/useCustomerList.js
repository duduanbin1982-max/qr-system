import { ref, onMounted, computed } from "vue"
import { api } from "@/lib/api.js"
import { showToast } from "@/lib/store.js"
import { can } from "@/lib/auth.js"
import { useCustomerDetails } from "@/composables/customer/useCustomerDetails.js"

export function useCustomerList() {
  const customers = ref([])
  const loading = ref(true)
  const loadError = ref("")
  const searchKeyword = ref("")
  const showModal = ref(false)
  const modalEdit = ref(false)
  const modalId = ref(null)
  const form = ref({ name:"", contact:"", phone:"", email:"", address:"", remark:"", tags:"" })
  const deleteCheck = ref(null)
  const deleteCheckOrders = ref([])
  const showDeleteBlock = ref(false)
  const presetTags = ["VIP", "长期合作", "新客户", "重点", "沉睡", "月结", "现结"]
  const selectedTags = ref([])
  const newTag = ref("")
  const saving = ref(false)

  function addTag() {
    if (newTag.value && !selectedTags.value.includes(newTag.value)) {
      selectedTags.value.push(newTag.value)
      form.value.tags = selectedTags.value.join(",")
    }
    newTag.value = ""
  }
  function removeTag(t) {
    selectedTags.value = selectedTags.value.filter(x => x !== t)
    form.value.tags = selectedTags.value.join(",")
  }
  function initTags(tagsStr) {
    selectedTags.value = tagsStr ? tagsStr.split(",").map(t => t.trim()).filter(Boolean) : []
  }

  function tagColor(tag) {
    const colors = {"VIP":"#dc2626","长期合作":"#2563eb","新客户":"#16a34a","重点":"#f59e0b","沉睡":"#9ca3af","月结":"#7c3aed","现结":"#0891b2"}
    return colors[tag] || "#6b7280"
  }
  const allTags = ref([])
  const tagFilter = ref("")
  const page = ref(1)
  const pageSize = 20
  const total = ref(0)
  const summary = ref({ total: 0, with_orders: 0, with_contact: 0, with_email: 0 })
  const hasContact = computed(() => summary.value.with_contact || 0)
  const hasEmail = computed(() => summary.value.with_email || 0)
  const hasOrders = computed(() => summary.value.with_orders || 0)
  const totalCount = computed(() => summary.value.total || 0)
  const canEdit = computed(() => can("customers:edit"))
  const canDelete = computed(() => can("customers:delete"))
  const canCreate = computed(() => can("customers:create"))
  const canViewOrders = computed(() => can("orders:view"))
  const {
    showDetail, detail, detailOrders, detailLoading, detailError,
    detailPage, detailTotal, detailPageSize,
    viewDetail, loadDetailOrders, detailPrevPage, detailNextPage, closeDetail,
  } = useCustomerDetails(canViewOrders)

  async function load() {
    loading.value = true
    loadError.value = ""
    try {
      const kw = searchKeyword.value.trim()
      const tg = tagFilter.value
      const params = { page: page.value, limit: pageSize }
      if (kw) params.keyword = kw
      if (tg) params.tag = tg
      const d = await api.domains.customers.listCustomers(params)
      customers.value = d.customers || []
      total.value = d.total || 0
      summary.value = d.summary || { total: total.value, with_orders: 0, with_contact: 0, with_email: 0 }
      allTags.value = d.available_tags || []
    } catch(e) {
      customers.value = []
      total.value = 0
      summary.value = { total: 0, with_orders: 0, with_contact: 0, with_email: 0 }
      loadError.value = e.message || "客户数据加载失败"
      showToast(loadError.value, "error")
    }
    finally { loading.value = false }
  }

  function searchAndLoad() { page.value = 1; load() }
  function filterAndLoad() { page.value = 1; load() }
  function prevPage() { if (page.value > 1) { page.value--; load() } }
  function nextPage() { if (page.value * pageSize < total.value) { page.value++; load() } }

  function openAdd() {
    form.value = { name:"", contact:"", phone:"", email:"", address:"", remark:"", tags:"" }
    modalEdit.value = false; modalId.value = null; initTags(""); showModal.value = true
  }
  function openEdit(c) {
    form.value = { name:c.name, contact:c.contact||"", phone:c.phone||"", email:c.email||"", address:c.address||"", remark:c.remark||"", tags:c.tags||"" }
    modalEdit.value = true; modalId.value = c.id; initTags(c.tags||""); showModal.value = true
  }
  async function save() {
    if (saving.value) return
    if (!form.value.name || !form.value.name.trim()) { showToast("请输入客户名称", "error"); return }
    saving.value = true
    try {
      if (modalEdit.value) { await api.domains.customers.updateCustomer(modalId.value, form.value); showToast("更新成功") }
      else { await api.domains.customers.createCustomer(form.value); showToast("创建成功") }
      showModal.value = false; await load()
    } catch(e) { showToast(e.message || "保存失败", "error") }
    finally { saving.value = false }
  }
  async function del(c) {
    deleteCheck.value = c; deleteCheckOrders.value = []
    try {
      const d = await api.domains.customers.customerOrders(c.id)
      const active = (d.orders || []).filter(o => o.deleted_at === null || o.deleted_at === undefined)
      if (active.length > 0) { deleteCheckOrders.value = active; showDeleteBlock.value = true; return }
    } catch(e) { showToast("无法检查订单关联，跳过预检", "warning") }
    if (!confirm("确定删除客户 \"" + c.name + "\" 吗？")) return
    try { await api.domains.customers.deleteCustomer(c.id); showToast("删除成功"); await load() }
    catch(e) { showToast(e.message || "删除失败", "error") }
  }
  onMounted(() => load())

  return {
    customers, loading, loadError, searchKeyword, load, searchAndLoad, filterAndLoad,
    showModal, modalEdit, form, saving, openAdd, openEdit, save, del,
    showDetail, detail, detailOrders, detailLoading, detailError, viewDetail, loadDetailOrders, closeDetail,
    deleteCheck, deleteCheckOrders, showDeleteBlock,
    hasContact, hasEmail, hasOrders, totalCount, canEdit, canDelete, canCreate, canViewOrders, tagFilter, allTags, tagColor, presetTags, selectedTags, newTag, addTag, removeTag, initTags,
    page, pageSize, total, summary, prevPage, nextPage,
    detailPage, detailTotal, detailPageSize, detailPrevPage, detailNextPage
  }
}
