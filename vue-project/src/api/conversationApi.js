import request from '@/request'

const base = '/api/conversations'
const path = (id) => `${base}/${encodeURIComponent(id)}`

export const createConversation = (id) =>
  request({ url: base, method: 'post', data: { request_id: id } })

export const getConversation = (id) => request({ url: path(id), method: 'get', timeout: 70000 })

export const sendConversationMessage = (id, data) =>
  request({ url: `${path(id)}/messages`, method: 'post', data, timeout: 100000 })

export const operateConversationTask = (id, taskId, operation, payload = {}) => {
  const taskPath = `${path(id)}/tasks/${encodeURIComponent(taskId)}`
  const direct = ['retry', 'cancel', 'conditions', 'clarify'].includes(operation)
  return request({
    url: `${taskPath}/${direct ? operation : 'steps'}`,
    method: 'post',
    data: direct ? payload : { ...payload, operation },
    timeout: 70000
  })
}
