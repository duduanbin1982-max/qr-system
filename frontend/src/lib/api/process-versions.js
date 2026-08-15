import { request } from './client.js'

export const processVersionsApi = {
  createVersionedProcess: (data) => request('POST', '/api/process-versions', data),
  listProcessVersions: (processId) => request('GET', `/api/processes/${processId}/versions`),
  getProcessVersion: (versionId) => request('GET', `/api/process-versions/${versionId}`),
  createProcessRevision: (processId, data) => request('POST', `/api/processes/${processId}/revisions`, data),
  updateProcessVersion: (versionId, data) => request('PUT', `/api/process-versions/${versionId}`, data),
  submitProcessVersion: (versionId, data) => request('POST', `/api/process-versions/${versionId}/submit`, data),
  approveProcessVersion: (versionId, data) => request('POST', `/api/process-versions/${versionId}/approve`, data),
  rejectProcessVersion: (versionId, data) => request('POST', `/api/process-versions/${versionId}/reject`, data),
  getProcessVersionImpact: (versionId) => request('GET', `/api/process-versions/${versionId}/impact`),
  requestProcessRetirement: (processId, data) => request('POST', `/api/processes/${processId}/retirement-requests`, data),
  requestProcessReactivation: (processId, data) => request('POST', `/api/processes/${processId}/reactivation-requests`, data),
  approveProcessRetirement: (requestId, data) => request('POST', `/api/process-retirement-requests/${requestId}/approve`, data),
  approveProcessReactivation: (requestId, data) => request('POST', `/api/process-reactivation-requests/${requestId}/approve`, data),
}
