<template>
  <div v-if="open" class="editor-overlay" @click.self="closeEditor">
    <section
      class="price-editor"
      role="dialog"
      aria-modal="true"
      aria-labelledby="price-editor-title"
      data-testid="price-version-editor"
    >
      <header class="editor-header">
        <div>
          <h3 id="price-editor-title">{{ draftPrice ? '工价草稿' : '建立精确工价' }}</h3>
          <p>路线 V{{ reference?.route_version }} / 工序 V{{ reference?.process_version }}</p>
        </div>
        <button type="button" class="icon-button" title="关闭" aria-label="关闭" @click="closeEditor">×</button>
      </header>

      <div v-if="isPending" class="group-release-notice">
        本工价绑定待发布路线，不能单独批准，只能随路线成组发布。
      </div>

      <div class="editor-body">
        <div class="locked-grid">
          <label>路线版本
            <input
              :value="`${reference?.route_name || '-'} · V${reference?.route_version || '-'}`"
              class="form-input"
              data-testid="locked-route"
              disabled
            >
          </label>
          <label>工序版本
            <input
              :value="`${reference?.process_name || '-'} · V${reference?.process_version || '-'}`"
              class="form-input"
              data-testid="locked-process"
              disabled
            >
          </label>
        </div>

        <div v-if="currentPrice" class="current-price-strip">
          <span>当前正常工价</span>
          <strong>{{ unitPrice(currentPrice.normal_unit_price_micros) }}</strong>
          <span>{{ formatDateTime(currentPrice.valid_from) }} 起</span>
        </div>

        <div class="form-grid">
          <label>正常工价（元）
            <input
              v-model="form.normal_unit_price"
              type="number"
              min="0.0001"
              step="0.0001"
              class="form-input"
              data-testid="price-unit-input"
              :disabled="Boolean(draftPrice)"
            >
          </label>
          <label>生效时间
            <input
              v-model="form.valid_from"
              type="datetime-local"
              class="form-input"
              :disabled="Boolean(draftPrice)"
            >
          </label>
        </div>

        <label class="toggle-row">
          <input
            v-model="form.rework_rate_configured"
            type="checkbox"
            :disabled="Boolean(draftPrice)"
          >
          <span>设置返工倍率</span>
        </label>
        <label v-if="form.rework_rate_configured">返工倍率（%）
          <input
            v-model="form.rework_rate_percent"
            type="number"
            min="0"
            max="100"
            step="0.01"
            class="form-input narrow-input"
            :disabled="Boolean(draftPrice)"
          >
        </label>
        <label>定价依据
          <textarea
            v-model="form.remark"
            rows="3"
            class="form-input"
            data-testid="price-remark-input"
            :disabled="Boolean(draftPrice)"
          />
        </label>

        <div v-if="currentPrice && form.normal_unit_price" class="change-preview">
          <span>价格变化</span>
          <strong>{{ unitPrice(currentPrice.normal_unit_price_micros) }} → {{ inputPrice }}</strong>
          <span :class="changeClass">{{ changeText }}</span>
        </div>

        <label v-if="draftPrice" class="void-field">作废原因
          <input
            v-model.trim="voidReason"
            class="form-input"
            data-testid="void-reason-input"
            placeholder="说明错误原因或路线调整依据"
          >
        </label>
      </div>

      <footer class="editor-footer">
        <button type="button" class="btn btn-default" :disabled="busy" @click="closeEditor">取消</button>
        <button
          v-if="draftPrice"
          type="button"
          class="btn btn-danger"
          data-testid="void-price-draft"
          :disabled="busy"
          @click="submitVoid"
        >作废草稿</button>
        <button
          v-else
          type="button"
          class="btn btn-primary"
          data-testid="save-price-draft"
          :disabled="busy"
          @click="submitCreate"
        >保存草稿</button>
      </footer>
    </section>
  </div>
</template>

<script setup>
import { usePriceVersionEditor } from '@/composables/wage/usePriceVersionEditor.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  reference: { type: Object, default: null },
  currentPrice: { type: Object, default: null },
  draftPrice: { type: Object, default: null },
})
const emit = defineEmits(['created', 'voided', 'close'])

const {
  busy,
  createDraft,
  voidDraft,
  voidReason,
  form,
  isPending,
  inputMicros,
  inputPrice,
  priceDifference,
  changeText,
  changeClass,
  localNow,
  emptyForm,
  reset,
  unitPrice,
  formatDateTime,
  closeEditor,
  submitCreate,
  submitVoid
} = usePriceVersionEditor(props, emit)
</script>

<style scoped>
.editor-overlay{position:fixed;inset:0;z-index:1200;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(15,23,42,.5)}
.price-editor{width:min(680px,100%);max-height:calc(100vh - 40px);overflow:auto;border:1px solid var(--border);border-radius:8px;background:var(--bg-surface);box-shadow:var(--shadow-lg)}
.editor-header,.editor-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 18px;border-bottom:1px solid var(--border-light)}
.editor-header h3{margin:0;font-size:17px}.editor-header p{margin:3px 0 0;color:var(--text-placeholder);font-size:12px}.icon-button{width:32px;height:32px;border:0;background:transparent;color:var(--text-secondary);font-size:24px;cursor:pointer}.group-release-notice{padding:10px 18px;border-bottom:1px solid #f2d58a;background:#fff8df;color:#755500;font-size:13px}.editor-body{display:grid;gap:14px;padding:18px}.locked-grid,.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.editor-body label{display:grid;gap:6px;color:var(--text-secondary);font-size:13px}.current-price-strip,.change-preview{display:flex;align-items:center;gap:14px;padding:10px 12px;border-left:3px solid var(--primary);background:var(--bg-secondary);font-size:13px}.current-price-strip span:last-child{margin-left:auto;color:var(--text-placeholder)}.toggle-row{display:flex!important;align-items:center;grid-template-columns:none!important}.narrow-input{max-width:220px}.void-field{padding-top:12px;border-top:1px solid var(--border-light)}.change-up{color:var(--danger)}.change-down{color:var(--success)}.editor-footer{justify-content:flex-end;border-top:1px solid var(--border-light);border-bottom:0}.btn-danger{background:var(--danger);color:#fff}
@media(max-width:640px){.editor-overlay{padding:8px}.locked-grid,.form-grid{grid-template-columns:1fr}.editor-header,.editor-body,.editor-footer{padding-left:12px;padding-right:12px}.current-price-strip,.change-preview{align-items:flex-start;flex-direction:column;gap:4px}.current-price-strip span:last-child{margin-left:0}}
</style>
