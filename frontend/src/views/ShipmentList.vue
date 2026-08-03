<!-- ShipmentList.vue -->
<template>
<div style="padding:var(--space-6)">
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">🚚</span><div><div class="s-val">{{ total }}</div><div class="s-label">出库单总数</div></div></div>
      <div class="summary-item"><span class="s-icon">⏳</span><div><div class="s-val" style="color:var(--warning)">{{ pendingCount }}</div><div class="s-label">待出库</div></div></div>
      <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-success">{{ completedCount }}</div><div class="s-label">已出库</div></div></div>
      <div class="summary-item"><span class="s-icon">💰</span><div><div class="s-val">{{ receivableTotal.toFixed(0) }}</div><div class="s-label">应收总额</div></div></div>
      <div class="summary-item"><span class="s-icon">💵</span><div><div class="s-val" style="color:var(--success)">{{ paidTotal.toFixed(0) }}</div><div class="s-label">已收总额</div></div></div>
      <div class="summary-item"><span class="s-icon">📋</span><div><div class="s-val" style="color:var(--danger)">{{ unpaidTotal.toFixed(0) }}</div><div class="s-label">未收总额</div></div></div>
    </div>

    <div class="card">
      <div class="card-header">
        <h3>🚚 发货管理</h3>
        <div style="display:flex;gap:var(--space-2);align-items:center">
          <select class="form-input" v-model="filterStatus" @change="page=1;load()" style="border:1px solid var(--border);border-radius:var(--radius-md);padding:var(--space-2) 12px;font-size:var(--text-base);background:white;cursor:pointer;width:100px">
            <option value="">全部</option>
            <option value="pending">待出库</option>
            <option value="completed">已出库</option>
            <option value="received">已签收</option>
            <option value="cancelled">已取消</option>
            <option value="reversed">已冲销</option>
          </select>
          <div class="search-box" style="background:var(--bg-hover);border-radius:var(--radius-md);display:flex;align-items:center;padding:0 10px">
            <span>🔍</span>
            <input class="form-input" v-model="searchKeyword" placeholder="搜索单号/客户..." @keyup.enter="load" style="border:none;background:transparent;outline:none;padding:var(--space-2) 6px;font-size:var(--text-base);width:160px;box-shadow:none">
          </div>
          <button class="btn btn-default btn-sm" @click="load">搜索</button>
          <button class="btn btn-default btn-sm" @click="exportExcel" style="font-size:var(--text-xs)">📥导出Excel</button>
          <button v-if="canCreate" class="btn btn-primary btn-sm" @click="openAdd">+ 新建出库单</button>
        </div>
      </div>
      <div class="card-body">
        <div class="table-wrap">
          <table v-if="shipments.length" class="data-table shipment-table">
            <colgroup>
              <col class="col-expand">
              <col class="col-shipment-no">
              <col class="col-customer">
              <col class="col-product-code">
              <col class="col-contact">
              <col class="col-count">
              <col class="col-qty">
              <col class="col-status">
              <col class="col-logistics">
              <col class="col-money">
              <col class="col-money">
              <col class="col-pay-status">
              <col class="col-actions">
            </colgroup>
            <thead>
              <tr>
                <th></th>
                <th>出库单号</th>
                <th>客户</th>
                <th>产品编码</th>
                <th>联系人</th>
                <th class="center-cell">物品数</th>
                <th class="center-cell">总量</th>
                <th class="center-cell nowrap-cell">状态</th>
                <th>物流单号</th>
                <th class="center-cell">应收</th>
                <th class="center-cell">已收</th>
                <th class="pay-status-th">收款状态</th>
                <th class="operation-th">操作</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="s in shipments" :key="s.id">
                <tr @click="viewDetail(s)" style="cursor:pointer">
                  <td class="expand-cell">▶</td>
                  <td class="shipment-no-cell"><code>{{ s.shipment_no }}</code></td>
                  <td class="customer-cell ellipsis-cell" :title="s.customer || ''">{{ s.customer || '-' }}</td>
                  <td class="product-code-cell" :title="s.product_codes || ''"><code>{{ s.product_codes || '-' }}</code></td>
                  <td class="ellipsis-cell" :title="s.contact_person || ''">{{ s.contact_person || '-' }}</td>
                  <td class="center-cell">{{ s.item_count || 0 }}</td>
                  <td class="center-cell strong-cell">{{ s.total_quantity }}</td>
                  <td class="center-cell"><span class="badge" :class="statusMap[s.status]?.cls||'badge-info'" style="font-size:var(--text-xs-alt)">{{ statusMap[s.status]?.label||s.status }}</span></td>
                  <td class="logistics-cell" :title="[s.tracking_no, s.logistics_company].filter(Boolean).join(' / ')">{{ s.tracking_no || '-' }}<span v-if="s.logistics_company" style="color:var(--text-muted)"> / {{ s.logistics_company }}</span></td>
                  <td class="center-cell">{{ s.receivable_amount || '-' }}</td>
                  <td class="center-cell strong-cell" :style="{color: (s.paid_amount||0) >= (s.receivable_amount||0) ? 'var(--success)' : 'inherit'}">{{ s.paid_amount || '-' }}</td>
                  <td class="pay-status-td"><span class="badge" :class="paymentStatusMap[s.payment_status]?.cls||'badge-info'" style="font-size:var(--text-xs-alt);white-space:nowrap">{{ paymentStatusMap[s.payment_status]?.label||s.payment_status||'未收款' }}</span></td>
                  <td class="operation-cell">
                    <div class="o-actions shipment-actions" @click.stop>
                      <button v-if="s.status==='pending'&&canComplete" class="btn btn-success btn-sm" @click="doComplete(s)">完成</button>
                      <button v-if="s.status==='completed'&&canReceive" class="btn btn-primary btn-sm" @click="openReceive(s)">签收</button>
                      <button v-if="(s.status==='completed'||s.status==='received')&&s.payment_status!=='paid'&&canFinance" class="btn btn-warning btn-sm" @click="openPayment(s, 'receipt')">收款</button>
                      <button v-if="(s.status==='completed'||s.status==='received')&&(s.paid_amount||0)>0&&canFinance" class="btn btn-default btn-sm" @click="openPayment(s, 'refund')">退款</button>
                      <span v-if="(s.status==='pending'||s.status==='completed')&&canLogistics" class="o-abtn o-edit" @click="openLogistics(s)" title="物流信息">🚚</span>
                      <span v-if="s.status==='pending'&&canEdit" class="o-abtn o-edit" @click="openEdit(s)" title="编辑">✏️</span>
                      <span v-if="['pending','completed','received'].includes(s.status)&&canCancel" class="o-abtn o-del" @click="openCancel(s)" :title="s.status==='pending'?'取消':'冲销'">↩</span>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
          <div v-else class="empty"><div class="empty-icon">🚚</div><div class="empty-text">暂无出库单</div></div>
        </div>
        <div v-if="total > limit" style="display:flex;justify-content:center;align-items:center;gap:var(--space-3);padding:var(--space-4) 0">
          <button class="btn btn-default btn-sm" @click="prevPage" :disabled="page <= 1">上一页</button>
          <span style="font-size:var(--text-sm);color:var(--text-placeholder)">第 {{ page }} / {{ Math.ceil(total/limit) }} 页，共 {{ total }} 条</span>
          <button class="btn btn-default btn-sm" @click="nextPage" :disabled="page * limit >= total">下一页</button>
        </div>
      </div>
    </div>

    <!-- 新增模态框 -->
    <div v-if="showModal && !modalEdit" class="modal-overlay" >
      <div class="modal" style="max-width:650px">
        <div class="modal-header"><span>新建出库单</span><span class="modal-close" @click="showModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-col" style="flex:2"><div class="form-group"><label>出库单号</label><input class="form-input" v-model="form.shipment_no" placeholder="自动生成" disabled></div></div>
          </div>
          <div class="form-row">
            <div class="form-col" style="flex:1"><div class="form-group"><label>物料单号</label><input class="form-input" v-model="form.material_bill_no" placeholder="选填"></div></div>
          </div>
          <div class="form-row">
            <div class="form-col"><div class="form-group"><label>客户</label><input class="form-input" v-model="form.customer" placeholder="客户名称"></div></div>
            <div class="form-col"><div class="form-group"><label>联系人</label><input class="form-input" v-model="form.contact_person" placeholder="联系人"></div></div>
            <div class="form-col"><div class="form-group"><label>电话</label><input class="form-input" v-model="form.contact_phone" placeholder="联系电话"></div></div>
          </div>
          <div class="form-group"><label>地址</label><input class="form-input" v-model="form.address" placeholder="收货地址"></div>
          <div class="form-row">
            <div class="form-col" style="flex:1"><div class="form-group"><label>备注</label><input class="form-input" v-model="form.remark" placeholder="备注"></div></div>
            <div class="form-col" style="flex:1"><div class="form-group"><label>应收金额</label><input class="form-input" v-model.number="form.receivable_amount" type="number" min="0" step="0.01" placeholder="0.00"></div></div>
          </div>
          <ShipmentItemsPicker
            :items="items"
            :inventory="inventory"
            @add-item="addItem"
            @remove-item="removeItem"
            @search-change="updateItemSearch"
            @focus-item="focusItem"
            @blur-item="blurItem"
            @select-inventory="selectInventory"
            @quantity-change="updateItemQuantity"
            @reset-item="resetItem"
          />
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showModal=false">取消</button>
          <button class="btn btn-primary" @click="save">创建出库单</button>
        </div>
      </div>
    </div>

    <!-- 编辑模态框 -->
    <div v-if="showModal && modalEdit" class="modal-overlay" >
      <div class="modal" style="max-width:500px">
        <div class="modal-header"><span>编辑出库单 — {{ form.shipment_no }}</span><span class="modal-close" @click="showModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-col"><div class="form-group"><label>客户</label><input class="form-input" v-model="form.customer"></div></div>
          </div>
          <div class="form-row">
            <div class="form-col"><div class="form-group"><label>联系人</label><input class="form-input" v-model="form.contact_person"></div></div>
            <div class="form-col"><div class="form-group"><label>电话</label><input class="form-input" v-model="form.contact_phone"></div></div>
          </div>
          <div class="form-group"><label>地址</label><input class="form-input" v-model="form.address"></div>
          <div class="form-row">
            <div class="form-col" style="flex:1"><div class="form-group"><label>备注</label><input class="form-input" v-model="form.remark"></div></div>
            <div class="form-col" style="flex:1"><div class="form-group"><label>应收金额</label><input class="form-input" v-model.number="form.receivable_amount" type="number" min="0" step="0.01" placeholder="0.00"></div></div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showModal=false">取消</button>
          <button class="btn btn-primary" @click="save">保存</button>
        </div>
      </div>
    </div>

    <!-- 详情模态框 -->
    <div v-if="showDetail" class="modal-overlay" >
      <div class="modal" style="width:850px;max-width:90vw">
        <div class="modal-header"><span>📋 {{ detailShipment?.shipment_no }}</span><span class="modal-close" @click="showDetail=false">&times;</span></div>
        <div class="modal-body">
          <div v-if="detailShipment" style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-2);font-size:var(--text-base);margin-bottom:var(--space-4)">
            <div><span style="color:var(--text-placeholder)">客户：</span>{{ detailShipment.customer || '-' }}</div>
            <div><span style="color:var(--text-placeholder)">状态：</span><span class="badge" :class="statusMap[detailShipment.status]?.cls">{{ statusMap[detailShipment.status]?.label }}</span></div>
            <div><span style="color:var(--text-placeholder)">联系人：</span>{{ detailShipment.contact_person || '-' }}</div>
            <div><span style="color:var(--text-placeholder)">电话：</span>{{ detailShipment.contact_phone || '-' }}</div>
            <div><span style="color:var(--text-placeholder)">地址：</span>{{ detailShipment.address || '-' }}</div>
            <div><span style="color:var(--text-placeholder)">物流：</span>{{ detailShipment.logistics_company || '-' }} / {{ detailShipment.tracking_no || '-' }}</div>
            <div><span style="color:var(--text-placeholder)">应收：</span><strong style="color:var(--danger)">{{ detailShipment.receivable_amount || 0 }}</strong></div>
            <div><span style="color:var(--text-placeholder)">已收：</span><strong style="color:var(--success)">{{ detailShipment.paid_amount || 0 }}</strong></div>
            <div><span style="color:var(--text-placeholder)">收款状态：</span><span class="badge" :class="{'badge-info': detailShipment.payment_status==='unpaid'||!detailShipment.payment_status, 'badge-warning': detailShipment.payment_status==='partial', 'badge-success': detailShipment.payment_status==='paid'}">{{ detailShipment.payment_status==='paid'?'已收清':detailShipment.payment_status==='partial'?'部分收':'未收款' }}</span></div>
            <div style="grid-column:1/-1"><span style="color:var(--text-placeholder)">备注：</span>{{ detailShipment.remark || '-' }}</div>
          </div>
          <table v-if="detailShipment?.items?.length" class="data-table">
            <thead><tr><th>订单号</th><th>库存型号</th><th>产品名</th><th style="width:60px;text-align:center">数量</th><th>单位</th><th>备注</th></tr></thead>
            <tbody>
              <tr v-for="it in detailShipment.items" :key="it.id">
                <td><code style="font-size:var(--text-xs-alt)">{{ it.order_no || '-' }}</code></td>
                <td><code style="font-size:var(--text-xs-alt)">{{ it.product_model }}</code></td>
                <td>{{ it.product_name || '-' }}</td>
                <td style="text-align:center;font-weight:600">{{ it.quantity }}</td>
                <td>{{ it.unit }}</td>
                <td style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ it.remark || '-' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else style="text-align:center;color:var(--text-muted);padding:var(--space-5)">无出库明细</p>
          <div v-if="detailShipment?.payments?.length" class="history-section">
            <h4>收付款流水</h4>
            <table class="data-table history-table">
              <thead><tr><th>流水号</th><th>类型</th><th>金额</th><th>日期</th><th>方式</th><th>操作人</th><th></th></tr></thead>
              <tbody><tr v-for="payment in detailShipment.payments" :key="payment.id">
                <td><code>{{ payment.payment_no }}</code></td>
                <td>{{ paymentTypeLabel(payment.type) }}</td>
                <td>{{ payment.amount }}</td>
                <td>{{ payment.payment_date }}</td>
                <td>{{ payment.method || '-' }}</td>
                <td>{{ payment.operator_name || '-' }}</td>
                <td><button v-if="canFinance&&payment.type!=='reversal'&&!isPaymentReversed(payment)" class="btn btn-default btn-sm" @click="reversePayment(payment)">冲销</button></td>
              </tr></tbody>
            </table>
          </div>
          <div v-if="detailShipment?.events?.length" class="history-section">
            <h4>操作历史</h4>
            <table class="data-table history-table">
              <thead><tr><th>时间</th><th>操作</th><th>状态变化</th><th>操作人</th></tr></thead>
              <tbody><tr v-for="event in detailShipment.events" :key="event.id">
                <td>{{ event.created_at }}</td>
                <td>{{ eventLabel(event.event_type) }}</td>
                <td>{{ statusMap[event.from_status]?.label || event.from_status || '-' }} → {{ statusMap[event.to_status]?.label || event.to_status || '-' }}</td>
                <td>{{ event.operator_name || '-' }}</td>
              </tr></tbody>
            </table>
          </div>
          <div v-if="detailShipment" style="text-align:right;margin-top:16px;padding-top:12px;border-top:1px solid var(--border-light)">
            <button class="btn-primary btn-sm" @click="printDeliveryNote(detailShipment)" style="padding:var(--space-2) 20px;font-size:var(--text-sm)">🖨️ 打印送货单</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 收款模态框 -->
    <div v-if="showPayModal" class="modal-overlay" @click.self="showPayModal=false">
      <div class="modal" style="max-width:420px">
        <div class="modal-header"><span>{{ payMode==='refund'?'退款':'收款' }} — {{ payTarget?.shipment_no }}</span><span class="modal-close" @click="showPayModal=false">&times;</span></div>
        <div class="modal-body">
          <div style="margin-bottom:12px;display:flex;gap:16px;font-size:var(--text-sm)">
            <span>应收：<strong style="color:var(--danger)">{{ payTarget?.receivable_amount || 0 }}</strong></span>
            <span>已收：<strong style="color:var(--success)">{{ payTarget?.paid_amount || 0 }}</strong></span>
            <span>未收：<strong style="color:var(--warning)">{{ (payTarget?.receivable_amount||0) - (payTarget?.paid_amount||0) }}</strong></span>
          </div>
          <div class="form-group"><label>{{ payMode==='refund'?'退款':'收款' }}金额</label><input class="form-input" v-model.number="payAmount" type="number" min="0.01" step="0.01" :max="payMode==='refund'?(payTarget?.paid_amount||0):(payTarget?.receivable_amount||0)-(payTarget?.paid_amount||0)"></div>
          <div class="form-row">
            <div class="form-col"><div class="form-group"><label>{{ payMode==='refund'?'退款':'收款' }}方式</label>
              <select class="form-input" v-model="payMethod">
                <option value="">-- 选择 --</option>
                <option value="现金">现金</option>
                <option value="转账">转账</option>
                <option value="支票">支票</option>
                <option value="微信">微信</option>
                <option value="支付宝">支付宝</option>
              </select>
            </div></div>
            <div class="form-col"><div class="form-group"><label>{{ payMode==='refund'?'退款':'收款' }}日期</label><input class="form-input" v-model="payDate" type="date"></div></div>
          </div>
          <div class="form-group"><label>备注</label><input class="form-input" v-model="payRemark" placeholder="收款备注"></div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showPayModal=false">取消</button>
          <button class="btn btn-primary" @click="doPayment">确认{{ payMode==='refund'?'退款':'收款' }}</button>
        </div>
      </div>
    </div>

    <div v-if="showCancelModal" class="modal-overlay" @click.self="showCancelModal=false">
      <div class="modal" style="max-width:440px">
        <div class="modal-header"><span>{{ cancelTarget?.status==='pending'?'取消出库单':'冲销出库单' }} — {{ cancelTarget?.shipment_no }}</span><span class="modal-close" @click="showCancelModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-group"><label>原因</label><textarea class="form-input" v-model="cancelReason" rows="3" placeholder="请输入取消或冲销原因"></textarea></div>
        </div>
        <div class="modal-footer"><button class="btn btn-default" @click="showCancelModal=false">返回</button><button class="btn btn-danger" @click="doCancel">确认</button></div>
      </div>
    </div>

    <div v-if="showReceiveModal" class="modal-overlay" @click.self="showReceiveModal=false">
      <div class="modal" style="max-width:440px">
        <div class="modal-header"><span>签收 — {{ receiveTarget?.shipment_no }}</span><span class="modal-close" @click="showReceiveModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-group"><label>签收人</label><input class="form-input" v-model="receiverName"></div>
          <div class="form-group"><label>签收日期</label><input class="form-input" v-model="receiveDate" type="date"></div>
        </div>
        <div class="modal-footer"><button class="btn btn-default" @click="showReceiveModal=false">取消</button><button class="btn btn-primary" @click="doReceive">确认签收</button></div>
      </div>
    </div>

    <div v-if="showLogisticsModal" class="modal-overlay" @click.self="showLogisticsModal=false">
      <div class="modal" style="max-width:440px">
        <div class="modal-header"><span>物流信息 — {{ logisticsTarget?.shipment_no }}</span><span class="modal-close" @click="showLogisticsModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-group"><label>物流公司</label><input class="form-input" v-model="logisticsCompany"></div>
          <div class="form-group"><label>运单号</label><input class="form-input" v-model="trackingNo"></div>
        </div>
        <div class="modal-footer"><button class="btn btn-default" @click="showLogisticsModal=false">取消</button><button class="btn btn-primary" @click="saveLogistics">保存</button></div>
      </div>
    </div>
  </div>
