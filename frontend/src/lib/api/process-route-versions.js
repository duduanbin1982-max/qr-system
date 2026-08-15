import { request } from './client.js'

export const processRouteVersionsApi = {
  createVersionedRoute: data => request('POST', '/api/process-route-versions', data),
  listRouteVersions: routeId => request('GET', `/api/process-routes/${routeId}/versions`),
  getRouteVersion: versionId => request('GET', `/api/process-route-versions/${versionId}`),
  createRouteRevision: (routeId, data) => request('POST', `/api/process-routes/${routeId}/revisions`, data),
  updateRouteVersion: (versionId, data) => request('PUT', `/api/process-route-versions/${versionId}`, data),
  submitRouteVersion: (versionId, data) => request('POST', `/api/process-route-versions/${versionId}/submit`, data),
  approveRouteVersion: (versionId, data) => request('POST', `/api/process-route-versions/${versionId}/approve`, data),
  rejectRouteVersion: (versionId, data) => request('POST', `/api/process-route-versions/${versionId}/reject`, data),
  getRouteVersionImpact: versionId => request('GET', `/api/process-route-versions/${versionId}/impact`),
  requestRouteRetirement: (routeId, data) => request('POST', `/api/process-routes/${routeId}/retirement-requests`, data),
  requestRouteReactivation: (routeId, data) => request('POST', `/api/process-routes/${routeId}/reactivation-requests`, data),
  approveRouteRetirement: (requestId, data) => request('POST', `/api/process-route-retirement-requests/${requestId}/approve`, data),
  approveRouteReactivation: (requestId, data) => request('POST', `/api/process-route-reactivation-requests/${requestId}/approve`, data),
}
