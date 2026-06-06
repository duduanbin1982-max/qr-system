// ===== QR-System Router (No vue-router, simple reactive switch) =====
import { reactive, watch } from './vendor/vue.esm.js'

export const router = reactive({
  page: 'login',
  params: {},
  subPage: null,
  tab: null,
})

export function navigate(page, params = {}) {
  router.page = page
  router.params = params
  localStorage.setItem('currentPage', page)
}

// 子页面持久化
watch(() => router.subPage, v => { if (v) localStorage.setItem('settingsSub', v) })
watch(() => router.tab, v => { if (v) localStorage.setItem('invTab', v) })

export function restoreNavState() {
  const sp = localStorage.getItem('settingsSub')
  const tb = localStorage.getItem('invTab')
  if (sp) router.subPage = sp
  if (tb) router.tab = tb
}
