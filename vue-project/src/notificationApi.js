import request from './request.js'

export function getNotificationsApi(params = {}) {
  return request({ url: '/api/notifications', method: 'get', params })
}

export function readNotificationApi(id) {
  return request({ url: `/api/notifications/${id}/read`, method: 'post' })
}

export function readAllNotificationsApi(throughId) {
  return request({
    url: '/api/notifications/read-all',
    method: 'post',
    data: { through_id: throughId }
  })
}

export function notificationTarget(item) {
  if (item.resource_type === 'loan') return { path: '/loans', query: { loan_id: item.resource_id } }
  if (item.resource_type === 'reservation')
    return { path: '/reservations', query: { reservation_id: item.resource_id } }
  return { path: '/notifications' }
}
