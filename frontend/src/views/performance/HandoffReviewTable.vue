<template>
  <div class="card" style="margin-top:var(--space-4)">
    <div class="card-header"><h3>🤝 工序交接评价明细</h3></div>
    <div class="card-body">
      <div class="table-wrap">
        <table v-if="reviews.length" class="data-table" style="font-size:var(--text-sm)">
          <thead><tr><th>时间</th><th>订单</th><th>序列号</th><th>上一工序/人员</th><th>当前工序/评价人</th><th>评分</th><th>问题</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="review in reviews" :key="review.id">
              <td>{{ review.created_at }}</td><td>{{ review.order_no }}</td><td>{{ review.serial_no || '-' }}</td>
              <td>{{ review.from_process_name }} / {{ review.from_user_name }}</td>
              <td>{{ review.to_process_name }} / {{ review.evaluator_name }}</td>
              <td><span class="badge" :class="review.rating <= 2 ? 'badge-danger' : 'badge-success'">{{ review.rating }}星</span></td>
              <td>{{ review.issue_type || review.comment || '-' }}</td>
              <td>{{ review.status }}</td>
              <td style="white-space:nowrap">
                <button v-if="canEdit && review.status === 'pending'" class="btn btn-sm btn-success" @click="$emit('confirm', review, 'confirmed')">确认</button>
                <button v-if="canEdit && review.status === 'pending'" class="btn btn-sm" @click="$emit('confirm', review, 'rejected')">驳回</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty">暂无工序交接评价。</p>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  props: {
    reviews: { type: Array, default: () => [] },
    canEdit: { type: Boolean, default: false },
  },
  emits: ['confirm'],
}
</script>
