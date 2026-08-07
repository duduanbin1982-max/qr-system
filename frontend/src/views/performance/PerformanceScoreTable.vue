<template>
  <div class="card performance-table-card">
    <div class="card-header"><h3>正式评分明细</h3></div>
    <div class="card-body">
      <div class="table-wrap">
        <table v-if="scores.length" class="data-table performance-score-table">
          <thead>
            <tr>
              <th>部门 / 岗位</th><th>员工</th><th>参评状态</th><th>产量 / 报工</th>
              <th>产量分</th><th>质量分</th><th>交付分</th><th>纪律分</th><th>改进分</th>
              <th>总分</th><th>岗位排名</th><th>预警</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in scores" :key="row.id" :data-testid="`score-row-${row.user_id}`">
              <td><strong>{{ row.department_name || '未设置部门' }}</strong><small>{{ row.position_name || '未设置岗位' }}</small></td>
              <td><strong>{{ row.user_name }}</strong><small>{{ row.employee_no || '-' }}</small></td>
              <td>
                <span v-if="isEligible(row)" class="badge badge-success">正常参评</span>
                <span v-else class="badge badge-warning">数据不足</span>
                <small v-if="!isEligible(row)">{{ row.eligibility_reason || eligibilityReason(row) }}</small>
              </td>
              <td>{{ row.output_qty ?? 0 }}<small>{{ row.report_count ?? 0 }} 次报工</small></td>
              <template v-if="isEligible(row)">
                <td>{{ row.output_score }}</td><td>{{ row.quality_score }}</td><td>{{ row.delivery_score }}</td>
                <td>{{ row.discipline_score }}</td><td>{{ row.improvement_score }}</td>
                <td><span data-testid="score-total" class="score-total">{{ row.total_score }}</span></td>
                <td><span data-testid="score-rank">{{ row.rank_no }}/{{ row.rank_total }}</span></td>
                <td><span data-testid="score-grade" class="badge" :class="warningClass(row.warning_level)">{{ warningText(row.warning_level) }}</span></td>
              </template>
              <template v-else>
                <td colspan="8" class="insufficient-cell">不生成分数、等级和排名</td>
              </template>
              <td class="action-cell">
                <button class="btn btn-sm" @click="$emit('detail', row)">查看依据</button>
                <button v-if="canPlan && isEligible(row) && row.warning_level !== 'green'" class="btn btn-sm" @click="$emit('plan', row)">新建计划</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty">当前生产月暂无正式绩效结果。</p>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    scores: { type: Array, default: () => [] },
    canPlan: { type: Boolean, default: false },
    warningText: { type: Function, required: true },
    warningClass: { type: Function, required: true },
  },
  emits: ['detail', 'plan'],
  methods: {
    isEligible(row) {
      return row.eligible === true || row.eligibility_status === 'eligible'
    },
    eligibilityReason(row) {
      const labels = {
        missing_position: '缺少岗位快照',
        missing_position_target: '缺少生效岗位目标',
        insufficient_work_days: '有效工作日不足',
        unresolved_data_exception: '存在未确认数据异常',
        zero_output: '无有效产量',
      }
      return labels[row.eligibility_reason_code] || '来源数据未达到评分条件'
    },
  },
}
</script>

<style scoped>
.performance-table-card{margin:0}.performance-score-table{min-width:1280px;font-size:var(--text-sm)}
td strong,td small{display:block}td small{margin-top:3px;color:var(--text-placeholder);font-size:var(--text-xs-alt)}
.score-total{font-weight:700;color:var(--primary)}.insufficient-cell{color:var(--text-placeholder);text-align:center;background:var(--bg-secondary)}
.action-cell{white-space:nowrap}.action-cell .btn+.btn{margin-left:6px}
</style>
