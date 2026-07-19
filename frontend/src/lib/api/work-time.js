import { request, buildQuery } from './client.js'

const BASE = '/api/work-time'

export const workTimeApi = {
  workTimeStats: () => request('GET', BASE + '/stats'),
  listWorkTimeStandards: (params) => request('GET', BASE + '/standards' + buildQuery(params || {})),
  listWorkTimeStandardRoutes: (params) => request('GET', BASE + '/standards/routes' + buildQuery(params || {})),
  createWorkTimeStandard: (data) => request('POST', BASE + '/standards', data),
  saveRouteWorkTimeStandards: (data) => request('POST', BASE + '/standards/route', data),
  updateWorkTimeStandard: (id, data) => request('PUT', BASE + '/standards/' + id, data),
  deleteWorkTimeStandard: (id) => request('DELETE', BASE + '/standards/' + id),
  listWorkTimeRecords: (params) => request('GET', BASE + '/records' + buildQuery(params || {})),
  createWorkTimeRecord: (data) => request('POST', BASE + '/records', data),
  reviewWorkTimeRecord: (id, data) => request('POST', BASE + '/records/' + id + '/review', data),
}
