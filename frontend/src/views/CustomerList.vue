<!-- CustomerList.vue -->
<template>
<div style="padding:var(--space-6)">
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">🏢</span><div><div class="s-val">{{ totalCount }}</div><div class="s-label">客户总数</div></div></div>
      <div class="summary-item"><span class="s-icon">📦</span><div><div class="s-val text-info">{{ hasOrders }}</div><div class="s-label">有订单</div></div></div>
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
          <select v-model="tagFilter" @change="load" style="border:1px solid var(--border);border-radius:var(--radius-md);padding:6px 10px;font-size:var(--text-sm);background:white;width:100px">
            <option value="">全部标签</option>
            <option v-for="t in allTags" :key="t" :value="t">{{ t }}</option>
          </select>
          <button class="btn btn-primary btn-sm" @click="openAdd" v-if="canCreate">+ 添加客户</button>
        </div>
      </div>
      <div class="card-body">
        <div class="table-wrap">
          <table v-if="customers.length" class="data-table" style="min-width:900px">
            <thead>
              <tr>
                <th style="width:40px;text-align:center">#</th>
                <th style="min-width:120px">客户名称</th>
                <th style="min-width:70px">联系人</th>
                <th style="min-width:100px">标签</th>
                <th style="min-width:110px">联系电话</th>
                <th style="width:60px;text-align:center">订单</th>
                <th style="min-width:90px">最近下单</th>
                <th style="min-width:100px">邮箱</th>
                <th>地址</th>
                <th style="width:100px;text-align:center">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(c, idx) in customers" :key="c.id">
                <td style="text-align:center"><span class="row-num">{{ idx + 1 }}</span></td>
                <td><a style="color:var(--primary);font-weight:600;cursor:pointer" @click="viewDetail(c)">{{ c.name }}</a></td>
                <td>{{ c.contact || "-" }}</td>
                <td>
                  <span v-if="c.tags" style="display:flex;gap:4px;flex-wrap:wrap">
                    <span v-for="t in c.tags.split(',')" :key="t" :style="{background:tagColor(t.trim()),color:'#fff',padding:'1px 6px',borderRadius:'3px',fontSize:'var(--text-2xs)'}">{{ t.trim() }}</span>
                  </span>
                  <span v-else style="color:var(--text-placeholder)">-</span>
                </td>
                <td><a v-if="c.phone" :href="'tel:' + c.phone" style="color:var(--primary);text-decoration:none">{{ c.phone }}</a><span v-else>-</span></td>
                <td style="text-align:center"><span :style="{fontWeight:600,color:(c.order_count||0)>0?'var(--primary)':'var(--text-placeholder)'}">{{ c.order_count || 0 }}</span></td>
                <td style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ c.last_order_date ? c.last_order_date.slice(0,10) : "-" }}</td>
                <td style="color:var(--text-placeholder)"><a v-if="c.email" :href="'mailto:' + c.email" style="color:var(--primary);text-decoration:none">{{ c.email }}</a><span v-else>-</span></td>
                <td :title="c.address || ''" style="max-width:150px;overflow:hidden;text-overflow:ellipsis;color:var(--text-placeholder);font-size:var(--text-sm)">{{ c.address || "-" }}</td>
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
    
    <div v-if="showModal" class="modal-overlay" >
      <div class="modal">
        <div class="modal-header"><span>{{ modalEdit ? "编辑客户" : "添加客户" }}</span><span class="modal-close" @click="showModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-row"><div class="form-col"><div class="form-group"><label>客户名称 *</label><input class="form-input" v-model="form.name" placeholder="客户公司名称"></div></div><div class="form-col"><div class="form-group"><label>联系人</label><input class="form-input" v-model="form.contact" placeholder="联系人姓名"></div></div></div>
          <div class="form-row"><div class="form-col"><div class="form-group"><label>联系电话</label><input class="form-input" v-model="form.phone" placeholder="联系电话"></div></div><div class="form-col"><div class="form-group"><label>邮箱</label><input class="form-input" v-model="form.email" placeholder="邮箱地址"></div></div></div>
          <div class="form-group"><label>标签</label>
            <div style="display:flex;flex-wrap:wrap;gap:6px;padding:8px;border:1px solid var(--border-light);border-radius:var(--radius-md);min-height:36px;align-items:center">
              <span v-for="t in selectedTags" :key="t" style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:3px;font-size:var(--text-xs);color:#fff;cursor:pointer" :style="{background:tagColor(t)}" @click="removeTag(t)">{{ t }} ✕</span>
              <select v-model="newTag" @change="addTag" style="border:none;background:transparent;font-size:var(--text-xs);color:var(--text-placeholder);outline:none;flex:1;min-width:80px">
                <option value="">+ 添加标签</option>
                <option v-for="t in presetTags" :key="t" :value="t" :disabled="selectedTags.includes(t)">{{ t }}</option>
              </select>
            </div>
          </div>
          <div class="form-group"><label>地址</label><input class="form-input" v-model="form.address" placeholder="客户地址"></div>
          <div class="form-group"><label>备注</label><textarea class="form-input" v-model="form.remark" rows="2" placeholder="备注信息"></textarea></div>
        </div>
        <div class="modal-footer"><button class="btn btn-default" @click="showModal=false">取消</button><button class="btn btn-primary" @click="save">💾 保存</button></div>
      </div>
    </div>
    
    <div v-if="showDetail" class="modal-overlay" >
      <div class="modal" style="max-width:750px">
        <div class="modal-header"><span>📋 {{ detail?.name }} — 订单列表</span><span class="modal-close" @click="showDetail=false">&times;</span></div>
        <div class="modal-body">
          <div v-if="detail" style="margin-bottom:16px;padding:12px;background:var(--bg-hover);border-radius:var(--radius-md);display:flex;gap:24px;flex-wrap:wrap;font-size:var(--text-sm)">
            <span v-if="detail.contact">👤 联系人: <strong>{{ detail.contact }}</strong></span>
            <span v-if="detail.phone">📞 <a :href="'tel:'+detail.phone" style="color:var(--primary)">{{ detail.phone }}</a></span>
            <span v-if="detail.email">📧 <a :href="'mailto:'+detail.email" style="color:var(--primary)">{{ detail.email }}</a></span>
            <span v-if="detail.address">📍 {{ detail.address }}</span>
          </div>
          <div v-if="detailOrders.length" style="display:flex;flex-direction:column;gap:8px">
            <div v-for="o in detailOrders" :key="o.id" style="padding:12px;border:1px solid var(--border-light);border-radius:var(--radius-md);display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:var(--text-sm)">
              <code style="font-weight:600;color:var(--primary);min-width:100px">{{ o.order_no }}</code>
              <span style="color:var(--text-primary);flex:1;min-width:120px">{{ o.product_name || "-" }}</span>
              <span style="color:var(--text-placeholder)">📦 {{ o.quantity }}件</span>
              <span style="color:var(--text-placeholder)">✅ {{ o.completed || 0 }}</span>
              <span :style="{padding:'2px 8px',borderRadius:'3px',fontSize:'var(--text-xs)',color:'#fff',background:o.status==='producing'?'#2563eb':o.status==='completed'?'#16a34a':o.status==='pending'?'#9ca3af':'#6b7280'}">{{ o.status==='producing'?'生产中':o.status==='completed'?'已完成':o.status==='pending'?'待生产':o.status }}</span>
              <span v-if="o.plan_start" style="font-size:var(--text-xs);color:var(--text-muted)">{{ o.plan_start }} ~ {{ o.plan_end || "?" }}</span>
            </div>
          </div>
          <div v-else style="text-align:center;padding:30px;color:var(--text-placeholder)">暂无订单记录</div>
        </div>
        <div class="modal-footer"><button class="btn btn-primary" @click="showDetail=false">关闭</button></div>
      </div>
    </div>
    
    <div v-if="showDeleteBlock" class="modal-overlay">
      <div class="modal" style="max-width:500px">
        <div class="modal-header"><span>⚠️ 无法删除</span><span class="modal-close" @click="showDeleteBlock=false">&times;</span></div>
        <div class="modal-body">
          <p>客户 <b>"{{ deleteCheck?.name }}"</b> 有以下活跃订单，无法删除：</p>
          <table class="data-table" style="font-size:13px"><thead><tr><th>订单号</th><th>产品</th><th>数量</th><th>状态</th></tr></thead>
            <tbody><tr v-for="o in deleteCheckOrders" :key="o.id"><td><code style="font-size:12px">{{ o.order_no }}</code></td><td>{{ o.product_name || "-" }}</td><td>{{ o.quantity }}</td><td><span class="badge" :class="'badge-' + (o.status || 'pending')">{{ o.status }}</span></td></tr></tbody>
          </table>
        </div>
        <div class="modal-footer"><button class="btn btn-primary" @click="showDeleteBlock=false">我知道了</button></div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, computed } from "vue"
