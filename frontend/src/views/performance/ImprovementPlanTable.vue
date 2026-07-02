<template>
  <div class="card">
    <div class="card-header"><h3>🛠️ 改进计划闭环</h3></div>
    <div class="card-body">
      <div class="table-wrap">
        <table v-if="plans.length" class="data-table" style="font-size:var(--text-sm)">
          <thead><tr><th>员工</th><th>月份</th><th>预警</th><th>目标</th><th>措施</th><th>负责人</th><th>截止</th><th>状态</th><th>复评</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="plan in plans" :key="plan.id">
              <td>{{ plan.user_name }}</td><td>{{ plan.year_month }}</td>
              <td><span class="badge" :class="warningClass(plan.warning_level)">{{ warningText(plan.warning_level) }}</span></td>
              <td>{{ plan.goal }}</td><td>{{ plan.actions }}</td><td>{{ plan.owner_name || '-' }}</td><td>{{ plan.due_date || '-' }}</td>
              <td>{{ plan.status }}</td><td>{{ plan.review_result || '-' }}</td>
              <td><button v-if="canEdit && plan.status === 'open'" class="btn btn-sm btn-success" @click="$emit('close', plan)">关闭复评</button></td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty">暂无改进计划。</p>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    plans: { type: Array, default: () => [] },
    canEdit: { type: Boolean, default: false },
    warningText: { type: Function, required: true },
    warningClass: { type: Function, required: true },
  },
  emits: ['close'],
}
</script>
