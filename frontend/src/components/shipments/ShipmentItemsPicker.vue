<template>
  <div class="shipment-items">
    <div class="shipment-items__header">
      <label class="shipment-items__title">出库产品</label>
      <button class="btn btn-default btn-sm" @click="$emit('add-item')" style="font-size:var(--text-xs);padding:var(--space-1) 12px">+ 添加</button>
    </div>
    <div v-if="items.length">
      <div
        v-for="(item, idx) in items"
        :key="idx"
        class="shipment-items__row"
      >
        <div class="shipment-items__search">
          <template v-if="item.inventory_id">
            <div
              class="shipment-items__selected"
              @click="$emit('reset-item', idx)"
            >
              <span><strong>{{ item.product_model }}</strong> <span style="color:var(--text-placeholder)">{{ item.product_name }}</span></span>
              <span style="color:var(--primary);font-size:var(--text-2xs)">切换</span>
            </div>
          </template>
          <template v-else>
            <input
              class="form-input"
              :value="item._search"
              placeholder="输入型号/名称/订单号搜索..."
              @input="$emit('search-change', idx, $event.target.value)"
              @focus="$emit('focus-item', idx)"
              @blur="$emit('blur-item', idx)"
              style="width:100%;font-size:var(--text-sm);padding:6px 8px"
            >
            <div
              v-if="item._showDrop && getFilteredInventory(item._search).length"
              class="shipment-items__dropdown"
            >
              <div
                v-for="inventoryItem in getFilteredInventory(item._search)"
                :key="inventoryItem.id"
                class="shipment-items__option"
                @mousedown.prevent="$emit('select-inventory', idx, inventoryItem)"
              >
                <span><strong>{{ inventoryItem.product_model }}</strong> <span style="color:var(--text-placeholder)">[{{ inventoryItem.order_no || '-' }}]</span></span>
                <span style="color:var(--text-muted)">{{ inventoryItem.product_name || '' }} ({{ inventoryItem.quantity }})</span>
              </div>
            </div>
            <div
              v-if="item._showDrop && item._search && !getFilteredInventory(item._search).length"
              class="shipment-items__empty"
            >
              无匹配产品
            </div>
          </template>
        </div>
        <input
          class="form-input"
          :value="item.quantity"
          type="number"
          min="1"
          placeholder="数量"
          @input="$emit('quantity-change', idx, $event.target.value)"
          style="width:60px;font-size:var(--text-xs);text-align:center"
        >
        <span
          @click="$emit('remove-item', idx)"
          style="color:var(--danger);cursor:pointer;font-size:var(--text-base)"
        >✕</span>
      </div>
    </div>
    <p v-else class="shipment-items__placeholder">暂未添加出库产品</p>
  </div>
</template>

<script>
export default {
  props: {
    items: { type: Array, required: true },
    inventory: { type: Array, required: true },
  },
  emits: [
    'add-item',
    'remove-item',
    'search-change',
    'focus-item',
    'blur-item',
    'select-inventory',
    'quantity-change',
    'reset-item',
  ],
  setup(props) {
    function getFilteredInventory(search) {
      if (!search) return props.inventory
      const keyword = String(search).trim().toLowerCase()
      return props.inventory.filter((inventoryItem) =>
        (inventoryItem.product_model || '').toLowerCase().includes(keyword) ||
        (inventoryItem.product_name || '').toLowerCase().includes(keyword) ||
        (inventoryItem.order_no || '').toLowerCase().includes(keyword)
      )
    }

    return { getFilteredInventory }
  }
}
</script>

<style scoped>
.shipment-items {
  margin-top: 16px;
  border-top: 1px solid var(--border-light);
  padding-top: 12px;
}

.shipment-items__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-2);
}

.shipment-items__title {
  font-weight: 600;
  font-size: var(--text-base);
}

.shipment-items__row {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  margin-bottom: 6px;
  padding: var(--space-2);
  background: var(--bg-table-header);
  border-radius: var(--radius-md);
  flex-wrap: wrap;
}

.shipment-items__search {
  flex: 2;
  min-width: 120px;
  position: relative;
}

.shipment-items__selected {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-table-header);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: 4px 8px;
  font-size: var(--text-xs);
  cursor: pointer;
}

.shipment-items__dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  z-index: 50;
  max-height: 200px;
  overflow-y: auto;
  background: white;
  border: 1px solid var(--primary);
  border-radius: var(--radius-sm);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.shipment-items__option {
  padding: 6px 10px;
  font-size: var(--text-xs);
  cursor: pointer;
  border-bottom: 1px solid var(--bg-hover);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.shipment-items__option:hover {
  background: var(--primary-light);
}

.shipment-items__empty {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  z-index: 50;
  background: white;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: 12px;
  text-align: center;
  font-size: var(--text-xs);
  color: var(--text-placeholder);
}

.shipment-items__placeholder {
  font-size: var(--text-xs);
  color: var(--text-placeholder);
  text-align: center;
  padding: var(--space-3);
}
</style>
