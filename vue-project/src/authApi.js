import request from './request.js'

export function loginApi(data) {
  return request({
    url: '/api/auth/login',
    method: 'post',
    data,
  })
}

export function getUserInfoApi() {
  return request({
    url: '/api/user/info',
    method: 'get',
  })
}
