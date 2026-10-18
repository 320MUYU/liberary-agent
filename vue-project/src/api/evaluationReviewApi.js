import request from '../request.js'

const base = '/api/admin/evaluation-reviews'

export function listEvaluationRuns() {
  return request({ url: base, method: 'get' })
}

export function importEvaluationReport(data) {
  return request({ url: `${base}/import`, method: 'post', data })
}

export function getEvaluationRun(id) {
  return request({ url: `${base}/${id}`, method: 'get' })
}

export function getEvaluationCase(id, caseId) {
  return request({ url: `${base}/${id}/cases/${encodeURIComponent(caseId)}`, method: 'get' })
}

export function saveEvaluationReview(id, caseId, data) {
  return request({ url: `${base}/${id}/cases/${encodeURIComponent(caseId)}`, method: 'put', data })
}

export function exportEvaluationReviews(id, kind) {
  return request({ url: `${base}/${id}/export/${kind}`, method: 'get' })
}
