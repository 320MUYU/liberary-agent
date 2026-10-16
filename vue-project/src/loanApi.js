import request from './request.js'

export function createLoanApi(bookId) {
  return request({ url: '/api/loans', method: 'post', data: { book_id: bookId } })
}

export function getMyLoansApi(params = {}) {
  return request({ url: '/api/loans', method: 'get', params })
}

export function cancelLoanApi(id) {
  return request({ url: `/api/loans/${id}/cancel`, method: 'post' })
}

export function requestLoanReturnApi(id) {
  return request({ url: `/api/loans/${id}/request-return`, method: 'post' })
}

export function getAdminLoansApi(params = {}) {
  return request({ url: '/api/admin/loans', method: 'get', params })
}

export function confirmBorrowApi(id, copyId) {
  return request({
    url: `/api/admin/loans/${id}/confirm-borrow`,
    method: 'post',
    data: copyId == null ? {} : { copy_id: copyId }
  })
}

export function rejectLoanApi(id, reason) {
  return request({
    url: `/api/admin/loans/${id}/reject`,
    method: 'post',
    data: { reason: reason.trim() }
  })
}

export function confirmReturnApi(id) {
  return request({ url: `/api/admin/loans/${id}/confirm-return`, method: 'post' })
}
