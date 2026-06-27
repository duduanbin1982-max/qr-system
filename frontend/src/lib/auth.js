// ===== QR-System Auth Module (v2 — Cookie-only Token) =====
import { reactive } from 'vue'
import { api } from './api.js'
import { hasPermission } from './permissions.js'
import { loadPageAccessCatalog, resetPageAccessCatalog } from './permissionCatalog.js'

export const auth = reactive({
  user: null,
  isAdmin: false,
  isLoggedIn: false,
  loading: true,  // true until /api/auth/info resolves
  mustChangePassword: false,  // 首次登录强制改密标记
})

/**
 * Check if current user has a specific permission.
 * Admin users with '*' or isAdmin=true always pass.
 */
export function can(permission) {
  return hasPermission(auth.user, permission)
}

async function loadPermissionCatalog() {
  return loadPageAccessCatalog(true)
}

/** Login: credentials → httpOnly cookie (server-side) + user info */
export async function login(username, password) {
  const d = await api.login({ username, password })
  const u = d.user || d
  const mustChange = d.must_change_password === true
  if (!mustChange) {
    await loadPermissionCatalog()
  }
  auth.user = u
  auth.isAdmin = !!(u.permissions && u.permissions.includes('*'))
  auth.isLoggedIn = !mustChange  // 需改密时不算已登录
  auth.mustChangePassword = mustChange
  auth.loading = false
  localStorage.setItem('currentPage', '')
  return { user: u, mustChangePassword: mustChange }
}

/** Logout: clear server session + local state */
export async function logout() {
  try { await api.logout() } catch (_) { /* best-effort */ }
  resetPageAccessCatalog()
  auth.user = null
  auth.isAdmin = false
  auth.isLoggedIn = false
  auth.loading = false
  localStorage.removeItem('currentPage')
}

/** Restore session via /api/auth/info (validates httpOnly cookie) */
export async function restoreSession() {
  auth.loading = true
  try {
    const d = await api.authInfo()
    if (d && d.user) {
      await loadPermissionCatalog()
      auth.user = d.user
      auth.isAdmin = !!(d.user.permissions && d.user.permissions.includes('*'))
      auth.mustChangePassword = d.must_change_password === true
      auth.isLoggedIn = !auth.mustChangePassword
      auth.loading = false
      return true
    }
  } catch (_) { /* not logged in */ }
  auth.loading = false
  return false
}


// Listen for auth:expired events from API layer.
// Only redirect to login if user WAS previously logged in (session expired).
// Ignore during initial page load (restoreSession handles that case).
window.addEventListener('auth:expired', () => {
  if (auth.isLoggedIn) {
    auth.user = null
    auth.isAdmin = false
    auth.isLoggedIn = false
    // Navigate to login page via router (if available) or reload
    if (window.A && window.A.router) {
      window.A.router.page = 'login'
    } else {
      window.location.href = '/'
    }
  }
})

/** Change password (first-login or voluntary) */
export async function changePassword(newPassword) {
  if (!newPassword || newPassword.length < 8) {
    throw new Error('新密码至少需要8位')
  }
  const d = await api.changePassword({ new_password: newPassword })
  if (d.error) throw new Error(d.error)
  await loadPermissionCatalog()
  auth.mustChangePassword = false
  auth.isLoggedIn = true
  return d
}

// Shared utility: get board/external token from URL params
export function getBoardToken() {
  return new URLSearchParams(window.location.search).get('token') || ''
}
