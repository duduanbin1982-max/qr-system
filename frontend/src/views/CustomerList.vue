<!-- CustomerList.vue -->
<template>
<div style="padding:var(--space-6)">
    <!-- 统计栏 -->
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">🏢</span><div><div class="s-val">{{ customers.length }}</div><div class="s-label">客户总数</div></div></div>
      <div class="summary-item"><span class="s-icon">📞</span><div><div class="s-val text-primary">{{ hasContact }}</div><div class="s-label">有联系人</div></div></div>
      <div class="summary-item"><span class="s-icon">📧</span><div><div class="s-val text-success">{{ hasEmail }}</div><div class="s-label">有邮箱</div></div></div>
    </div>
    
    <div class="card">
      <div class="card-header">
        <h3>🏢 客户管理</h3>
        <div style="display:flex;gap:var(--space-2);align-items:center">
          <div class="search-box" style="background:var(--bg-hover);border-radius:var(--radius-md);display:flex;align-items:center;padding:0 10px">
            <span>🔍</span>
            <input class="form-input" v-model="searchKeyword" placeholder="搜索名称/联系人/电话..." @keyup.enter="load" style="border:none;background:transparent;outline:none;padding:var(--space-2) 6px;font-size:var(--text-base);width:200px;box-shadow:none">
          </div>
          <button class="btn btn-default btn-sm" @click="load">搜索</button>
          <button class="btn btn-primary btn-sm" @click="openAdd" v-if="canCreate">+ 添加客户</button>
        </div>
      </div>
      <div class="card-body">
        <div class="table-wrap">
          <table v-if="customers.length" class="data-table" style="min-width:800px">
            <thead>
              <tr>
                <th style="width:40px;text-align:center">#</th>
                <th style="min-width:120px">客户名称</th>
                <th style="min-width:80px">联系人</th>
                <th style="min-width:110px">联系电话</th>
                <th style="min-width:100px">邮箱</th>
                <th>地址</th>
                <th style="min-width:80px">备注</th>
                <th style="width:100px;text-align:center">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(c, idx) in customers" :key="c.id">
                <td style="text-align:center"><span class="row-num">{{ idx + 1 }}</span></td>
                <td><a style="color:var(--primary);font-weight:600;cursor:pointer" @click="viewDetail(c)">{{ c.name }}</a></td>
                <td>{{ c.contact || '-' }}</td>
                <td><a v-if="c.phone" :href="'tel:' + c.phone" style="color:var(--primary);text-decoration:none">{{ c.phone }}</a><span v-else>-</span></td>
                <td style="color:var(--text-placeholder)"><a v-if="c.email" :href="'mailto:' + c.email" style="color:var(--primary);text-decoration:none">{{ c.email }}</a><span v-else>-</span></td>
                <td :title="c.address || ''" style="max-width:150px;overflow:hidden;text-overflow:ellipsis;color:var(--text-placeholder);font-size:var(--text-sm)">{{ c.address || '-' }}</td>
                <td style="max-width:100px;overflow:hidden;text-overflow:ellipsis;color:var(--text-placeholder);font-size:var(--text-xs)">{{ c.remark || '-' }}</td>
                <td style="text-align:center">
                  <div class="o-actions" style="justify-content:center">
                    <span v-if="canEdit" class="o-abtn o-edit" @click="openEdit(c)" title="编辑">✏️</span>
                    <span v-if="canDelete" class="o-abtn o-del" @click="del(c)" title="删除">🗑️</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty"><div class="empty-icon">🏢</div><div class="empty-text">暂无客户数据</div></div>
        </div>
      </div>
    </div>
    
    <!-- 新增/编辑模态框 -->
    <div v-if="showModal" class="modal-overlay" >
      <div class="modal">
        <div class="modal-header">
          <span>{{ modalEdit ? '编辑客户' : '添加客户' }}</span>
          <span class="modal-close" @click="showModal=false">&times;</span>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-col">
              <div class="form-group"><label>客户名称 *</label><input class="form-input" v-model="form.name" placeholder="客户公司名称"></div>
            </div>
            <div class="form-col">
              <div class="form-group"><label>联系人</label><input class="form-input" v-model="form.contact" placeholder="联系人姓名"></div>
            </div>
          </div>
          <div class="form-row">
            <div class="form-col">
              <div class="form-group"><label>联系电话</label><input class="form-input" v-model="form.phone" placeholder="联系电话"></div>
            </div>
            <div class="form-col">
              <div class="form-group"><label>邮箱</label><input class="form-input" v-model="form.email" placeholder="邮箱地址"></div>
            </div>
          </div>
          <div class="form-group"><label>地址</label><input class="form-input" v-model="form.address" placeholder="客户地址"></div>
          <div class="form-group"><label>备注</label><textarea class="form-input" v-model="form.remark" rows="2" placeholder="备注信息"></textarea></div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showModal=false">取消</button>
          <button class="btn btn-primary" @click="save">保存</button>
        </div>
      </div>
    </div>
    
    <!-- 客户详情模态框 -->
    <div v-if="showDetail" class="modal-overlay" >
      <div class="modal" style="max-width:700px">
        <div class="modal-header">
          <span>📋 {{ detail?.name }} - 订单列表</span>
          <span class="modal-close" @click="showDetail=false">&times;</span>
        </div>
        <div class="modal-body">
          <div v-if="detailOrders.length">
            <table class="data-table">
              <thead><tr><th>订单号</th><th>产品</th><th>数量</th><th>状态</th><th>日期</th></tr></thead>
              <tbody>
                <tr v-for="o in detailOrders" :key="o.id">
                  <td><code>{{ o.order_no }}</code></td>
                  <td>{{ o.product_name || '-' }}</td>
                  <td>{{ o.quantity }}</td>
                  <td><span class="badge" :class="'badge-' + o.status">{{ o.status }}</span></td>
                  <td style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ o.created_at }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else style="text-align:center;color:var(--text-muted);padding:40px">暂无订单</p>
        </div>
      </div>
    </div>

    <!-- 删除阻止弹窗（客户有关联订单） -->
    <div v-if="showDeleteBlock" class="modal-overlay" >
      <div class="modal" style="max-width:560px">
        <div class="modal-header" style="background:#FFF7ED;border-bottom:2px solid #FDBA74">
          <span>⚠️ 无法删除客户</span>
          <span class="modal-close" @click="showDeleteBlock=false">&times;</span>
        </div>
        <div class="modal-body">
          <div style="background:#FFF7ED;border:1px solid #FDBA74;border-radius:10px;padding:12px 16px;margin-bottom:16px">
            <strong style="color:#C2410C">「{{ deleteCheck?.name }}」</strong>
            <span style="color:#9A3412"> 仍有 {{ deleteCheckOrders.length }} 个活跃订单关联，无法删除。</span>
            <div style="margin-top:6px;font-size:13px;color:#92400E">请先将以下订单删除或转移至其他客户后再试。</div>
          </div>
          <table class="data-table" style="font-size:13px">
            <thead><tr><th>订单号</th><th>产品</th><th>数量</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="o in deleteCheckOrders" :key="o.id">
                <td><code style="font-size:12px">{{ o.order_no }}</code></td>
                <td>{{ o.product_name || '-' }}</td>
                <td>{{ o.quantity }}</td>
                <td><span class="badge" :class="'badge-' + (o.status || 'pending')">{{ o.status }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="modal-footer">
          <button class="btn btn-primary" @click="showDeleteBlock=false">我知道了</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { auth, can } from '@/lib/auth.js'

export default {
  setup() {
    const customers = ref([])
    const loading = ref(true)
    const searchKeyword = ref('')
    
    // 模态框状态
    const showModal = ref(false)
    const modalEdit = ref(false)
    const modalId = ref(null)
    const form = ref({ name:'', contact:'', phone:'', email:'', address:'', remark:'' })
    
    // 详情模态框
    const detail = ref(null)
    const detailOrders = ref([])
    const showDetail = ref(false)
    const deleteCheck = ref(null)       // 正在检查删除的客户
    const deleteCheckOrders = ref([])   // 该客户的活跃订单
    const showDeleteBlock = ref(false)  // 删除被阻止的弹窗
    
    // 统计
    const hasContact = computed(() => customers.value.filter(c => c.contact).length)
    const hasEmail = computed(() => customers.value.filter(c => c.email).length)

    // RBAC
    const canEdit   = computed(() => can('customers:edit'))
    const canDelete = computed(() => can('customers:delete'))
    const canCreate = computed(() => can('customers:create'))
    
    async function load() {
      loading.value = true
      try {
        const kw = searchKeyword.value.trim()
        const d = await api.listCustomers(kw ? { keyword: kw } : null)
        customers.value = d.customers || []
      } catch(e) {
        showToast(e.message || '加载失败', 'error')
      } finally {
        loading.value = false
      }
    }
    
    function openAdd() {
      form.value = { name:'', contact:'', phone:'', email:'', address:'', remark:'' }
      modalEdit.value = false
      modalId.value = null
      showModal.value = true
    }
    
    function openEdit(c) {
      form.value = { name:c.name, contact:c.contact||'', phone:c.phone||'', email:c.email||'', address:c.address||'', remark:c.remark||'' }
      modalEdit.value = true
      modalId.value = c.id
      showModal.value = true
    }
    
    async function save() {
      if (!form.value.name || !form.value.name.trim()) {
        showToast('请输入客户名称', 'error')
        return
      }
      try {
        if (modalEdit.value) {
          await api.updateCustomer(modalId.value, form.value)
          showToast('更新成功')
        } else {
          await api.createCustomer(form.value)
          showToast('创建成功')
        }
        showModal.value = false
        await load()
      } catch(e) {
        showToast(e.message || '保存失败', 'error')
      }
    }
    
    async function del(c) {
      // 先查询客户关联的活跃订单
      deleteCheck.value = c
      deleteCheckOrders.value = []
      try {
        const d = await api.get('/api/customers/' + c.id + '/orders')
        const active = (d.orders || []).filter(o => o.deleted_at === null || o.deleted_at === undefined)
        if (active.length > 0) {
          deleteCheckOrders.value = active
          showDeleteBlock.value = true
          return
        }
      } catch(e) {
        // 查询失败，降级为直接确认删除
      }
      // 无活跃订单，确认后删除
      if (!confirm('确定删除客户 "' + c.name + '" 吗？\n\n该操作不可撤销。')) return
      try {
        await api.deleteCustomer(c.id)
        showToast('删除成功')
        await load()
      } catch(e) {
        showToast(e.message || '删除失败', 'error')
      }
    }
    
    async function viewDetail(c) {
      detail.value = c
      showDetail.value = true
      try {
        const d = await api.get('/api/customers/' + c.id + '/orders')
        detailOrders.value = d.orders || []
      } catch(e) {
        detailOrders.value = []
      }
    }
    
    onMounted(() => load())
    
    return {
      customers, loading, searchKeyword, load,
      showModal, modalEdit, form, openAdd, openEdit, save, del,
      showDetail, detail, detailOrders, viewDetail,
      deleteCheck, deleteCheckOrders, showDeleteBlock,
      hasContact, hasEmail, can, canEdit, canDelete, canCreate
    }
  }
}
</script>