</template>

<script>
import ShipmentItemsPicker from '@/components/shipments/ShipmentItemsPicker.vue'
import { useShipment } from '@/composables/useShipment.js'

export default {
  components: { ShipmentItemsPicker },
  setup() {
    return useShipment()
  },
}
</script>

<style scoped>
.shipment-table { min-width:1500px; table-layout:fixed; }
.shipment-table th, .shipment-table td { vertical-align:middle; }
.col-expand { width:36px; }
.col-shipment-no { width:150px; }
.col-customer { width:150px; }
.col-product-code { width:220px; }
.col-contact { width:120px; }
.col-count { width:80px; }
.col-qty { width:80px; }
.col-status { width:100px; }
.col-logistics { width:190px; }
.col-money { width:100px; }
.col-pay-status { width:110px; }
.col-actions { width:330px; }
.center-cell { text-align:center; }
.nowrap-cell, .shipment-no-cell, .operation-th, .operation-cell { white-space:nowrap; }
.strong-cell { font-weight:600; }
.expand-cell { text-align:center; font-size:var(--text-xs); color:var(--text-placeholder); }
.shipment-no-cell code { font-size:var(--text-xs); font-weight:600; }
.customer-cell { font-weight:500; }
.ellipsis-cell, .product-code-cell, .logistics-cell { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.product-code-cell code { font-size:var(--text-xs); color:var(--primary); font-weight:600; }
.logistics-cell { font-size:var(--text-sm); color:var(--text-placeholder); }
.pay-status-th, .pay-status-td { text-align:center; white-space:nowrap; }
.operation-th, .operation-cell { position:sticky; right:0; z-index:2; text-align:center; background:var(--bg-card, var(--bg-primary)); box-shadow:-8px 0 12px rgba(15, 23, 42, .06); }
.operation-th { z-index:3; background:var(--bg-table-header, var(--bg-hover)); }
.shipment-actions { justify-content:center; gap:4px; overflow:visible; flex-wrap:nowrap; }
.action-slot { display:inline-flex; align-items:center; justify-content:center; min-width:56px; height:28px; }
.shipment-actions .btn { font-size:var(--text-xs-alt); padding:var(--space-1) 7px; }
.history-section { margin-top:var(--space-5); }
.history-section h4 { margin:0 0 var(--space-2); font-size:var(--text-base); }
.history-table { font-size:var(--text-xs); }
.history-table code { font-size:var(--text-xs-alt); }
</style>
