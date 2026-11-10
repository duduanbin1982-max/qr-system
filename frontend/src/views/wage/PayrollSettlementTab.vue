<template>
  <section class="settlement-page" data-testid="payroll-settlement-page">
    <header class="settlement-toolbar">
      <div>
        <h3>导出对账</h3>
        <p>管理已确认工资批次的支付清单、回执、差异与结账状态。</p>
      </div>
      <div class="settlement-toolbar-actions">
        <label class="settlement-month-label">
          工资月份
          <input v-model="month" class="form-input" type="month" @change="load">
        </label>
        <button class="btn-default btn-sm" :disabled="loading || working" @click="load">刷新</button>
      </div>
    </header>

    <p class="settlement-boundary-note">
      此处只生成支付清单并登记财务回执，不会连接银行或发起付款。旧批次导出仅供预览。
    </p>

    <div class="settlement-layout">
      <aside class="settlement-batch-list" aria-label="已确认工资批次">
        <h4>已确认批次</h4>
        <p v-if="loading" class="settlement-empty">正在加载批次...</p>
        <p v-else-if="!availableBatches.length" class="settlement-empty">
          当前月份没有可结算的已确认批次。
        </p>
        <button
          v-for="batch in availableBatches"
          :key="batch.id"
          class="settlement-batch-option"
          :class="{ selected: selectedBatchId === batch.id }"
          :aria-pressed="selectedBatchId === batch.id"
          @click="selectBatch(batch)"
        >
          <span>
            <strong>{{ batch.payroll_month }} / V{{ batch.version }}</strong>
            <small>{{ batch.prepared_by_name || batch.prepared_user_name || '制单人未记录' }}</small>
          </span>
          <strong>{{ money(batch.payable_wage_cents) }}</strong>
        </button>
      </aside>

      <div class="settlement-detail">
        <p v-if="!selectedBatch" class="settlement-empty" data-testid="settlement-no-batch">
          选择一个已确认批次查看结算进度。
        </p>
        <p v-else-if="detailLoading" class="settlement-empty">正在加载结算信息...</p>
        <template v-else-if="settlement">
          <header class="settlement-detail-header">
            <div>
              <h4>{{ selectedBatch.payroll_month }} / V{{ selectedBatch.version }}</h4>
              <p>应付 {{ money(settlement.expected_total_cents ?? selectedBatch.payable_wage_cents) }}</p>
            </div>
            <span class="settlement-status" :class="`status-${settlement.status}`">
              {{ settlementStatusLabel(settlement.status) }}
            </span>
          </header>

          <div class="settlement-totals" aria-label="对账汇总">
            <div><span>应付合计</span><strong>{{ money(settlement.expected_total_cents ?? selectedBatch.payable_wage_cents) }}</strong></div>
            <div><span>成功支付</span><strong>{{ money(settlement.successful_paid_cents) }}</strong></div>
            <div><span>差额</span><strong :class="{ 'text-warning': Number(settlement.difference_cents || 0) !== 0 }">{{ money(settlement.difference_cents) }}</strong></div>
            <div><span>阻断差异</span><strong :class="{ 'text-warning': Number(settlement.blocking_difference_count || 0) > 0 }">{{ settlement.blocking_difference_count || 0 }}</strong></div>
          </div>

          <section class="settlement-section" aria-labelledby="payment-list-title">
            <div class="settlement-section-heading">
              <div>
                <h5 id="payment-list-title">正式支付清单</h5>
                <p v-if="currentExport">
                  V{{ currentExport.export_version }} · {{ currentExport.row_count }} 人 ·
                  {{ currentExport.created_at || '生成时间未知' }}
                </p>
                <p v-else>尚未为此工资批次生成支付清单。</p>
              </div>
              <div class="settlement-actions">
                <a
                  v-if="currentExport && canExport"
                  class="btn-default btn-sm"
                  :href="downloadUrl(currentExport.id)"
                  target="_blank"
                  rel="noopener"
                  data-testid="download-payment-list"
                >下载清单</a>
                <button
                  v-if="canExport && canCreateExport"
                  class="btn-primary btn-sm"
                  :disabled="working"
                  data-testid="create-payment-list"
                  @click="createExport"
                >{{ currentExport ? '生成新版本' : '生成支付清单' }}</button>
              </div>
            </div>
            <p v-if="currentExport" class="settlement-digest">
              文件 SHA-256：<code>{{ currentExport.content_sha256 }}</code>
            </p>
            <p v-if="currentExport && receiptBatches.length" class="settlement-inline-note">
              当前清单已有回执，不能替换版本。
            </p>
          </section>

          <section class="settlement-section" aria-labelledby="receipt-title">
            <div class="settlement-section-heading">
              <div>
                <h5 id="receipt-title">财务支付回执</h5>
                <p>接受 UTF-8 CSV；每个文件最多 2 MB、10,000 行。</p>
              </div>
            </div>
            <div v-if="canUploadReceipt" class="settlement-upload-row">
              <input
                aria-label="支付回执 CSV 文件"
                type="file"
                accept=".csv,text/csv"
                :disabled="working"
                data-testid="receipt-file"
                @change="setReceiptFile($event.target.files?.[0])"
              >
              <span v-if="receiptFile" class="settlement-file-name">{{ receiptFile.name }}</span>
              <button
                class="btn-primary btn-sm"
                :disabled="working || !receiptFile || !currentExport"
                data-testid="upload-receipt"
                @click="uploadReceipt"
              >上传回执</button>
            </div>
            <p v-else-if="!currentExport" class="settlement-inline-note">先生成支付清单，再上传对应回执。</p>
            <p v-else-if="settlement.status === 'closed'" class="settlement-inline-note">结账后回执已锁定，不可继续上传。</p>

            <div v-if="receiptBatches.length" class="settlement-receipt-list">
              <div v-for="receipt in receiptBatches" :key="receipt.id" class="settlement-receipt-row">
                <div>
                  <strong>{{ receipt.source_filename }}</strong>
                  <small>{{ receipt.uploaded_at || receipt.created_at || '上传时间未知' }} · SHA-256 {{ receipt.content_sha256 }}</small>
                </div>
                <span>{{ receipt.accepted_row_count }} 行有效 / {{ receipt.failed_row_count }} 行无效</span>
                <span class="settlement-receipt-status">{{ receipt.status === 'accepted' ? '已接收' : '需检查' }}</span>
                <ul v-if="receipt.invalid_items?.length" class="settlement-invalid-rows">
                  <li v-for="item in receipt.invalid_items" :key="item.id">
                    第 {{ item.row_number }} 行{{ item.payment_reference ? ` · ${item.payment_reference}` : '' }}：{{ item.validation_error }}
                  </li>
                </ul>
                <p v-if="receipt.failed_row_count > receipt.invalid_items?.length" class="settlement-inline-note">
                  另有无效行未展开显示。
                </p>
              </div>
            </div>
            <p v-else class="settlement-empty-inline">尚无支付回执。</p>
          </section>

          <section class="settlement-section" aria-labelledby="reconcile-title">
            <div class="settlement-section-heading">
              <div>
                <h5 id="reconcile-title">差异对账</h5>
                <p v-if="latestReconciliation">
                  第 {{ latestReconciliation.run_version }} 次对账 ·
                  {{ latestReconciliation.executed_at || '运行时间未知' }} ·
                  {{ latestReconciliation.status === 'reconciled' ? '金额一致' : `${latestReconciliation.blocking_count} 项待处理` }}
                </p>
                <p v-else>上传回执后运行对账；每次运行都会保留独立结果。</p>
              </div>
              <button
                v-if="canReconcile"
                class="btn-default btn-sm"
                :disabled="working || !canRunReconciliation"
                data-testid="run-reconciliation"
                @click="reconcile"
              >重新运行对账</button>
            </div>

            <p v-if="latestReconciliation && !latestReconciliation.items?.length" class="settlement-success-note">
              当前回执与应付金额一致，可以进入结账审核。
            </p>
            <div v-else-if="latestReconciliation?.items?.length" class="settlement-differences">
              <article
                v-for="item in latestReconciliation.items"
                :key="item.id"
                class="settlement-difference-row"
                :data-testid="`settlement-difference-${item.id}`"
              >
                <div class="settlement-difference-main">
                  <strong>{{ differenceTypeLabel(item.difference_type) }}</strong>
                  <small>{{ item.payment_reference || '无支付引用' }} · {{ item.blocking ? '阻断结账' : '提示' }}</small>
                  <small v-if="differenceFor(item).validation_error">{{ differenceFor(item).validation_error }}</small>
                </div>
                <div class="settlement-difference-amounts">
                  <span>应付 {{ money(item.expected_cents) }}</span>
                  <span>成功支付 {{ money(item.successful_paid_cents) }}</span>
                  <strong>差额 {{ money(item.difference_cents) }}</strong>
                </div>
                <div v-if="canResolveDifference(item)" class="settlement-resolution-form">
                  <input
                    v-model="resolutionReasons[item.id]"
                    class="form-input"
                    :aria-label="`差异 ${item.id} 处理原因`"
                    placeholder="填写处理原因"
                    maxlength="500"
                  >
                  <button
                    class="btn-default btn-sm"
                    :disabled="working || !resolutionReasons[item.id]?.trim()"
                    @click="resolveDifference(item, resolutionReasons[item.id])"
                  >记录处理</button>
                </div>
              </article>
            </div>
            <p v-else-if="receiptBatches.length && !latestReconciliation" class="settlement-inline-note">
              已收到回执，运行对账后才能查看差异或结账。
            </p>
          </section>

          <footer v-if="canClose || settlement.status === 'closed'" class="settlement-close-row">
            <div>
              <strong>{{ settlement.status === 'closed' ? '结算已锁定' : '结账锁定' }}</strong>
              <p v-if="settlement.status === 'closed'">本批次的回执、对账结果和结账记录已归档。</p>
              <p v-else>仅当最新对账完全通过后，才可锁定本次结算。</p>
            </div>
            <button
              v-if="canClose"
              class="btn-primary btn-sm"
              :disabled="working"
              data-testid="close-settlement"
              @click="closeSettlement"
            >结账锁定</button>
          </footer>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup>
