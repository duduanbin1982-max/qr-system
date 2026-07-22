import { request, buildQuery } from './client.js'

export const performanceApi = {
  performanceOverview: (params) => request('GET', '/api/performance/overview' + buildQuery(params)),
  performanceScores: (params) => request('GET', '/api/performance/scores' + buildQuery(params)),
  performanceRules: () => request('GET', '/api/performance/rules'),
  generatePerformance: (data) => request('POST', '/api/performance/generate', data),
  performancePlans: (params) => request('GET', '/api/performance/plans' + buildQuery(params)),
  savePerformanceReview: (data) => request('POST', '/api/performance/reviews', data),
  createPerformancePlan: (data) => request('POST', '/api/performance/plans', data),
  updatePerformancePlan: (id, data) => request('PUT', '/api/performance/plans/' + id, data),
}
