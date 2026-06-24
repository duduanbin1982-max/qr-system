import { request, buildQuery, uploadFile } from './client.js'

export const statsApi = {
  // ========== 统计 ==========
  dailyStats:       (params) => request('GET', '/api/stats/daily' + buildQuery(params)),
  workerStats:      (params) => request('GET', '/api/stats/worker' + buildQuery(params)),
  workerDetail:     (params) => request('GET', '/api/stats/worker-detail' + buildQuery(params)),
  scrapStats:       (params) => request('GET', '/api/stats/scrap' + buildQuery(params)),
  orderProgress:    (params) => request('GET', '/api/stats/order-progress' + buildQuery(params)),
  dailyReport:      (params) => request('GET', '/api/daily-report' + buildQuery(params)),
  productionProgress:(params)=>request('GET', '/api/production-progress' + buildQuery(params)),
  productionTrend:  (params) => request('GET', '/api/reports/production-trend' + buildQuery(params)),
  monthlySummary:   ()       => request('GET', '/api/stats/monthly-summary'),
  workerEfficiency: (params) => request('GET', '/api/reports/worker-efficiency' + buildQuery(params)),
  qualityAnalysis:  (params) => request('GET', '/api/reports/quality-analysis' + buildQuery(params)),
  orderAnalysis:    (params) => request('GET', '/api/reports/order-analysis' + buildQuery(params)),
  dashboardKpi:     (params) => request('GET', '/api/reports/dashboard-kpi' + buildQuery(params)),
  materialUsage:    (params) => request('GET', '/api/stats/material' + buildQuery(params)),
  productStats:     (params) => request('GET', '/api/stats/product' + buildQuery(params)),
  productProcessMatrix: (params) => request('GET', '/api/reports/product-process-matrix' + buildQuery(params)),
  modelProcessStats: (params) => request('GET', '/api/reports/model-process-stats' + buildQuery(params)),
  productProcessStats: (params) => request('GET', '/api/stats/product-process' + buildQuery(params)),
  reportShipmentStats: (params) => request('GET', '/api/stats/shipment' + buildQuery(params)),
  customerStats:    (params) => request('GET', '/api/stats/customer' + buildQuery(params)),
  materialDetail:   (params) => request('GET', '/api/stats/material-detail' + buildQuery(params)),
}