import { usePayrollSettlement, settlementStatusLabel } from '@/composables/wage/usePayrollSettlement.js'

const {
  month,
  availableBatches,
  selectedBatch,
  selectedBatchId,
  settlement,
  currentExport,
  receiptBatches,
  latestReconciliation,
  loading,
  detailLoading,
  working,
  receiptFile,
  resolutionReasons,
  canExport,
  canReconcile,
  canUploadReceipt,
  canCreateExport,
  canRunReconciliation,
  canClose,
  money,
  load,
  selectBatch,
  setReceiptFile,
  createExport,
  uploadReceipt,
  reconcile,
  differenceFor,
  differenceTypeLabel,
  canResolveDifference,
  resolveDifference,
  closeSettlement,
  downloadUrl,
} = usePayrollSettlement()
</script>

<style scoped>
.settlement-page{min-width:0}.settlement-toolbar,.settlement-detail-header,.settlement-section-heading,.settlement-close-row{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.settlement-toolbar{margin-bottom:12px}.settlement-toolbar h3,.settlement-detail-header h4{margin:0;font-size:18px}.settlement-toolbar p,.settlement-detail-header p,.settlement-section-heading p,.settlement-close-row p{margin:4px 0 0;color:var(--text-placeholder);font-size:12px}.settlement-toolbar-actions{display:flex;align-items:flex-end;gap:8px}.settlement-month-label{display:grid;gap:4px;color:var(--text-secondary);font-size:12px}.settlement-month-label .form-input{width:160px}.settlement-boundary-note{padding:9px 12px;margin:0 0 12px;border-left:3px solid var(--primary);background:var(--bg-secondary);font-size:13px}.settlement-layout{display:grid;grid-template-columns:minmax(230px,290px) minmax(0,1fr);border-top:1px solid var(--border-light);border-bottom:1px solid var(--border-light)}.settlement-batch-list{min-width:0;padding:14px 12px 14px 0;border-right:1px solid var(--border-light)}.settlement-batch-list h4,.settlement-section h5{margin:0;font-size:14px}.settlement-batch-option{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;min-height:58px;padding:9px 10px;margin-top:6px;border:1px solid transparent;border-radius:6px;background:transparent;color:var(--text-primary);text-align:left;cursor:pointer}.settlement-batch-option:hover{background:var(--bg-secondary)}.settlement-batch-option.selected{border-color:var(--primary);background:var(--primary-light)}.settlement-batch-option span{display:grid;gap:4px;min-width:0}.settlement-batch-option strong{font-size:13px}.settlement-batch-option small,.settlement-receipt-row small,.settlement-difference-main small{display:block;color:var(--text-placeholder);font-size:11px;overflow-wrap:anywhere}.settlement-detail{min-width:0;padding:14px 0 14px 16px}.settlement-detail-header{align-items:center;padding-bottom:12px;border-bottom:1px solid var(--border-light)}.settlement-status,.settlement-receipt-status{flex:none;padding:4px 8px;border-radius:4px;background:var(--bg-secondary);font-size:12px}.status-reconciled{background:var(--success-light);color:var(--success)}.status-difference_pending{background:var(--warning-lighter);color:var(--warning-dark)}.status-closed{background:var(--text-secondary);color:var(--bg-primary)}.settlement-totals{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-bottom:1px solid var(--border-light)}.settlement-totals div{min-width:0;padding:11px 10px;border-right:1px solid var(--border-light)}.settlement-totals div:last-child{border-right:0}.settlement-totals span{display:block;color:var(--text-placeholder);font-size:11px}.settlement-totals strong{display:block;margin-top:4px;font-size:16px;overflow-wrap:anywhere}.settlement-section{padding:14px 0;border-bottom:1px solid var(--border-light)}.settlement-section-heading{align-items:center}.settlement-actions,.settlement-upload-row,.settlement-resolution-form{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.settlement-digest{margin:8px 0 0;color:var(--text-placeholder);font-size:11px;overflow-wrap:anywhere}.settlement-digest code{word-break:break-all}.settlement-inline-note,.settlement-empty-inline{margin:8px 0 0;color:var(--text-placeholder);font-size:12px}.settlement-upload-row{margin-top:12px}.settlement-upload-row input[type=file]{max-width:min(100%,380px);font-size:12px}.settlement-file-name{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.settlement-receipt-list{margin-top:10px}.settlement-receipt-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px 12px;align-items:start;padding:10px 0;border-top:1px solid var(--border-light);font-size:12px}.settlement-receipt-row>div{min-width:0}.settlement-receipt-row>div strong{overflow-wrap:anywhere}.settlement-invalid-rows{grid-column:1/-1;margin:0;padding:8px 10px 8px 26px;background:var(--warning-lighter);font-size:12px}.settlement-success-note{padding:10px 12px;margin:10px 0 0;background:var(--success-light);color:var(--success);font-size:13px}.settlement-differences{margin-top:8px}.settlement-difference-row{display:grid;grid-template-columns:minmax(150px,1fr) minmax(170px,auto);gap:10px 16px;padding:12px 0;border-top:1px solid var(--border-light)}.settlement-difference-main{display:grid;gap:4px;min-width:0}.settlement-difference-main strong{font-size:13px}.settlement-difference-amounts{display:grid;gap:3px;text-align:right;font-size:12px}.settlement-resolution-form{grid-column:1/-1}.settlement-resolution-form .form-input{flex:1 1 220px;min-width:0}.settlement-close-row{align-items:center;padding-top:14px}.settlement-empty{text-align:center;padding:24px 8px;color:var(--text-placeholder);font-size:13px}.text-warning{color:var(--warning-dark)}@media(max-width:900px){.settlement-layout{grid-template-columns:minmax(0,1fr)}.settlement-batch-list{padding:12px 0;border-right:0;border-bottom:1px solid var(--border-light)}.settlement-batch-option{display:inline-flex;width:min(100%,360px);vertical-align:top;margin-right:6px}.settlement-detail{padding:14px 0}}@media(max-width:600px){.settlement-toolbar,.settlement-detail-header,.settlement-section-heading,.settlement-close-row{flex-direction:column}.settlement-toolbar-actions{width:100%;align-items:flex-end}.settlement-month-label{flex:1}.settlement-month-label .form-input{width:100%}.settlement-totals{grid-template-columns:repeat(2,minmax(0,1fr))}.settlement-totals div:nth-child(2){border-right:0}.settlement-totals div:nth-child(-n+2){border-bottom:1px solid var(--border-light)}.settlement-receipt-row{grid-template-columns:minmax(0,1fr) auto}.settlement-receipt-status{grid-column:2;grid-row:1}.settlement-difference-row{grid-template-columns:minmax(0,1fr)}.settlement-difference-amounts{text-align:left}.settlement-section-heading .settlement-actions{width:100%}.settlement-upload-row{align-items:flex-start;flex-direction:column}.settlement-invalid-rows{grid-column:1/-1}}
</style>
