import request from './request.js'

export function chatApi(messages, mode = 'chat') {
  return request({
    url: '/api/ai/chat',
    method: 'post',
    data: { messages, mode },
    timeout: 70000
  })
}
