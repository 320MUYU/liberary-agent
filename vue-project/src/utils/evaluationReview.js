export function percent(value) {
  return value == null ? '待审核' : `${Math.round(value * 10000) / 100}%`
}

export function filterCases(cases, status) {
  return cases.filter((row) => {
    const review = row.review
    if (status === 'pending') return review.status !== 'reviewed'
    if (status === 'reviewed') return review.status === 'reviewed'
    if (status === 'human_negative') {
      return (
        review.status === 'reviewed' &&
        (review.answer_correct === false || review.citations_support === false)
      )
    }
    if (status === 'automatic_failure') return !row.contract_pass
    return true
  })
}

export function citedSources(row) {
  const cited = new Set(
    [...(row?.answer?.content || '').matchAll(/\[([1-9][0-9]{0,2})\]/g)].map((match) =>
      Number(match[1])
    )
  )
  return (row?.answer?.sources || []).map((source) => ({
    ...source,
    cited: cited.has(source.number)
  }))
}

export function reviewForm(review) {
  return {
    answer_correct: review.answer_correct ?? null,
    citations_support: review.citations_support ?? null,
    notes: review.notes || ''
  }
}

export function reviewLabel(status) {
  return { pending_human: '待审核', draft: '草稿', reviewed: '已审核' }[status] || status
}
