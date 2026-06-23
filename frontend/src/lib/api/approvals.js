import { request, buildQuery, uploadFile } from './client.js'

export const approvalsApi = {
  // ========== 审批 ==========
  pendingApprovals:  ()       => request('GET', '/api/approvals/pending'),
  approvalHistory:  (params) => request('GET', '/api/approvals/history' + buildQuery(params)),
  handleApproval:   (id,action,comment) => request('POST', '/api/approvals/' + id + '/' + action, {comment: comment || ''}),
  batchApproval:    (ids, action) => request('POST', '/api/approvals/batch', {ids: ids, action: action}),
  approvalStats:    ()       => request('GET', '/api/approvals/stats'),
  approvalConfig:   ()       => request('GET', '/api/approvals/config'),
  saveApprovalConfig: (data) => request('POST', '/api/approvals/config', data),
}
