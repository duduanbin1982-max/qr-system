<!-- ReworkList.vue -->
<template>
<div style="padding:var(--space-6)">
    <!-- Stats Row -->
    <div class="summary-bar">
      <div class="card" style="flex:1;padding:var(--space-3) 20px;border-left:3px solid var(--warning);display:flex;align-items:center;gap:var(--space-3)">
        <div style="font-size:var(--text-2xl)">🔧</div>
        <div><div style="font-size:var(--text-2xl);font-weight:700;color:var(--warning)">{{ stats.pending_count }}</div><div style="font-size:var(--text-sm);color:var(--text-muted)">待处理 / {{ stats.pending_qty }} 件</div></div>
      </div>
      <div class="card" style="flex:1;padding:var(--space-3) 20px;border-left:3px solid var(--danger);display:flex;align-items:center;gap:var(--space-3)">
        <div style="font-size:var(--text-2xl)">📋</div>
        <div><div style="font-size:var(--text-2xl);font-weight:700;color:var(--danger)">{{ stats.today_count }}</div><div style="font-size:var(--text-sm);color:var(--text-muted)">今日新增 / {{ stats.today_qty }} 件</div></div>
      </div>
      <div class="card" style="flex:1;padding:var(--space-3) 20px;border-left:3px solid var(--success);display:flex;align-items:center;gap:var(--space-3)">
        <div style="font-size:var(--text-2xl)">✅</div>
        <div><div style="font-size:var(--text-2xl);font-weight:700;color:var(--success)">{{ stats.today_done }}</div><div style="font-size:var(--text-sm);color:var(--text-muted)">今日完成 / {{ stats.today_done_qty }} 件</div></div>
      </div>
      <div class="card" style="flex:1;padding:var(--space-3) 20px;border-left:3px solid var(--primary-accent);display:flex;align-items:center;gap:var(--space-3)">
        <div style="font-size:var(--text-2xl)">📅</div>
        <div><div style="font-size:var(--text-2xl);font-weight:700" :style="{color: stats.week_rate > 5 ? 'var(--danger)' : 'var(--primary-accent)'}">{{ stats.week_rate }}%</div><div style="font-size:var(--text-sm);color:var(--text-muted)">本周返工率 / {{ stats.week_rework_qty || 0 }} 件</div></div>
      </div>
      <div class="card" style="flex:1;padding:var(--space-3) 20px;border-left:3px solid var(--warning);display:flex;align-items:center;gap:var(--space-3)">
        <div style="font-size:var(--text-2xl)">📆</div>
        <div><div style="font-size:var(--text-2xl);font-weight:700" :style="{color: stats.month_rate > 5 ? 'var(--danger)' : 'var(--warning)'}">{{ stats.month_rate }}%</div><div style="font-size:var(--text-sm);color:var(--text-muted)">本月返工率 / {{ stats.month_rework_qty || 0 }} 件</div></div>
      </div>
    </div>

    <!-- Main Card -->
    <div class="card" style="border-radius:var(--radius-lg);overflow:hidden;padding:0">
      <div class="card-header" style="display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap;padding:var(--space-3) 20px">
        <h3 style="font-size:var(--text-lg);font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:var(--space-2);margin:0">
          <span style="display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;background:linear-gradient(135deg,var(--warning),var(--warning-dark));border-radius:var(--radius-md);font-size:var(--text-lg);color:white">🔧</span>
          返工管理
        </h3>
        <div style="display:flex;gap:var(--space-2);align-items:center;margin-left:auto;flex-wrap:wrap">
          <button class="btn-sm" :style="{borderRadius:'8px',border:'1px solid var(--border-light)',background:statusFilter==='pending'?'var(--warning)':'var(--bg-surface)',color:statusFilter==='pending'?'#fff':'var(--text-placeholder)',padding:'6px 14px',cursor:'pointer',fontWeight:statusFilter==='pending'?'600':'400'}" @click="switchTab('pending')">待处理</button>
          <button class="btn-sm" :style="{borderRadius:'8px',border:'1px solid var(--border-light)',background:statusFilter==='completed'?'var(--success)':'var(--bg-surface)',color:statusFilter==='completed'?'#fff':'var(--text-placeholder)',padding:'6px 14px',cursor:'pointer',fontWeight:statusFilter==='completed'?'600':'400'}" @click="switchTab('completed')">已完成</button>
          <select v-model="filterWorker" class="form-input" style="width:110px;font-size:var(--text-xs);padding:6px 8px" @change="applyFilter">
            <option value="">全部工人</option>
            <option v-for="w in workers" :key="w.id" :value="w.id">{{ w.name }}</option>
          </select>
          <select v-model="filterProcess" class="form-input" style="width:100px;font-size:var(--text-xs);padding:6px 8px" @change="applyFilter">
            <option value="">全部工序</option>
            <option v-for="p in processes" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
          <input v-model="search" @keyup.enter="applyFilter" placeholder="搜索订单号..." class="form-input" style="margin-left:4px;width:160px;font-size:var(--text-sm);padding:6px 10px">
          <input v-model="dateFrom" type="date" class="form-input" style="width:130px;font-size:var(--text-xs);padding:var(--space-1) 8px" @change="applyFilter">
          <span style="color:var(--text-placeholder);font-size:var(--text-xs)">至</span>
          <input v-model="dateTo" type="date" class="form-input" style="width:130px;font-size:var(--text-xs);padding:var(--space-1) 8px" @change="applyFilter">
          <button v-if="statusFilter==='pending' && selectedIds.length && canEdit" @click="openBatchComplete" class="btn-success btn-sm" style="padding:6px 12px;white-space:nowrap">✅ 批量完成 ({{ selectedIds.length }})</button>
          <button @click="exportData" class="btn-sm" style="background:var(--primary-light);color:var(--primary);border:1px solid var(--primary-light);padding:6px 12px;white-space:nowrap;cursor:pointer">📥 导出</button>
        </div>
      </div>

      <div v-if="loading" style="text-align:center;padding:60px;color:var(--text-placeholder)">⏳ 加载中...</div>

      <!-- Pending Table -->
      <div v-else-if="statusFilter==='pending'" style="padding:0 20px 20px">
        <div v-if="!items.length" style="text-align:center;padding:50px;color:var(--text-placeholder)">✅ 暂无待处理返工</div>
        <table v-else style="width:100%;border-collapse:collapse">
          <thead><tr style="border-bottom:1px solid var(--border-light);color:var(--text-placeholder);font-size:var(--text-xs)">
            <th style="padding:var(--space-3) 4px;text-align:center;font-weight:500;width:30px">
              <input type="checkbox" @change="toggleSelectAll" :checked="allSelected">
            </th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:130px">订单号</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">产品 / 客户</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:80px">工序</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:70px">工人</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:55px">数量</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:130px">原因</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:85px">时间</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:100px">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="it in items" :key="it.id" :style="{borderBottom:'1px solid var(--bg-hover)',fontSize:'var(--text-sm)',transition:'background .15s',background: isOverdue(it) ? 'var(--danger-lighter, #fff0f0)' : ''}" @mouseenter="it._hover=true" @mouseleave="it._hover=false">
              <td style="padding:var(--space-3) 4px;text-align:center">
                <input type="checkbox" :checked="selectedIds.includes(it.id)" @change="toggleSelect(it.id)">
              </td>
              <td style="padding:var(--space-3) 12px">
                <div style="font-weight:600;color:var(--primary)">{{ it.order_no }}</div>
                <div style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ it.product_name }}</div>
              </td>
              <td style="padding:var(--space-3) 12px;font-size:var(--text-xs);color:var(--text-placeholder)">{{ it.customer_name }}</td>
              <td style="padding:var(--space-3) 12px;color:var(--primary-accent);font-weight:500">{{ it.process_name }}</td>
              <td style="padding:var(--space-3) 12px">{{ it.worker_name }}</td>
              <td style="padding:var(--space-3) 12px;text-align:center;font-weight:600">{{ it.quantity }}</td>
              <td style="padding:var(--space-3) 12px">
                <div v-if="editing===it.id" style="display:flex;gap:var(--space-1);align-items:center">
                  <input v-model="editReason" class="form-input" style="width:110px;font-size:var(--text-xs);padding:var(--space-1) 6px" @keyup.enter="saveEdit(it)">
                  <button class="btn-success btn-sm" :disabled="editSubmitting" style="padding:3px 8px;font-size:var(--text-xs-alt)" @click="saveEdit(it)">{{ editSubmitting ? '保存中' : '保存' }}</button>
                  <button class="btn-sm" :disabled="editSubmitting" style="padding:3px 8px;font-size:var(--text-xs-alt);background:var(--bg-hover);border:1px solid var(--border-light);border-radius:var(--radius-sm);cursor:pointer;color:var(--text-placeholder)" @click="cancelEdit">取消</button>
                </div>
                <div v-else style="display:flex;align-items:center;gap:var(--space-1)">
                  <span v-if="it.reason" style="background:var(--warning-lighter);color:var(--warning);padding:var(--space-1) 8px;border-radius:var(--radius-sm);font-size:var(--text-xs);max-width:120px;display:inline-block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ it.reason }}</span>
                  <span v-else style="color:var(--text-placeholder)">-</span>
                  <button v-if="editing!==it.id && canEdit" class="btn-icon-edit btn-icon-sm" style="font-size:var(--text-xs);flex-shrink:0;margin-left:2px" @click="startEdit(it)" title="编辑原因">✏️</button>
                </div>
              </td>
              <td style="padding:var(--space-3) 12px;text-align:center;font-size:var(--text-xs-alt)" :style="{color: isOverdue(it) ? 'var(--danger)' : 'var(--text-placeholder)'}">
                {{ fmtDate(it.created_at) }}
                <span v-if="isOverdue(it)" style="display:block;font-size:var(--text-2xs);font-weight:600;color:var(--danger);margin-top:2px">⚠ {{ overdueHours(it) }}h</span>
              </td>
              <td style="padding:var(--space-3) 12px;text-align:center">
                <button @click="openComplete(it)" v-if="canEdit" class="btn-success btn-sm" style="padding:var(--space-1) 14px">完成返工</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="total > perPage" style="display:flex;justify-content:center;align-items:center;gap:var(--space-3);padding:var(--space-4) 0 0">
          <button class="btn-default btn-sm" @click="load(page-1)" :disabled="page<=1">上一页</button>
          <span style="font-size:var(--text-sm);color:var(--text-placeholder)">第 {{ page }} / {{ Math.ceil(total/perPage) }} 页（共 {{ total }} 条）</span>
          <button class="btn-default btn-sm" @click="load(page+1)" :disabled="page*perPage >= total">下一页</button>
        </div>
      </div>

      <!-- Completed Table -->
      <div v-else style="padding:0 20px 20px">
        <div v-if="!items.length" style="text-align:center;padding:50px;color:var(--text-placeholder)">暂无已完成记录</div>
        <table v-else style="width:100%;border-collapse:collapse">
          <thead><tr style="border-bottom:1px solid var(--border-light);color:var(--text-placeholder);font-size:var(--text-xs)">
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:130px">订单号</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500">产品 / 客户</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:80px">工序</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:70px">工人</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:55px">数量</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:130px">原因</th>
            <th style="padding:var(--space-3) 12px;text-align:left;font-weight:500;width:85px">完成人</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:70px">结果</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:70px">耗时</th>
            <th style="padding:var(--space-3) 12px;text-align:center;font-weight:500;width:140px">完成时间</th>
          </tr></thead>
          <tbody>
            <tr v-for="it in items" :key="it.id" style="border-bottom:1px solid var(--bg-hover);font-size:var(--text-sm)">
              <td style="padding:var(--space-2) 12px">
                <div style="font-weight:600;color:var(--primary)">{{ it.order_no }}</div>
                <div style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ it.product_name }}</div>
              </td>
              <td style="padding:var(--space-2) 12px;font-size:var(--text-xs);color:var(--text-placeholder)">{{ it.customer_name }}</td>
              <td style="padding:var(--space-2) 12px;color:var(--primary-accent);font-weight:500">{{ it.process_name }}</td>
              <td style="padding:var(--space-2) 12px">{{ it.worker_name }}</td>
              <td style="padding:var(--space-2) 12px;text-align:center;font-weight:600">{{ it.quantity }}</td>
              <td style="padding:var(--space-2) 12px">
                <span v-if="it.reason" style="background:var(--warning-lighter);color:var(--warning);padding:var(--space-1) 8px;border-radius:var(--radius-sm);font-size:var(--text-xs)">{{ it.reason }}</span>
                <span v-else style="color:var(--text-placeholder)">-</span>
              </td>
              <td style="padding:var(--space-2) 12px;color:var(--text-secondary)">{{ it.completed_by_name || '-' }}</td>
              <td style="padding:var(--space-2) 12px;text-align:center">
                <span v-if="it.result==='ok'" style="color:var(--success);font-weight:600">✅ 合格</span>
                <span v-else-if="it.result==='scrap'" style="color:var(--danger);font-weight:600">❌ 报废</span>
                <span v-else-if="it.result==='rework_again'" style="color:var(--warning);font-weight:600">🔧 再返</span>
                <span v-else style="color:var(--text-placeholder)">-</span>
              </td>
              <td style="padding:var(--space-2) 12px;text-align:center;font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ it.duration_hours ? it.duration_hours+'h' : '-' }}</td>
              <td style="padding:var(--space-2) 12px;text-align:center;font-size:var(--text-xs-alt);color:var(--success)">{{ fmtDatetime(it.completed_at) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="total > perPage" style="display:flex;justify-content:center;align-items:center;gap:var(--space-3);padding:var(--space-4) 0 0">
          <button class="btn-default btn-sm" @click="load(page-1)" :disabled="page<=1">上一页</button>
          <span style="font-size:var(--text-sm);color:var(--text-placeholder)">第 {{ page }} / {{ Math.ceil(total/perPage) }} 页（共 {{ total }} 条）</span>
          <button class="btn-default btn-sm" @click="load(page+1)" :disabled="page*perPage >= total">下一页</button>
        </div>
      </div>
    </div>
  </div>

    <!-- 批量完成弹窗 -->
    <div v-if="showBatchModal" class="modal-overlay" >
      <div class="modal" style="max-width:440px;width:95%">
        <div class="modal-header">
          <span>✅ 批量完成返工 ({{ selectedIds.length }} 条)</span>
          <span class="modal-close" @click="showBatchModal=false">&times;</span>
        </div>
        <div class="modal-body">
          <div class="form-group"><label>批量结果 *</label>
            <select class="form-input" v-model="batchResult">
              <option value="ok">✅ 合格</option>
              <option value="scrap">❌ 报废</option>
              <option value="rework_again">🔧 需再次返工</option>
            </select>
          </div>
          <div class="form-group"><label>批量原因（可选）</label>
            <textarea class="form-input" v-model="batchReason" rows="2" placeholder="统一返工原因..."></textarea>
          </div>
          <div style="font-size:var(--text-xs);color:var(--text-placeholder);padding:8px;background:var(--bg-hover);border-radius:8px">
            将对选中的 {{ selectedIds.length }} 条待处理返工统一标记完成
          </div>
          <div v-if="batchErrors.length" style="margin-top:10px;padding:8px;border:1px solid var(--danger-light);background:var(--danger-lighter);color:var(--danger);font-size:var(--text-xs);max-height:120px;overflow:auto">
            <div v-for="error in batchErrors" :key="error.id">记录 {{ error.id }}：{{ error.error }}</div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" :disabled="batchSubmitting" @click="showBatchModal=false">取消</button>
          <button class="btn btn-primary" :disabled="batchSubmitting" @click="doBatchComplete">{{ batchSubmitting ? '处理中...' : '确认批量完成' }}</button>
        </div>
      </div>
    </div>

    <!-- 完成返工弹窗 -->
    <div v-if="completingItem" class="modal-overlay" >
      <div class="modal" style="max-width:420px;width:95%">
        <div class="modal-header">
          <span>✅ 完成返工 — {{ completingItem.order_no }}</span>
          <span class="modal-close" @click="closeComplete">&times;</span>
        </div>
        <div class="modal-body">
          <div style="margin-bottom:12px;font-size:var(--text-sm)">
            <b>工序:</b> {{ completingItem.process_name }} | <b>数量:</b> {{ completingItem.quantity }} | <b>工人:</b> {{ completingItem.worker_name }}
          </div>
          <div class="form-group"><label>返工结果 *</label>
            <select class="form-input" v-model="completeResult">
              <option value="ok">✅ 合格 — 返工后通过检验</option>
              <option value="scrap">❌ 报废 — 无法修复</option>
              <option value="rework_again">🔧 需再次返工</option>
            </select>
          </div>
          <div class="form-group"><label>处理备注</label>
            <textarea class="form-input" v-model="completeResultRemark" rows="2" placeholder="返工处理说明..."></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" :disabled="completeSubmitting" @click="closeComplete">取消</button>
          <button class="btn btn-primary" :disabled="completeSubmitting" @click="doComplete">{{ completeSubmitting ? '提交中...' : '确认完成' }}</button>
        </div>
      </div>
    </div>
</template>

<script>
import { useReworkList } from '@/composables/quality/useReworkList.js'

export default {
  setup() {
    return useReworkList()
  }
}
</script>
