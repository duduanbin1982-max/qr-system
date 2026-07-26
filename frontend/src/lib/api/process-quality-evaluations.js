import { buildQuery, request } from './client.js'

export const processQualityEvaluationsApi = {
  qualityEvaluationTasks: (params) => request('GET', '/api/process-quality-evaluations/tasks' + buildQuery(params)),
  qualityEvaluationTaskDisposalSummary: () => request('GET', '/api/process-quality-evaluations/tasks/disposal-summary'),
  qualityEvaluationTaskAudits: (params) => request('GET', '/api/process-quality-evaluations/tasks/audits' + buildQuery(params)),
  waiveQualityEvaluationTasks: (data) => request('POST', '/api/process-quality-evaluations/tasks/waive', data),
  skipQualityEvaluationTask: (id, data) => request('POST', `/api/process-quality-evaluations/tasks/${id}/skip`, data),
  submitQualityEvaluations: (data) => request('POST', '/api/process-quality-evaluations', data),
  qualityEvaluationRecords: (params) => request('GET', '/api/process-quality-evaluations' + buildQuery(params)),
  myQualityEvaluations: (params) => request('GET', '/api/process-quality-evaluations/mine' + buildQuery(params)),
  reviewQualityEvaluation: (id, data) => request('PUT', `/api/process-quality-evaluations/${id}/review`, data),
  createQualityEvaluationAppeal: (id, data) => request('POST', `/api/process-quality-evaluations/${id}/appeals`, data),
  qualityEvaluationAppeals: (params) => request('GET', '/api/process-quality-evaluations/appeals' + buildQuery(params)),
  reviewQualityEvaluationAppeal: (id, data) => request('PUT', `/api/process-quality-evaluations/appeals/${id}/review`, data),
  qualityEvaluationStats: (params) => request('GET', '/api/process-quality-evaluations/stats' + buildQuery(params)),
  qualityEvaluationRules: () => request('GET', '/api/process-quality-evaluations/rules'),
  saveQualityEvaluationRules: (data) => request('PUT', '/api/process-quality-evaluations/rules', data),
  qualityEvaluationReferences: () => request('GET', '/api/process-quality-evaluations/references'),
  qualityEvaluationTemplates: (params) => request('GET', '/api/process-quality-evaluations/templates' + buildQuery(params)),
  createQualityEvaluationTemplate: (data) => request('POST', '/api/process-quality-evaluations/templates', data),
  updateQualityEvaluationTemplate: (id, data) => request('PUT', `/api/process-quality-evaluations/templates/${id}`, data),
}
