import { buildQuery, request } from './client.js'

export const masterDataReleasesApi = {
  listReleaseBatches: params => request('GET', '/api/master-data-release-batches' + buildQuery(params)),
  getReleaseBatch: batchId => request('GET', `/api/master-data-release-batches/${batchId}`),
  createReleaseBatch: data => request('POST', '/api/master-data-release-batches', data),
  submitReleaseBatch: (batchId, data) => request('POST', `/api/master-data-release-batches/${batchId}/submit`, data),
  approveReleaseBatch: (batchId, data) => request('POST', `/api/master-data-release-batches/${batchId}/approve`, data),
  rejectReleaseBatch: (batchId, data) => request('POST', `/api/master-data-release-batches/${batchId}/reject`, data),
  removeReleaseBatchMember: (batchId, data) => request('POST', `/api/master-data-release-batches/${batchId}/members/remove`, data),
  replaceReleaseBatchMember: (batchId, data) => request('POST', `/api/master-data-release-batches/${batchId}/members/replace`, data),
}
