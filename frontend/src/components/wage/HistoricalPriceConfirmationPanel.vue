<template>
  <section class="manual-panel" data-testid="historical-price-confirmation-panel">
    <div class="manual-heading">
      <div>
        <h4>历史工价人工确认</h4>
        <p>按订单、产品、路线和工序确认工价；系统内部编号仅用于后台审计。</p>
      </div>
      <span v-if="!props.loading" class="manual-count">{{ props.reviews.length }} 项待确认</span>
    </div>

    <div v-if="props.loading" class="manual-empty">正在加载历史人工确认项...</div>
    <div v-else-if="!props.reviews.length" class="manual-empty">没有待人工确认的历史报工。</div>
    <div v-else class="manual-list">
      <article v-for="review in props.reviews" :key="review.review_id" class="manual-card">
        <div class="manual-card-main">
          <div class="manual-card-title">
            <strong>{{ review.process?.name || '未命名工序' }}</strong>
            <span>工序 V{{ review.process?.version || '-' }}</span>
          </div>
          <div class="manual-route">{{ review.route?.name || '未命名路线' }} · 路线 V{{ review.route?.version || '-' }}</div>
          <div class="manual-orders">
            <span class="label">受影响订单</span>
            <span v-for="order in review.affected_orders || []" :key="order.order_id" class="order-chip">
              {{ order.order_no }}<em v-if="order.product_code"> · {{ order.product_code }}</em>
              <small v-if="order.product_name">{{ order.product_name }}</small>
            </span>
          </div>
          <div class="manual-evidence">{{ review.evidence?.work_record_count || 0 }} 条报工 · {{ review.evidence?.quantity || 0 }} 件</div>
        </div>

        <div class="manual-card-side">
          <div v-if="review.candidate_prices?.length" class="candidate-box">
            <span>历史参考（仅参考）</span>
            <button v-for="(candidate, index) in review.candidate_prices.slice(0, 2)" :key="`${candidate.valid_from}-${index}`" type="button" class="candidate-button" @click="openCreate(review, candidate)">
              {{ unitPrice(candidate.normal_unit_price_micros) }} · {{ formatDate(candidate.valid_from) }}
            </button>
          </div>
          <div v-if="draftFor(review)" class="draft-status">
            <span>已建草稿</span><strong>{{ unitPrice(draftFor(review).normal_unit_price_micros) }}</strong><small>等待独立批准</small>
          </div>
          <div class="manual-actions">
            <button v-if="props.canPrepare && !draftFor(review)" type="button" class="btn btn-primary btn-sm" @click="openCreate(review)">填写这条工序工价</button>
            <button v-if="props.canPrepare && draftFor(review)?.status === 'draft'" type="button" class="btn btn-default btn-sm" @click="voidDraft(draftFor(review))">作废草稿</button>
            <button v-if="props.canApprove && draftFor(review)?.status === 'draft'" type="button" class="btn btn-primary btn-sm" :disabled="busy" @click="approveDraft(draftFor(review))">独立批准</button>
          </div>
        </div>
      </article>
    </div>

    <div v-if="editorOpen" class="manual-overlay" @click.self="closeEditor">
      <section class="manual-editor" role="dialog" aria-modal="true" aria-labelledby="manual-editor-title">
        <header class="manual-editor-header">
          <div><h4 id="manual-editor-title">确认历史工价</h4><p>{{ selectedReview?.affected_orders?.[0]?.order_no || '-' }} · {{ selectedReview?.process?.name || '-' }}</p></div>
          <button type="button" class="icon-button" aria-label="关闭" @click="closeEditor">×</button>
        </header>
        <div class="manual-editor-body">
          <div class="locked-summary">
            <div><span>产品 / 订单</span><strong>{{ orderSummary }}</strong></div>
            <div><span>路线</span><strong>{{ routeSummary }}</strong></div>
            <div><span>工序</span><strong>{{ processSummary }}</strong></div>
          </div>
          <div v-if="referenceCandidate" class="reference-note">已带入历史参考工价 {{ unitPrice(referenceCandidate.normal_unit_price_micros) }}；请人工核对，系统不会自动套用。</div>
          <div class="manual-form-grid">
            <label>正常工价（元）<input v-model="form.normal_unit_price" type="number" min="0.0001" step="0.0001" class="form-input" data-testid="manual-price-input"></label>
            <label>生效时间<input v-model="form.valid_from" type="datetime-local" class="form-input"></label>
            <label>失效时间（可选）<input v-model="form.valid_to" type="datetime-local" class="form-input"></label>
            <label>返工倍率（可选，%）<input v-model="form.rework_rate_percent" type="number" min="0" max="100" step="0.01" class="form-input"></label>
          </div>
          <label>确认理由<textarea v-model.trim="form.confirmation_reason" rows="3" class="form-input" placeholder="说明已核对订单、路线和工序后的定价依据"></textarea></label>
          <p class="manual-help">保存后由另一位有批准权限的人员独立批准。</p>
        </div>
        <footer class="manual-editor-footer"><button type="button" class="btn btn-default" :disabled="busy" @click="closeEditor">取消</button><button type="button" class="btn btn-primary" :disabled="busy" @click="createDraft">保存人工确认草稿</button></footer>
      </section>
    </div>
  </section>
