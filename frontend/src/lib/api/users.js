import { request, buildQuery } from './client.js'

function normalizeUserListParams(params = {}) {
  const normalized = { ...params }
  if (normalized.role_not != null && normalized.not_role == null) {
    normalized.not_role = normalized.role_not
    delete normalized.role_not
  }
  if (normalized.role_filter != null && normalized.role == null) {
    normalized.role = normalized.role_filter
    delete normalized.role_filter
  }
  return normalized
}

export const usersApi = {
  listUsers: (params) => request('GET', '/api/users' + buildQuery(normalizeUserListParams(params))),
  createUser: (data) => request('POST', '/api/users', data),
  updateUser: (id, data) => request('PUT', '/api/users/' + id, data),
  deleteUser: (id) => request('DELETE', '/api/users/' + id),
  restoreUser: (id) => request('POST', '/api/users/' + id + '/restore'),
  permanentDeleteUser: (id) => request('DELETE', '/api/users/' + id + '/permanent'),
  resetPassword: (id, data) => request('POST', '/api/users/' + id + '/reset-password', data),
  unlockUser: (id) => request('POST', '/api/users/' + id + '/unlock'),
}
