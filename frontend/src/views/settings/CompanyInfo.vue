<!-- CompanyInfo.vue — 🏢 公司资料 -->
<template>
<!-- ========== 公司资料 ========== -->
<div>
      <div class="card" style="margin-bottom:var(--space-5)">
        <div class="card-header">
          <h3>🏢 公司资料</h3>
        </div>
        <div class="card-body">
          <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else style="max-width:640px">
            <div style="padding:var(--space-3) 0;border-bottom:1px solid var(--bg-hover)">
              <label style="display:block;font-size:var(--text-sm);font-weight:500;color:var(--text-secondary);margin-bottom:6px">公司名称</label>
              <input class="form-input" v-model="edits.company_name" placeholder="请输入公司名称" style="font-size:var(--text-base)">
            </div>
            <div style="padding:var(--space-3) 0;border-bottom:1px solid var(--bg-hover)">
              <label style="display:block;font-size:var(--text-sm);font-weight:500;color:var(--text-secondary);margin-bottom:6px">联系人</label>
              <input class="form-input" v-model="edits.contact" placeholder="请输入联系人" style="font-size:var(--text-base)">
            </div>
            <div style="padding:var(--space-3) 0;border-bottom:1px solid var(--bg-hover)">
              <label style="display:block;font-size:var(--text-sm);font-weight:500;color:var(--text-secondary);margin-bottom:6px">联系电话</label>
              <input class="form-input" v-model="edits.phone" placeholder="请输入联系电话" style="font-size:var(--text-base)">
            </div>
            <div style="padding:var(--space-3) 0;border-bottom:1px solid var(--bg-hover)">
              <label style="display:block;font-size:var(--text-sm);font-weight:500;color:var(--text-secondary);margin-bottom:6px">公司地址</label>
              <input class="form-input" v-model="edits.address" placeholder="请输入公司地址" style="font-size:var(--text-base)">
            </div>
            <div style="padding:var(--space-3) 0">
              <label style="display:block;font-size:var(--text-sm);font-weight:500;color:var(--text-secondary);margin-bottom:6px">公司简介</label>
              <textarea class="form-input" v-model="edits.description" placeholder="请输入公司简介" rows="3" style="font-size:var(--text-base)"></textarea>
            </div>
          </div>
        </div>
      </div>
      <div style="text-align:right">
        <button class="btn" @click="saveSettings" :disabled="saving"
          :style="{minWidth:'120px', background: companyInfoDirty ? 'var(--warning)' : 'var(--primary)', color:'var(--bg-surface)'}">
          {{ saving ? '⏳ 保存中...' : (companyInfoDirty ? '💾 保存设置 ●' : '💾 保存设置') }}
        </button>
      </div>
    </div>

</template>

<script>
import { useCompanyInfo } from '@/composables/settings/useCompanyInfo.js'

export default {
  setup() {
    return useCompanyInfo()
  }
}
</script>
