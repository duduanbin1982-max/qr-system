import { buildQuery, request } from './client.js'

export const processQualityEvaluationsApi = {
  qualityEvaluationTasks: (params) => request('GET', '/api/process-quality-evaluations/tasks' + buildQuery(params)),
  submitQualityEvaluations: (data) => request('POST', '/api/process-quality-evaluations', data),
  qualityEvaluationRecords: (params) => request('GET', '/api/process-quality-evaluations' + buildQuery(params)),
  reviewQualityEvaluation: (id, data) => request('PUT', `/api/process-quality-evaluations/${id}/review`, data),
  qualityEvaluationStats: (params) => request('GET', '/api/process-quality-evaluations/stats' + buildQuery(params)),
  qualityEvaluationRules: () => request('GET', '/api/process-quality-evaluations/rules'),
  saveQualityEvaluationRules: (data) => request('PUT', '/api/process-quality-evaluations/rules', data),
}
