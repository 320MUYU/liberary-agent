import request from './request.js'

export function getBooksApi(params = {}) {
  return request({ url: '/api/books', method: 'get', params })
}

export function getBookApi(id) {
  return request({ url: `/api/books/${id}`, method: 'get' })
}

export function getAdminBooksApi(params = {}) {
  return request({ url: '/api/admin/books', method: 'get', params })
}

export function createBookApi(data) {
  return request({ url: '/api/admin/books', method: 'post', data })
}

export function updateBookApi(id, data) {
  return request({ url: `/api/admin/books/${id}`, method: 'put', data })
}

export function getBookCopiesApi(id, params = {}) {
  return request({ url: `/api/admin/books/${id}/copies`, method: 'get', params })
}

export function createBookCopyApi(data) {
  return request({ url: '/api/admin/book-copies', method: 'post', data })
}

export function updateBookCopyApi(id, data) {
  return request({ url: `/api/admin/book-copies/${id}`, method: 'put', data })
}
