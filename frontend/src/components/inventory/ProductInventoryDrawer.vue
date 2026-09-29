<template>
  <Teleport to="body">
    <div v-if="open" class="inventory-drawer-backdrop" @click.self="$emit('close')">
      <aside class="inventory-drawer" role="dialog" aria-modal="true" aria-labelledby="product-drawer-title">
        <header><div><h3 id="product-drawer-title">{{ product?.product_code || '产品库存详情' }}</h3><p>{{ product?.product_name || '' }}</p></div><button class="drawer-close" aria-label="关闭" @click="$emit('close')">×</button></header>
        <main>
          <div v-if="!details" class="product-empty">加载中…</div>
          <template v-else>
            <section><h4>兼容分组</h4><div v-for="group in details.compatibility_groups || []" :key="group.compatibility_key" class="compatibility-card"><strong>{{ group.specification || '标准规格' }}</strong><span>可用 {{ group.available_quantity ?? 0 }}</span></div></section>
            <section><h4>库存明细</h4><div v-for="item in details.inventory_items || []" :key="item.inventory_id" class="detail-row"><code>{{ item.order_no || '无订单' }}</code><span>{{ item.location || '未指定库位' }}</span><span>可用 {{ item.available_quantity ?? 0 }}</span></div></section>
            <section v-if="details.identity_warnings?.length" class="warning-block"><h4>身份异常</h4><p v-for="warning in details.identity_warnings" :key="warning.inventory_id">⚠️ 库存 {{ warning.inventory_id }}：{{ warning.reason }}</p></section>
          </template>
        </main>
        <footer><button class="btn btn-default" @click="$emit('close')">关闭</button></footer>
      </aside>
    </div>
  </Teleport>
</template>

<script setup>
defineProps({ open: Boolean, product: { type: Object, default: null }, details: { type: Object, default: null } })
defineEmits(['close'])
</script>

<style scoped>
.inventory-drawer-backdrop { position:fixed; inset:0; z-index:1000; background:rgba(15,23,42,.35); display:flex; justify-content:flex-end; }
.inventory-drawer { width:min(560px, 94vw); height:100%; background:#fff; display:flex; flex-direction:column; box-shadow:-8px 0 24px rgba(15,23,42,.16); }
.inventory-drawer header,.inventory-drawer footer { flex:none; display:flex; align-items:center; justify-content:space-between; padding:18px 22px; border-bottom:1px solid var(--border-light); }
.inventory-drawer footer { border-top:1px solid var(--border-light); border-bottom:0; justify-content:flex-end; }
.inventory-drawer main { flex:1; overflow:auto; padding:22px; }.drawer-close { border:0; background:none; font-size:28px; cursor:pointer; color:var(--text-muted); }
.inventory-drawer h3 { margin:0; }.inventory-drawer h4 { margin:0 0 10px; }.inventory-drawer section { margin-bottom:22px; }
.compatibility-card,.detail-row { display:flex; justify-content:space-between; gap:12px; padding:12px; border:1px solid var(--border-light); border-radius:8px; margin-bottom:8px; }
.warning-block { color:var(--danger); background:var(--danger-light,#fff1f2); padding:12px; border-radius:8px; }
@media (max-width: 700px) { .inventory-drawer { width:100vw; } }
</style>
