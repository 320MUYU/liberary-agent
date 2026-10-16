import request from '../request.js'

const base = '/api/admin/knowledge'

export function searchKnowledgeApi(data) {
  return request({ url: `${base}/search`, method: 'post', data, timeout: 65000 })
}

export function getKnowledgeIndexStatusApi(versionId) {
  return request({
    url: `${base}/versions/${versionId}/index-status`,
    method: 'get',
    timeout: 65000
  })
}

function uploadData({ title = '', file }) {
  const data = new FormData()
  data.append('title', title.trim())
  data.append('file', file)
  return data
}

export function getKnowledgeDocumentsApi() {
  return request({ url: `${base}/documents`, method: 'get' })
}

export function uploadKnowledgeDocumentApi(data) {
  return request({ url: `${base}/documents`, method: 'post', data: uploadData(data) })
}

export function uploadKnowledgeVersionApi(documentId, data) {
  return request({
    url: `${base}/documents/${documentId}/versions`,
    method: 'post',
    data: uploadData(data)
  })
}

export function publishKnowledgeDocumentApi(documentId, versionId) {
  return request({
    url: `${base}/documents/${documentId}/publish`,
    method: 'post',
    params: { version_id: versionId }
  })
}

export function disableKnowledgeDocumentApi(documentId) {
  return request({ url: `${base}/documents/${documentId}/disable`, method: 'post' })
}

export function deleteKnowledgeDocumentApi(documentId) {
  return request({ url: `${base}/documents/${documentId}`, method: 'delete' })
}

export function retryKnowledgeVersionApi(versionId) {
  return request({ url: `${base}/versions/${versionId}/retry`, method: 'post' })
}

export function getKnowledgeSourceApi(chunkId) {
  return request({ url: `/api/knowledge/sources/${encodeURIComponent(chunkId)}`, method: 'get' })
}