</template>

<script setup>
import { useHistoricalPriceConfirmation } from '@/composables/wage/useHistoricalPriceConfirmation.js'

const props = defineProps({ reviews: { type: Array, default: () => [] }, canPrepare: { type: Boolean, default: false }, canApprove: { type: Boolean, default: false }, loading: { type: Boolean, default: false } })
const emit = defineEmits(['refresh'])

const {
  selectedReview,
  referenceCandidate,
  editorOpen,
  busy,
  form,
  orderSummary,
  routeSummary,
  processSummary,
  emptyForm,
  commandKey,
  timestamp,
  openCreate,
  closeEditor,
  draftFor,
  unitPrice,
  formatDate,
  createDraft,
  voidDraft,
  approveDraft
} = useHistoricalPriceConfirmation(props, emit)
</script>

<style scoped>
.manual-panel{margin-bottom:16px;padding:14px;border:1px solid #f1d48b;border-radius:8px;background:#fffaf0}.manual-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.manual-heading h4{margin:0;font-size:16px}.manual-heading p{margin:5px 0 0;color:#755500;font-size:12px}.manual-count{padding:3px 8px;border-radius:12px;background:#f4d98f;color:#755500;font-size:12px}.manual-empty{padding:18px 0;color:var(--text-placeholder);font-size:13px}.manual-list{display:grid;gap:10px;margin-top:12px}.manual-card{display:flex;justify-content:space-between;gap:16px;padding:12px;border:1px solid #eedaa6;border-radius:7px;background:#fff}.manual-card-title{display:flex;align-items:baseline;gap:8px}.manual-card-title span,.manual-route,.manual-evidence{color:var(--text-placeholder);font-size:12px}.manual-route{margin-top:4px}.manual-orders{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin-top:10px}.manual-orders .label{color:var(--text-secondary);font-size:12px}.order-chip{padding:4px 7px;border-radius:4px;background:#f6f7f9;font-size:12px}.order-chip em{color:var(--primary);font-style:normal}.order-chip small{margin-left:4px;color:var(--text-placeholder)}.manual-evidence{margin-top:8px}.manual-card-side{display:flex;align-items:flex-end;flex-direction:column;gap:8px;min-width:220px}.candidate-box{display:grid;gap:4px;width:100%;color:var(--text-placeholder);font-size:11px}.candidate-button{padding:4px 6px;border:1px dashed var(--border);border-radius:4px;background:var(--bg-secondary);color:var(--primary);font-size:12px;text-align:left;cursor:pointer}.draft-status{display:grid;gap:2px;width:100%;padding:7px 9px;border-radius:5px;background:#edf7ed;color:#23723b;font-size:12px}.manual-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:6px}.manual-overlay{position:fixed;inset:0;z-index:1200;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(15,23,42,.5)}.manual-editor{width:min(680px,100%);max-height:calc(100vh - 40px);overflow:auto;border:1px solid var(--border);border-radius:8px;background:var(--bg-surface);box-shadow:var(--shadow-lg)}.manual-editor-header,.manual-editor-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 18px;border-bottom:1px solid var(--border-light)}.manual-editor-header h4{margin:0;font-size:17px}.manual-editor-header p{margin:3px 0 0;color:var(--text-placeholder);font-size:12px}.manual-editor-body{display:grid;gap:14px;padding:18px}.locked-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.locked-summary div{display:grid;gap:4px;padding:8px 10px;border-radius:5px;background:var(--bg-secondary)}.locked-summary span{color:var(--text-placeholder);font-size:11px}.manual-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.manual-editor-body label{display:grid;gap:6px;color:var(--text-secondary);font-size:13px}.reference-note{padding:8px 10px;border-left:3px solid #d59b00;background:#fff8df;color:#755500;font-size:12px}.manual-help{margin:0;color:var(--text-placeholder);font-size:12px}.manual-editor-footer{justify-content:flex-end;border-top:1px solid var(--border-light);border-bottom:0}@media(max-width:720px){.manual-card{flex-direction:column}.manual-card-side{align-items:stretch;width:100%;min-width:0}.manual-actions{justify-content:flex-start}.locked-summary,.manual-form-grid{grid-template-columns:1fr}.manual-overlay{padding:8px}}
</style>
