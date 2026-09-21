<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  node: { type: Object, default: null },
  form: { type: Object, required: true },
  loading: Boolean,
  error: { type: String, default: '' },
  saving: Boolean,
  canManage: Boolean,
  onAdd: { type: Function, required: true },
  onRemove: { type: Function, required: true },
  onSave: { type: Function, required: true },
  onRetry: { type: Function, required: true },
})

const emit = defineEmits(['dirty-change', 'saved'])
const digest = value => JSON.stringify(value || {})
const initialDigest = ref(digest(props.form))
const submitting = ref(false)
const formDisabled = computed(() => (
  props.loading || Boolean(props.error) || props.saving || submitting.value
))
const isBatch = computed(() => props.node?.capacity_mode === 'batch')
const displayValue = value => (value === null || value === undefined || value === '' ? '-' : value)
const statusLabel = value => ({ active: '启用', inactive: '停用' }[value] || displayValue(value))

watch(
  () => props.form,
  value => {
    initialDigest.value = digest(value)
    if (!submitting.value) emit('dirty-change', false)
  },
)

watch(
  () => props.form,
  value => {
    if (!submitting.value) emit('dirty-change', digest(value) !== initialDigest.value)
  },
  { deep: true },
)

async function submit() {
  if (formDisabled.value) return
  submitting.value = true
  try {
    const result = await props.onSave()
    if (!result) return
    await nextTick()
    initialDigest.value = digest(props.form)
    emit('dirty-change', false)
    emit('saved', result)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="node-capability-panel" aria-labelledby="node-capability-title">
    <header class="node-capability-panel__header">
      <div>
        <h3 id="node-capability-title">能力限制</h3>
        <p>{{ form.node_label || (node ? `${node.node_code || ''} ${node.node_name || ''}`.trim() : '请选择生产节点') }}</p>
      </div>
      <button
        v-if="canManage"
        data-test="capability-add"
        type="button"
        class="btn btn-default"
        :disabled="formDisabled"
        @click="onAdd"
      >
        添加能力
      </button>
    </header>

    <div v-if="!node" class="node-capability-panel__notice">请选择生产节点查看能力限制</div>
    <template v-else>
      <div v-if="error" class="node-capability-panel__notice node-capability-panel__notice--error" role="alert">
        <span>{{ error }}</span>
        <button
          data-test="capability-retry"
          type="button"
          class="btn btn-default"
          :disabled="loading || saving || submitting"
          @click="onRetry"
        >
          重试
        </button>
      </div>
      <div v-else-if="loading" class="node-capability-panel__notice" role="status">正在加载节点能力…</div>

      <form v-if="canManage" class="node-capability-panel__form" @submit.prevent="submit">
      <fieldset data-test="capability-fields" class="node-capability-panel__fields" :disabled="formDisabled">
        <div v-if="!form.capabilities.length" class="node-capability-panel__empty">
          暂无能力限制，可添加第一条能力。
        </div>
        <article
          v-for="(capability, index) in form.capabilities"
          :key="index"
          class="capability-row"
          data-test="capability-row"
        >
          <label>
            <span>产品 ID</span>
            <input v-model.number="capability.product_id" data-test="capability-product-id" type="number" min="1" class="form-input">
          </label>
          <label>
            <span>产品族</span>
            <input v-model="capability.product_family" data-test="capability-product-family" class="form-input">
          </label>
          <label>
            <span>物料编码</span>
            <input v-model="capability.material_code" data-test="capability-material-code" class="form-input">
          </label>
          <label>
            <span>规格</span>
            <input v-model="capability.specification" data-test="capability-specification" class="form-input">
          </label>
          <label>
            <span>工艺路线版本 ID</span>
            <input v-model.number="capability.route_version_id" data-test="capability-route-version-id" type="number" min="1" class="form-input">
          </label>
          <label>
            <span>工序版本 ID</span>
            <input v-model.number="capability.process_version_id" data-test="capability-process-version-id" type="number" min="1" class="form-input">
          </label>
          <template v-if="isBatch">
            <label>
              <span>最大批量</span>
              <input v-model.number="capability.max_batch_quantity" data-test="max-batch-quantity" type="number" min="1" class="form-input">
            </label>
            <label>
              <span>批处理分钟</span>
              <input v-model.number="capability.batch_minutes" data-test="batch-minutes" type="number" min="0.01" step="0.01" class="form-input">
            </label>
            <label>
              <span>换型分钟</span>
              <input v-model.number="capability.changeover_minutes" data-test="changeover-minutes" type="number" min="0" step="0.01" class="form-input">
            </label>
            <label class="node-capability-panel__checkbox">
              <input v-model="capability.allow_mixed_orders" data-test="allow-mixed-orders" type="checkbox">
              <span>允许混单</span>
            </label>
          </template>
          <label>
            <span>状态</span>
            <select v-model="capability.status" data-test="capability-status" class="form-input">
              <option value="active">启用</option>
              <option value="inactive">停用</option>
            </select>
          </label>
          <div class="node-capability-panel__row-actions">
            <button
              data-test="capability-remove"
              type="button"
              class="btn btn-danger"
              @click="onRemove(index)"
            >
              移除
            </button>
          </div>
        </article>

        <label class="node-capability-panel__wide">
          <span>变更原因</span>
          <textarea v-model="form.reason" data-test="capability-reason" class="form-input" rows="3" required />
        </label>
        <label class="node-capability-panel__wide">
          <span>幂等键</span>
          <input v-model="form.idempotency_key" data-test="capability-idempotency-key" class="form-input" required>
        </label>
        <div class="node-capability-panel__actions">
          <button data-test="capability-save" type="submit" class="btn btn-primary">
            {{ saving || submitting ? '正在保存…' : '保存能力限制' }}
          </button>
        </div>
      </fieldset>
      </form>

      <section v-else class="node-capability-panel__readonly" aria-label="节点能力摘要">
        <div v-if="!form.capabilities.length" class="node-capability-panel__empty">暂无能力限制。</div>
        <article
          v-for="(capability, index) in form.capabilities"
          :key="index"
          class="capability-row node-capability-panel__readonly-row"
          data-test="capability-row"
        >
          <dl>
            <div><dt>产品 ID</dt><dd>{{ displayValue(capability.product_id) }}</dd></div>
            <div><dt>产品族</dt><dd>{{ displayValue(capability.product_family) }}</dd></div>
            <div><dt>物料编码</dt><dd>{{ displayValue(capability.material_code) }}</dd></div>
            <div><dt>规格</dt><dd>{{ displayValue(capability.specification) }}</dd></div>
            <div><dt>工艺路线版本 ID</dt><dd>{{ displayValue(capability.route_version_id) }}</dd></div>
            <div><dt>工序版本 ID</dt><dd>{{ displayValue(capability.process_version_id) }}</dd></div>
            <template v-if="isBatch">
              <div><dt>最大批量</dt><dd>{{ displayValue(capability.max_batch_quantity) }}</dd></div>
              <div><dt>批处理分钟</dt><dd>{{ displayValue(capability.batch_minutes) }}</dd></div>
              <div><dt>换型分钟</dt><dd>{{ displayValue(capability.changeover_minutes) }}</dd></div>
              <div><dt>允许混单</dt><dd>{{ capability.allow_mixed_orders ? '是' : '否' }}</dd></div>
            </template>
            <div><dt>状态</dt><dd>{{ statusLabel(capability.status) }}</dd></div>
          </dl>
        </article>
      </section>
    </template>
  </section>
</template>

<style scoped>
.node-capability-panel {
  max-width: 1080px;
  margin: 0 auto;
}

.node-capability-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
}

.node-capability-panel__header h3,
.node-capability-panel__header p {
  margin: 0;
}

.node-capability-panel__header p {
  margin-top: 6px;
  color: var(--text-secondary);
}

.node-capability-panel__notice {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 64px;
  margin-bottom: 16px;
  color: var(--text-placeholder);
  text-align: center;
}

.node-capability-panel__notice--error {
  color: var(--danger);
}

.node-capability-panel__fields {
  display: grid;
  gap: 16px;
  min-width: 0;
  padding: 0;
  border: 0;
}

.node-capability-panel__readonly {
  display: grid;
  gap: 16px;
}

.node-capability-panel__readonly-row dl {
  display: contents;
}

.node-capability-panel__readonly-row dl > div {
  min-width: 0;
}

.node-capability-panel__readonly-row dt {
  color: var(--text-placeholder);
  font-size: 12px;
}

.node-capability-panel__readonly-row dd {
  margin: 6px 0 0;
  color: var(--text-primary);
  overflow-wrap: anywhere;
}

.capability-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(160px, 1fr));
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
}

.capability-row label,
.node-capability-panel__wide {
  display: grid;
  gap: 7px;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.capability-row .node-capability-panel__checkbox {
  display: flex;
  align-items: center;
  align-self: end;
  min-height: 38px;
}

.node-capability-panel__row-actions {
  display: flex;
  align-items: end;
  justify-content: flex-end;
}

.node-capability-panel__empty {
  padding: 24px;
  border: 1px dashed var(--border-light);
  border-radius: var(--radius-md);
  color: var(--text-placeholder);
  text-align: center;
}

.node-capability-panel__actions {
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 899px) {
  .node-capability-panel__header {
    align-items: flex-start;
  }

  .capability-row {
    grid-template-columns: 1fr;
  }
}
</style>
