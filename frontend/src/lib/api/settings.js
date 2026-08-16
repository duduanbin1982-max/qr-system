import { request, buildQuery, uploadFile } from './client.js'

export const settingsApi = {
  // ========== 系统设置 ==========
  getSettings:      ()       => request('GET', '/api/settings'),
  saveSettings:     (data)   => request('POST', '/api/settings', data),
  getCompanyInfo:   ()       => request('GET', '/api/settings/company-info'),
  saveCompanyInfo:  (data)   => request('PUT', '/api/settings/company-info', data),
  getCompanyInfoHistory: (limit = 100) => request(
    'GET', `/api/settings/company-info/history${buildQuery({ limit })}`
  ),
}
