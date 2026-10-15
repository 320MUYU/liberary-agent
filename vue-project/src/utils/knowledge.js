export const DOCUMENT_STATUSES = {
  draft: { label: '未发布', type: 'info' },
  published: { label: '已发布', type: 'success' },
  disabled: { label: '已停用', type: 'warning' },
  deleted: { label: '已删除', type: 'info' }
}

export const VERSION_STATUSES = {
  queued: { label: '等待处理', type: 'info' },
  indexing: { label: '正在建立索引', type: 'warning' },
  ready: { label: '可发布', type: 'success' },
  failed: { label: '处理失败', type: 'danger' }
}

export function latestVersion(document) {
  const versions = document.versions || []
  return (
    versions.find((version) => version.id === document.latest_version_id) ||
    [...versions].sort((a, b) => b.version_number - a.version_number)[0] ||
    null
  )
}

export function canPublishVersion(document, version) {
  return Boolean(
    document.status !== 'deleted' &&
    version?.status === 'ready' &&
    (document.status !== 'published' || document.active_version_id !== version.id)
  )
}

export function canRetryVersion(version) {
  return version?.status === 'failed'
}

export function shouldPollKnowledgeDocuments(documents) {
  return documents.some(
    (document) =>
      document.status !== 'deleted' &&
      document.versions?.some((version) => ['queued', 'indexing'].includes(version.status))
  )
}

export function validateKnowledgeUpload({ title = '', file }, requiresTitle = true) {
  if (requiresTitle && !title.trim()) return '请输入文档标题'
  if ([...title.trim()].length > 200) return '文档标题不能超过 200 个字符'
  if (!file) return '请选择要上传的文件'
  if (!/\.(txt|md|docx|pdf)$/i.test(file.name || '')) return '文件格式仅支持 TXT、MD、DOCX、PDF'
  if (!Number.isFinite(file.size) || file.size <= 0) return '不能上传空文件'
  if (file.size > 10 * 1024 * 1024) return '文件不能超过 10 MB'
  return ''
}

export function safeKnowledgeError(message) {
  const text = String(message || '').trim()
  if (!text || /[A-Za-z]:[\\/]|\/(?:tmp|var|home|Users|app|srv|opt)\//i.test(text)) {
    return '处理失败，请检查文件后重试，或联系管理员。'
  }
  return text.slice(0, 300)
}
