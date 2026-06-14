<!-- ProcessConfig.vue -->
<template>
<div>
    <div>
      <div class="card" style="margin-bottom:var(--space-5)">
        <div class="card-header"><h3>⚙️ 工艺配置</h3></div>
        <div class="card-body">
          <div v-if="processConfigLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else style="display:grid;grid-template-columns:1fr 1fr;gap:24px">
            <!-- 工序报工顺序 -->
            <div>
              <label style="display:block;font-weight:600;font-size:var(--text-base);margin-bottom:var(--space-2)">工序报工顺序</label>
              <div style="display:flex;gap:var(--space-4)">
                <label style="display:flex;align-items:center;gap:var(--space-2);cursor:pointer;font-size:var(--text-base)">
                  <input type="radio" v-model="processConfig.process_order_mode" value="sequential"> 按顺序报工
                </label>
                <label style="display:flex;align-items:center;gap:var(--space-2);cursor:pointer;font-size:var(--text-base)">
                  <input type="radio" v-model="processConfig.process_order_mode" value="out_of_order"> 允许乱序报工
                </label>
              </div>
            </div>
            <!-- 交期预警天数 -->
            <div>
              <label style="display:block;font-weight:600;font-size:var(--text-base);margin-bottom:var(--space-2)">交期预警天数</label>
              <div style="display:flex;align-items:center;gap:var(--space-2)">
                <input class="form-input" type="number" v-model.number="processConfig.delivery_warning_days" min="0" max="365" style="width:100px">
                <span style="color:var(--text-placeholder);font-size:var(--text-base)">天</span>
              </div>
            </div>
            <!-- 报工数量上限 -->
            <div>
              <label style="display:block;font-weight:600;font-size:var(--text-base);margin-bottom:var(--space-3)">报工数量上限</label>
              <div style="display:flex;flex-direction:column;gap:var(--space-3)">
                <ToggleSwitch v-model="processConfig.limit_by_prev_process" label="上道工序累计上限" />
                <ToggleSwitch v-model="processConfig.limit_by_order_qty" label="订单总数上限" />
              </div>
            </div>
            <!-- 列表每页条数 -->
            <div>
              <label style="display:block;font-weight:600;font-size:var(--text-base);margin-bottom:var(--space-2)">列表每页条数</label>
              <div style="display:flex;align-items:center;gap:var(--space-2)">
                <input class="form-input" type="number" v-model.number="processConfig.page_size" min="5" max="200" style="width:100px">
                <span style="color:var(--text-placeholder);font-size:var(--text-base)">条/页</span>
              </div>
            </div>
            <!-- 审批设置 -->
            <div>
              <label style="display:block;font-weight:600;font-size:var(--text-base);margin-bottom:var(--space-3)">审批设置</label>
              <ToggleSwitch v-model="processConfig.approval_enabled" label="启用报工审批" />
            </div>
            <!-- 订单号前缀 -->
            <div>
              <label style="display:block;font-weight:600;font-size:var(--text-base);margin-bottom:var(--space-2)">自动生成订单号前缀</label>
              <input class="form-input" v-model="processConfig.auto_order_no" placeholder="如 YYMMDD 或 PO-" style="width:100%">
            </div>
          </div>
        </div>
      </div>
      <div style="text-align:right;margin-bottom:var(--space-6)">
        <button class="btn btn-primary" @click="saveProcessConfig" :disabled="processConfigSaving" style="min-width:120px">
          {{ processConfigSaving ? '⏳ 保存中...' : '💾 保存配置' }}
        </button>
      </div>
    </div>
</div>
</template>

<script>
import ToggleSwitch from '@/components/common/ToggleSwitch.vue'
import { useProcessConfig } from '@/composables/settings/useProcessConfig.js'

export default {
  components: { ToggleSwitch },
  setup() {
    return useProcessConfig()
  }
}
</script>