import { request, buildQuery, uploadFile } from './client.js'

export const authApi = {
  // ========== 认证 ==========
  login:         (data) => request('POST', '/api/auth/login', data),
  logout:        ()    => request('POST', '/api/auth/logout'),
  authInfo:      ()    => request('GET', '/api/auth/info'),
  changePassword:(data) => request('POST', '/api/auth/change-password', data),
}
