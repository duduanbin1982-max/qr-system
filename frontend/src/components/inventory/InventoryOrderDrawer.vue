<template>
  <Teleport to="body">
    <div v-if="open" class="inventory-drawer-backdrop" @click.self="$emit('close')">
      <aside class="inventory-drawer inventory-order-drawer" role="dialog" aria-modal="true" aria-labelledby="inventory-order-drawer-title">
        <header>
          <div>
            <h3 id="inventory-order-drawer-title">库存明细</h3>
            <p>{{ item?.order_no || '未关联订单' }} · {{ item?.product_model || '-' }}</p>
          </div>
          <button class="drawer-close" aria-label="关闭库存明细" @click="$emit('close')">×</button>
        </header>
        <main>
          <section class="inventory-drawer-summary">
            <div><span>产品名称</span><strong>{{ item?.product_name || '-' }}</strong></div>
            <div><span>客户</span><strong>{{ item?.customer || '-' }}</strong></div>
            <div><span>规格</span><strong>{{ item?.specification || '-' }}</strong></div>
            <div><span>库位</span><strong>{{ item?.location || '-' }}</strong></div>
          </section>
          <section>
            <h4>库存数量</h4>
            <div class="inventory-order-metrics">
              <div><span>当前库存</span><strong>{{ item?.quantity ?? 0 }} {{ item?.unit || '件' }}</strong></div>
              <div><span>可用库存</span><strong>{{ item?.available_quantity ?? 0 }}</strong></div>
              <div><span>预留</span><strong>{{ item?.reserved ?? 0 }}</strong></div>
              <div><span>安全库存</span><strong>{{ item?.safe_stock ?? 0 }}</strong></div>
            </div>
          </section>
          <section>
            <h4>状态</h4>
            <p class="inventory-order-status" :class="item?.is_low ? 'is-low' : 'is-normal'">
              {{ item?.is_low ? '低库存，需要关注' : '库存正常' }}
            </p>
          </section>
        </main>
        <footer>
          <button class="btn btn-default" type="button" @click="$emit('logs', item)">查看库存流水</button>
          <button class="btn btn-default" type="button" @click="$emit('close')">关闭</button>
        </footer>
      </aside>
    </div>
  </Teleport>
</template>

<script setup>
defineProps({ open: Boolean, item: { type: Object, default: null } })
defineEmits(['close', 'logs'])
</script>

<style scoped>
.inventory-order-drawer { width:min(560px, 94vw); }
.inventory-drawer-summary { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.inventory-drawer-summary > div, .inventory-order-metrics > div { display:flex; flex-direction:column; gap:4px; padding:12px; border:1px solid var(--border-light); border-radius:8px; }
.inventory-drawer-summary span, .inventory-order-metrics span { color:var(--text-muted); font-size:12px; }.inventory-drawer-summary strong, .inventory-order-metrics strong { color:var(--text-primary); font-size:14px; word-break:break-word; }
.inventory-order-metrics { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }.inventory-order-status { margin:0; padding:12px; border-radius:8px; font-weight:600; }.inventory-order-status.is-low { color:var(--danger); background:var(--danger-light,#fff1f2); }.inventory-order-status.is-normal { color:var(--success); background:var(--success-light,#ecfdf5); }
@media (max-width: 700px) { .inventory-drawer-summary,.inventory-order-metrics { grid-template-columns:1fr; } }
</style>
