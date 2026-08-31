import { request } from './client.js'

export const positionVersionsApi = {
  listPositionVersions: (positionId) => request('GET', `/api/positions/${positionId}/versions`),
  getPositionVersion: (versionId) => request('GET', `/api/position-versions/${versionId}`),
  getPositionVersionImpact: (versionId) => request('GET', `/api/position-versions/${versionId}/impact`),
  createPositionRevision: (positionId, data) => request('POST', `/api/positions/${positionId}/revisions`, data),
  updatePositionVersion: (versionId, data) => request('PUT', `/api/position-versions/${versionId}`, data),
  submitPositionVersion: (versionId, data) => request('POST', `/api/position-versions/${versionId}/submit`, data),
  approvePositionVersion: (versionId, data) => request('POST', `/api/position-versions/${versionId}/approve`, data),
  rejectPositionVersion: (versionId, data) => request('POST', `/api/position-versions/${versionId}/reject`, data),
  cancelPositionVersion: (versionId, data) => request('POST', `/api/position-versions/${versionId}/cancel`, data),
  listPositionLifecycleRequests: (positionId) => request('GET', `/api/positions/${positionId}/lifecycle-requests`),
  requestPositionRetirement: (positionId, data) => request('POST', `/api/positions/${positionId}/retirement-requests`, data),
  requestPositionReactivation: (positionId, data) => request('POST', `/api/positions/${positionId}/reactivation-requests`, data),
  approvePositionLifecycle: (requestId, data) => request('POST', `/api/position-lifecycle-requests/${requestId}/approve`, data),
  rejectPositionLifecycle: (requestId, data) => request('POST', `/api/position-lifecycle-requests/${requestId}/reject`, data),
}
