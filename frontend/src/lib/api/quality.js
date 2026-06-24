import { request, buildQuery, uploadFile } from './client.js'

export const qualityApi = {
  // ========== 质检 ==========
  listInspections:  (params) => request('GET', '/api/quality/inspections' + buildQuery(params)),
  inspectionStats:  ()       => request('GET', '/api/inspection/stats'),
  createInspection: (data)   => request('POST', '/api/quality/inspections', data),
  updateInspection: (id,data)=> request('PUT', '/api/quality/inspections/' + id, data),
  deleteInspection: (id)     => request('DELETE', '/api/quality/inspections/' + id),
  defectCategories: ()       => request('GET', '/api/quality/defect-categories'),
  defectPareto:     (params) => request('GET', '/api/quality/defect-pareto' + buildQuery(params)),
  inspectionTemplates: ()     => request('GET', '/api/quality/inspection-templates'),
  batchInspections:   (data)  => request('POST', '/api/quality/inspections/batch', data),
  listQAttachments:   (iid)   => request('GET', '/api/quality/inspections/' + iid + '/attachments'),
  uploadQAttachment:  (iid, formData) => uploadFile('/api/quality/inspections/' + iid + '/attachments', formData),
  exportInspections:(params) => request('GET', '/api/quality/inspections/export' + buildQuery(params)),
  qualityInspStats: ()       => request('GET', '/api/quality/inspections/stats'),
  spcPChart:       (params) => request('GET', '/api/quality/spc-p-chart' + buildQuery(params)),
  deleteQAttachment:  (aid)   => request('DELETE', '/api/quality/attachments/' + aid),
  getQAttachmentUrl:  (aid)   => '/api/quality/attachments/' + aid,
}
