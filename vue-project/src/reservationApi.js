import request from './request.js'

export function getMyReservationsApi() {
  return request({ url: '/api/reservation/mine', method: 'get' })
}

export function createReservationApi(data) {
  return request({ url: '/api/reservation', method: 'post', data })
}

export function cancelReservationApi(id) {
  return request({ url: `/api/reservation/${id}/cancel`, method: 'put' })
}
