export function reservationError(form, now = new Date()) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.date || '')) return '请选择预约日期。'
  const time = /^(?:[01]\d|2[0-3]):[0-5]\d$/
  if (!time.test(form.start || '') || !time.test(form.end || '')) return '请填写起止时间。'
  if (form.start >= form.end) return '结束时间需要晚于开始时间，同一次预约不能跨天。'
  if (!Number.isInteger(form.people) || form.people < 1 || form.people > 1000)
    return '请填写1至1000之间的整数人数。'
  if (!String(form.purpose || '').trim()) return '请填写使用用途。'
  if (form.purpose.trim().length > 255 || String(form.note || '').length > 200)
    return '用途最多255字，备注最多200字。'
  const start = new Date(`${form.date}T${form.start}:00+08:00`)
  const dateParts = start.toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' })
  if (!Number.isFinite(start.getTime()) || dateParts !== form.date) return '请选择有效日期。'
  if (start.getTime() < now.getTime() + 2 * 3600000) return '预约需至少提前两小时提交。'
  return ''
}

export function spaceAvailability(space) {
  if (space?.can_reserve) return '该时段可申请，仍需管理员审核'
  const reasons = {
    maintenance: '空间维护中',
    capacity: '人数超过容量',
    approved_conflict: '该时段已有通过的预约',
    too_late: '距开始不足两小时'
  }
  return (
    (space?.unavailable_reasons || []).map((code) => reasons[code] || '暂不可申请').join('；') ||
    '可用性待确认'
  )
}

export function reservationHeading(status) {
  return (
    {
      reservation_pending: '预约已提交，待管理员审核',
      reservation_approved: '预约已通过',
      reservation_rejected: '预约未通过',
      reservation_cancelled: '预约已取消',
      cancelled: '已取消本次操作'
    }[status] || '预约任务状态'
  )
}

export function formatSpaceTime(value) {
  if (!value) return '—'
  return new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : value + '+08:00').toLocaleString(
    'zh-CN',
    { timeZone: 'Asia/Shanghai', hour12: false }
  )
}
