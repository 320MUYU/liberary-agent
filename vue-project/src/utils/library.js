export const LOAN_STATUSES = {
  pending: { label: '待确认借出', type: 'warning' },
  borrowed: { label: '借阅中', type: 'primary' },
  return_pending: { label: '待确认归还', type: 'warning' },
  returned: { label: '已归还', type: 'success' },
  rejected: { label: '已拒绝', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' }
}

export const COPY_STATUSES = {
  available: { label: '正常馆藏', type: 'success' },
  maintenance: { label: '维护中', type: 'warning' },
  withdrawn: { label: '已退藏', type: 'info' }
}

export function canRequestLoan(book) {
  return Boolean(book?.is_active && book.available_copies > 0)
}

export function canRequestReturn(loan) {
  return loan?.status === 'borrowed'
}

export function bookAvailability(book) {
  if (!book || !Number.isFinite(book.total_copies)) return '馆藏信息待确认'
  if (book.total_copies === 0) return '本馆尚未登记馆藏'
  if (book.available_copies > 0) return `可借 ${book.available_copies} 册`
  return '暂无可借副本'
}

export function discoveryDegradation(codes = []) {
  const messages = {
    knowledge_disabled: '知识库检索未启用，当前仅按分类和主题标签匹配',
    vector_unavailable: '向量检索暂不可用，已使用关键词和元数据检索',
    rerank_unavailable: '重排暂不可用，已使用融合排序',
    knowledge_unavailable: '知识库检索暂不可用，当前仅按分类和主题标签匹配'
  }
  return [...new Set(codes)].map((code) => messages[code] || '部分检索服务不可用').join('；')
}

export function bookLanguages(source) {
  const names = { chi: '中文', zho: '中文', eng: '英语', fre: '法语', fra: '法语', jpn: '日语' }
  return source?.languages?.map((code) => names[code] || code).join(' / ') || '未提供'
}

export function loanActions(status, role) {
  if (role === 'reader') {
    if (status === 'pending') return ['cancel']
    if (status === 'borrowed') return ['request-return']
  }
  if (role === 'admin') {
    if (status === 'pending') return ['confirm-borrow', 'reject']
    if (status === 'return_pending') return ['confirm-return']
  }
  return []
}

export function copyAvailability(copy) {
  if (copy.is_on_loan) return { label: '借出中', type: 'primary' }
  if (copy.status === 'available') return { label: '可借出', type: 'success' }
  return COPY_STATUSES[copy.status] || { label: '状态未知', type: 'info' }
}

export function toBookPayload(book) {
  const optional = (value) => String(value || '').trim() || null
  return {
    title: String(book.title || '').trim(),
    author: String(book.author || '').trim(),
    isbn: optional(book.isbn),
    publisher: optional(book.publisher),
    publication_year: Number.isInteger(book.publication_year) ? book.publication_year : null,
    category: String(book.category || '').trim(),
    description: optional(book.description),
    cover: optional(book.cover),
    is_active: Boolean(book.is_active)
  }
}

export function formatLoanTime(value) {
  if (!value) return '—'
  // 服务端使用本地无时区日期，保留原时间，避免浏览器额外偏移时区。
  return String(value).replace('T', ' ').slice(0, 16)
}
