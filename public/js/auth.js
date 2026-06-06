// ===== QR-System Auth Module (v2 — Cookie-only Token) =====
import { reactive } from './vendor/vue.esm.js'
import { api } from './api.js'

export const auth = reactive({
  user: null,
  isAdmin: false,
  isLoggedIn: false,
  loading: true,  // true until /api/auth/info resolves
})

/**
 * Check if current user has a specific permission.
 * Admin users with '*' or isAdmin=true always pass.
 */
export function can(permission) {
  if (!auth.user) return false
  const perms = auth.user.permissions || []
  if (perms.includes('*') || auth.isAdmin) return true
  return perms.includes(permission)
}

/** Login: credentials → httpOnly cookie (server-side) + user info */
export async function login(username, password) {
  const d = await api.login({ username, password })
  const u = d.user || d
  auth.user = u
  auth.isAdmin = u.role === 'admin'
  auth.isLoggedIn = true
  auth.loading = false
  // No localStorage! Token is httpOnly cookie managed by the server.
  localStorage.setItem('currentPage', '') // non-sensitive: UI state only
  return u
}

/** Logout: clear server session + local state */
export async function logout() {
  try { await api.logout() } catch (_) { /* best-effort */ }
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
      auth.user = d.user
      auth.isAdmin = d.user.role === 'admin'
      auth.isLoggedIn = true
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
