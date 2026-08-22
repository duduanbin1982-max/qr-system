import { request, buildQuery } from './client.js'

export const approvalsApi = {
  // ========== 审批 ==========
  pendingApprovals:  (params = {}) => request('GET', '/api/approvals/pending' + buildQuery(params)),
  approvalHistory:  (params) => request('GET', '/api/approvals/history' + buildQuery(params)),
  handleApproval:   (id,action,comment) => request('POST', '/api/approvals/' + id + '/' + action, {comment: comment || ''}),
  batchApproval:    (ids, action) => request('POST', '/api/approvals/batch', {ids: ids, action: action}),
  approvalStats:    ()       => request('GET', '/api/approvals/stats'),
  approvalConfig:   ()       => request('GET', '/api/approvals/config'),
  saveApprovalConfig: (data) => request('POST', '/api/approvals/config', data),
  approvalPolicies:   (params = {}) => request('GET', '/api/approval-policies' + buildQuery(params)),
  createPolicyRevision: (data) => request('POST', '/api/approval-policies/revisions', data),
  policyHistory: (id) => request('GET', '/api/approval-policies/' + id + '/history'),
  submitPolicy: (id) => request('POST', '/api/approval-policies/revisions/' + id + '/submit'),
  approvePolicy: (id) => request('POST', '/api/approval-policies/revisions/' + id + '/approve'),
  rejectPolicy: (id) => request('POST', '/api/approval-policies/revisions/' + id + '/reject'),
}
