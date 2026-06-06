// ===== QR-System Global Store =====
// 用 Vue reactive 替代 Pinia，无 build 依赖
import { reactive } from './vendor/vue.esm.js'

export const store = reactive({
  // 缓存数据（各页面共享，避免重复请求）
  products: [],
  customers: [],
  users: [],
  positions: [],
  processes: [],
  processRoutes: [],
  roleGroups: [],
  roles: [],
  shipments: [],
  
  // 仪表盘
  dashboard: null,
  
  // UI 状态
  toast: { show: false, message: '', type: 'success' },
  loading: true,
})

export function showToast(message, type = 'success') {
  store.toast = { show: true, message, type }
  setTimeout(() => { store.toast.show = false }, 3000)
}

// 数据加载辅助
export async function loadIfEmpty(key, fetcher) {
  if (!store[key] || store[key].length === 0) {
    store[key] = await fetcher()
  }
}
