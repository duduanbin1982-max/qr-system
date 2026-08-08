<template>
  <div class="card">
    <div class="card-header"><h3>改进计划台账</h3></div>
    <div class="card-body">
      <div class="table-wrap">
        <table v-if="plans.length" class="data-table improvement-table">
          <thead><tr><th>员工</th><th>生产月</th><th>问题级别</th><th>目标 / 措施</th><th>负责人 / 截止</th><th>状态</th><th>复评轮次</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="plan in plans" :key="plan.id">
              <td><strong>{{ plan.employee_name_snapshot || plan.user_name }}</strong><small>{{ plan.employee_no_snapshot || '-' }}</small></td>
              <td>{{ plan.production_month || plan.year_month }}</td>
              <td><span class="badge" :class="warningClass(plan.warning_level_snapshot || plan.warning_level)">{{ warningText(plan.warning_level_snapshot || plan.warning_level) }}</span></td>
              <td><strong>{{ plan.goal || '-' }}</strong><small>{{ plan.actions || '-' }}</small></td>
              <td>{{ plan.owner_name_snapshot || plan.owner_name || '-' }}<small>{{ plan.due_date || '未设置截止日期' }}</small></td>
              <td><span class="plan-status" :class="`status-${plan.status}`">{{ statusLabel(plan.status) }}</span></td>
              <td>{{ plan.reassessment_round || 0 }}</td>
              <td class="action-cell">
                <button class="btn btn-sm" @click="$emit('detail', plan)">详情</button>
                <button v-if="canManage && plan.status === 'draft'" class="btn btn-sm btn-primary" @click="$emit('activate', plan)">激活</button>
                <button v-if="canManage && plan.status === 'active'" class="btn btn-sm" :data-testid="`plan-evidence-${plan.id}`" @click="$emit('evidence', plan)">追加证据</button>
                <button v-if="canManage && plan.status === 'active'" class="btn btn-sm btn-primary" @click="$emit('request-reassessment', plan)">申请复评</button>
                <button v-if="canReassess && plan.status === 'reassessment_pending'" class="btn btn-sm btn-primary" @click="$emit('reassess', plan)">执行复评</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty">当前生产月暂无改进计划。</p>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    plans: { type: Array, default: () => [] },
    canManage: { type: Boolean, default: false },
    canReassess: { type: Boolean, default: false },
    warningText: { type: Function, required: true },
    warningClass: { type: Function, required: true },
  },
  emits: ['detail', 'activate', 'evidence', 'request-reassessment', 'reassess'],
  methods: {
    statusLabel(status) {
      return {
        draft: '草稿', active: '执行中', reassessment_pending: '待复评', closed: '复评通过', cancelled: '已取消',
      }[status] || status || '-'
    },
  },
}
</script>

<style scoped>
.improvement-table{min-width:1080px;font-size:var(--text-sm)}td strong,td small{display:block}td small{margin-top:4px;color:var(--text-placeholder);font-size:var(--text-xs-alt)}
.plan-status{display:inline-block;padding:3px 7px;border-radius:4px;background:var(--bg-secondary);white-space:nowrap}.status-active{color:var(--primary);background:var(--primary-light)}.status-reassessment_pending{color:var(--warning);background:var(--warning-light)}.status-closed{color:var(--success);background:var(--success-light)}
.action-cell{white-space:nowrap}.action-cell .btn{margin:2px 4px 2px 0}
</style>
