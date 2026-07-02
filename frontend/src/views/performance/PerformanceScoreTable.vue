<template>
  <div class="card" style="margin-bottom:var(--space-4)">
    <div class="card-header"><h3>📋 月度量化评分</h3></div>
    <div class="card-body">
      <div class="table-wrap">
        <table v-if="scores.length" class="data-table" style="font-size:var(--text-sm)">
          <thead>
            <tr>
              <th>排名</th><th>员工</th><th>工号</th><th>产量</th><th>报工</th><th>质量扣项</th>
              <th>产量</th><th>质量</th><th>交付</th><th>纪律</th><th>改进</th><th>总分</th><th>预警</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in scores" :key="row.id">
              <td>{{ row.rank_no }}/{{ row.rank_total }}</td>
              <td style="font-weight:600">{{ row.user_name }}</td>
              <td>{{ row.employee_no || '-' }}</td>
              <td>{{ row.output_qty }}</td>
              <td>{{ row.report_count }}</td>
              <td>{{ badQty(row) }}</td>
              <td>{{ row.output_score }}</td>
              <td>{{ row.quality_score }}</td>
              <td>{{ row.delivery_score }}</td>
              <td>{{ row.discipline_score }}</td>
              <td>{{ row.improvement_score }}</td>
              <td><span class="badge badge-info">{{ row.total_score }}</span></td>
              <td><span class="badge" :class="warningClass(row.warning_level)">{{ warningText(row.warning_level) }}</span></td>
              <td style="white-space:nowrap;display:flex;gap:var(--space-1);flex-wrap:wrap">
                <button class="btn btn-sm" @click="$emit('detail', row)">依据</button>
                <button v-if="canEdit" class="btn btn-sm" @click="$emit('review', row)">评议</button>
                <button v-if="canCreate && row.warning_level !== 'green'" class="btn btn-sm" @click="$emit('plan', row)">建改进计划</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty">暂无评分数据，请先生成本月评分。</p>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    scores: { type: Array, default: () => [] },
    canCreate: { type: Boolean, default: false },
    canEdit: { type: Boolean, default: false },
    warningText: { type: Function, required: true },
    warningClass: { type: Function, required: true },
    badQty: { type: Function, required: true },
  },
  emits: ['detail', 'review', 'plan'],
}
</script>
