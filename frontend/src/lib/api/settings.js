import { request, buildQuery, uploadFile } from './client.js'

export const settingsApi = {
  // ========== 系统设置 ==========
  getSettings:      ()       => request('GET', '/api/settings'),
  saveSettings:     (data)   => request('POST', '/api/settings', data),
  getProcessConfig: ()       => request('GET', '/api/process-config'),
  getProcessConfigHistory: (limit = 100) => request(
    'GET', `/api/process-config/revisions${buildQuery({ limit })}`
  ),
  createProcessConfigRevision: (data) => request(
    'POST', '/api/process-config/revisions', data
  ),
  updateProcessConfigRevision: (revisionId, data) => request(
    'PUT', `/api/process-config/revisions/${revisionId}`, data
  ),
  submitProcessConfigRevision: (revisionId, data) => request(
    'POST', `/api/process-config/revisions/${revisionId}/submit`, data
  ),
  approveProcessConfigRevision: (revisionId, data) => request(
    'POST', `/api/process-config/revisions/${revisionId}/approve`, data
  ),
  rejectProcessConfigRevision: (revisionId, data) => request(
    'POST', `/api/process-config/revisions/${revisionId}/reject`, data
  ),
  getCompanyInfo:   ()       => request('GET', '/api/settings/company-info'),
  saveCompanyInfo:  (data)   => request('PUT', '/api/settings/company-info', data),
  getCompanyInfoHistory: (limit = 100) => request(
    'GET', `/api/settings/company-info/history${buildQuery({ limit })}`
  ),
}