import { api } from "@/lib/api.js"
import { showToast } from "@/lib/store.js"
import { can } from "@/lib/auth.js"

export default {
  setup() {
    const customers = ref([])
    const loading = ref(true)
    const searchKeyword = ref("")
    const showModal = ref(false)
    const modalEdit = ref(false)
    const modalId = ref(null)
    const form = ref({ name:"", contact:"", phone:"", email:"", address:"", remark:"", tags:"" })
    const detail = ref(null)
    const detailOrders = ref([])
    const showDetail = ref(false)
    const deleteCheck = ref(null)
    const deleteCheckOrders = ref([])
    const showDeleteBlock = ref(false)
    const presetTags = ["VIP", "长期合作", "新客户", "重点", "沉睡", "月结", "现结"]
    const selectedTags = ref([])
    const newTag = ref("")

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
    const allTags = computed(() => {
      const s = new Set()
      customers.value.forEach(c => { if(c.tags) c.tags.split(",").forEach(t => { const tt = t.trim(); if(tt) s.add(tt) }) })
      return [...s].sort()
    })
    const tagFilter = ref("")
    const hasContact = computed(() => customers.value.filter(c => c.contact).length)
    const hasEmail = computed(() => customers.value.filter(c => c.email).length)
    const hasOrders = computed(() => customers.value.filter(c => (c.order_count || 0) > 0).length)
    const totalCount = computed(() => customers.value.length)
    const canEdit = computed(() => can("customers:edit"))
    const canDelete = computed(() => can("customers:delete"))
    const canCreate = computed(() => can("customers:create"))
    
    async function load() {
      loading.value = true
      try {
        const kw = searchKeyword.value.trim()
        const tg = tagFilter.value
        const params = {}
        if (kw) params.keyword = kw
        if (tg) params.tag = tg
        const d = await api.listCustomers(Object.keys(params).length ? params : null)
        customers.value = d.customers || []
      } catch(e) { showToast(e.message || "加载失败", "error") }
      finally { loading.value = false }
    }
    
    function openAdd() {
      form.value = { name:"", contact:"", phone:"", email:"", address:"", remark:"", tags:"" }
      modalEdit.value = false; modalId.value = null; initTags(""); showModal.value = true
    }
    function openEdit(c) {
      form.value = { name:c.name, contact:c.contact||"", phone:c.phone||"", email:c.email||"", address:c.address||"", remark:c.remark||"", tags:c.tags||"" }
      modalEdit.value = true; modalId.value = c.id; initTags(c.tags||""); showModal.value = true
    }
    async function save() {
      if (!form.value.name || !form.value.name.trim()) { showToast("请输入客户名称", "error"); return }
      try {
        if (modalEdit.value) { await api.updateCustomer(modalId.value, form.value); showToast("更新成功") }
        else { await api.createCustomer(form.value); showToast("创建成功") }
        showModal.value = false; await load()
      } catch(e) { showToast(e.message || "保存失败", "error") }
    }
    async function del(c) {
      deleteCheck.value = c; deleteCheckOrders.value = []
      try {
        const d = await api.customerOrders(c.id)
        const active = (d.orders || []).filter(o => o.deleted_at === null || o.deleted_at === undefined)
        if (active.length > 0) { deleteCheckOrders.value = active; showDeleteBlock.value = true; return }
      } catch(e) {}
      if (!confirm("确定删除客户 \"" + c.name + "\" 吗？")) return
      try { await api.deleteCustomer(c.id); showToast("删除成功"); await load() }
      catch(e) { showToast(e.message || "删除失败", "error") }
    }
    async function viewDetail(c) {
      detail.value = c; showDetail.value = true
      try { const d = await api.customerOrders(c.id); detailOrders.value = d.orders || [] }
      catch(e) { detailOrders.value = [] }
    }
    onMounted(() => load())
    
    return {
      customers, loading, searchKeyword, load,
      showModal, modalEdit, form, openAdd, openEdit, save, del,
      showDetail, detail, detailOrders, viewDetail,
      deleteCheck, deleteCheckOrders, showDeleteBlock,
      hasContact, hasEmail, hasOrders, totalCount, canEdit, canDelete, canCreate, tagFilter, allTags, tagColor, presetTags, selectedTags, newTag, addTag, removeTag, initTags
    }
  }
}
</script>
