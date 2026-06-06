// ===== QR-System Auth Module =====
import { reactive } from './vendor/vue.esm.js'
import { api } from './api.js'

export const auth = reactive({
  user: null,
  token: null,
  isAdmin: false,
  isLoggedIn: false,
})

/**
 * Check if current user has a specific permission.
 * Admin users with '*' or isAdmin=true always pass.
 * @param {string} permission - e.g. 'users:create', 'orders:edit'
 * @returns {boolean}
 */
export function can(permission) {
  if (!auth.user) return false
  const perms = auth.user.permissions || []
  if (perms.includes('*') || auth.isAdmin) return true
  return perms.includes(permission)
}

export async function login(username, password) {
  const d = await api.login({ username, password })
  const u = d.user || d
  auth.token = u.token || d.token
  auth.user = u
  auth.isAdmin = u.role === 'admin'
  auth.isLoggedIn = true
  localStorage.setItem('token', auth.token)
  localStorage.setItem('user', JSON.stringify(u))
  return u
}

export function logout() {
  auth.user = null
  auth.token = null
  auth.isAdmin = false
  auth.isLoggedIn = false
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  localStorage.removeItem('currentPage')
}

export function restoreSession() {
  const token = localStorage.getItem('token')
  const user = localStorage.getItem('user')
  if (token && user) {
    try {
      auth.token = token
      auth.user = JSON.parse(user)
      auth.isAdmin = auth.user.role === 'admin'
      auth.isLoggedIn = true
      return true
    } catch(e) {
      logout()
    }
  }
  return false
}
