import request from '../request.js'

const base = '/api/agent/runs'
export const startBorrowRun = (data) => request({ url: base, method: 'post', data, timeout: 70000 })
export const getBorrowRun = (id) => request({ url: `${base}/${encodeURIComponent(id)}` })
export const selectBorrowBook = (id, bookId) =>
  request({
    url: `${base}/${encodeURIComponent(id)}/select`,
    method: 'post',
    data: { book_id: bookId }
  })
export const decideBorrow = (id, data) =>
  request({
    url: `${base}/${encodeURIComponent(id)}/decision`,
    method: 'post',
    data,
    timeout: 70000
  })
export const retryBorrowRun = (id) =>
  request({ url: `${base}/${encodeURIComponent(id)}/retry`, method: 'post', timeout: 70000 })
