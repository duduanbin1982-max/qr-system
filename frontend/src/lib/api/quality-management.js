import { buildQuery, request } from './client.js'

const root = '/api/quality-management'

export const qualityManagementApi = {
  qualityDashboard: () => request('GET', root + '/dashboard'),
  qualityReferences: () => request('GET', root + '/references'),
  qualityRules: () => request('GET', root + '/rules'),
  saveQualityRules: data => request('PUT', root + '/rules', data),

  qualityStandards: params => request('GET', root + '/standards' + buildQuery(params)),
  qualityStandard: id => request('GET', root + '/standards/' + id),
  createQualityStandard: data => request('POST', root + '/standards', data),
  updateQualityStandard: (id, data) => request('PUT', root + '/standards/' + id, data),
  archiveQualityStandard: id => request('DELETE', root + '/standards/' + id),

  qualityPlans: params => request('GET', root + '/plans' + buildQuery(params)),
  createQualityPlan: data => request('POST', root + '/plans', data),
  updateQualityPlan: (id, data) => request('PUT', root + '/plans/' + id, data),
  archiveQualityPlan: id => request('DELETE', root + '/plans/' + id),

  qualityTasks: params => request('GET', root + '/tasks' + buildQuery(params)),
  qualityTask: id => request('GET', root + '/tasks/' + id),
  createQualityTask: data => request('POST', root + '/tasks', data),
  startQualityTask: id => request('POST', root + '/tasks/' + id + '/start', {}),
  inspectQualityTask: (id, data) => request('POST', root + '/tasks/' + id + '/inspect', data),
  managedInspections: params => request('GET', root + '/inspections' + buildQuery(params)),
  qualityInspection: id => request('GET', root + '/inspections/' + id),
  reviewQualityInspection: (id, data) => request('POST', root + '/inspections/' + id + '/review', data),

  qualityNcr: params => request('GET', root + '/ncr' + buildQuery(params)),
  qualityNcrDetail: id => request('GET', root + '/ncr/' + id),
  createQualityNcr: data => request('POST', root + '/ncr', data),
  disposeQualityNcr: (id, data) => request('PUT', root + '/ncr/' + id + '/disposition', data),
  qualityCapa: params => request('GET', root + '/capa' + buildQuery(params)),
  createQualityCapa: data => request('POST', root + '/capa', data),
  updateQualityCapa: (id, data) => request('PUT', root + '/capa/' + id, data),

  supplierInspections: params => request('GET', root + '/supplier-inspections' + buildQuery(params)),
  createSupplierInspection: data => request('POST', root + '/supplier-inspections', data),
  qualityGauges: params => request('GET', root + '/gauges' + buildQuery(params)),
  createQualityGauge: data => request('POST', root + '/gauges', data),
  updateQualityGauge: (id, data) => request('PUT', root + '/gauges/' + id, data),
  calibrateQualityGauge: (id, data) => request('POST', root + '/gauges/' + id + '/calibrations', data),
  qualityAnalytics: params => request('GET', root + '/analytics' + buildQuery(params)),
}
