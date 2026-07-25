import { request, buildQuery } from './client.js'

export const wagesApi = {
  listWages:          (params) => request('GET', '/api/wages' + buildQuery(params)),
  getSnapshotStatus:  (yearMonth) => request('GET', '/api/wages/snapshot-status' + buildQuery({ year_month: yearMonth })),
  saveSnapshot:       (yearMonth) => request('POST', '/api/wages/snapshot' + buildQuery({ year_month: yearMonth }), {}),
  lockSnapshot:       (yearMonth, notes) => request('POST', '/api/wages/lock' + buildQuery({ year_month: yearMonth }), { notes }),
  confirmSnapshot:    (yearMonth) => request('POST', '/api/wages/confirm' + buildQuery({ year_month: yearMonth }), {}),
  getMonthlySummary:  (params) => request('GET', '/api/wages/monthly-summary' + buildQuery(params)),
  getProcessSummary:  (yearMonth) => request('GET', '/api/wages/process-summary' + buildQuery({ year_month: yearMonth })),
  listAdjustments:    (yearMonth) => request('GET', '/api/wages/adjustments' + buildQuery({ year_month: yearMonth })),
  createAdjustment:   (data) => request('POST', '/api/wages/adjustments', data),
  deleteAdjustment:   (id) => request('DELETE', '/api/wages/adjustments/' + id),
  getWageTrends:      (months) => request('GET', '/api/wages/trends' + buildQuery({ months })),
  getPositionSummary: (yearMonth) => request('GET', '/api/wages/position-summary' + buildQuery({ year_month: yearMonth })),
  getWagePrediction:  (months) => request('GET', '/api/wages/prediction' + buildQuery({ months })),
}
