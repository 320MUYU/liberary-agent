// Keep client history within the backend's 30-message / 20,000-character budget.
export function buildChatHistory(messages) {
  const selected = []
  let remaining = 20000
  for (const message of [...messages].reverse()) {
    if (message.localOnly || message.failed || !['user', 'assistant'].includes(message.role)) {
      continue
    }
    const content = String(message.text || '')
      .trim()
      .slice(0, 4000)
    if (!content) continue
    if (selected.length >= 30 || content.length > remaining) break
    selected.push({ role: message.role, content })
    remaining -= content.length
  }
  return selected.reverse()
}

export function retrievalLabel(status) {
  return (
    {
      matched: '已找到知识库依据',
      no_match: '未找到有效的知识库依据',
      insufficient_evidence: '引用依据不足，已保守拒答',
      not_requested: '普通聊天 · 未检索知识库'
    }[status] || ''
  )
}
