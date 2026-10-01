import request from './request.js'

export function chatApi(messages) {
  return request({
    url: '/api/ai/chat',
    method: 'post',
    data: { messages },
    timeout: 70000,
  })
}
