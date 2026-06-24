import { request, buildQuery, uploadFile } from './client.js'

export const settingsApi = {
  // ========== 系统设置 ==========
  getSettings:      ()       => request('GET', '/api/settings'),
  saveSettings:     (data)   => request('POST', '/api/settings', data),
}
