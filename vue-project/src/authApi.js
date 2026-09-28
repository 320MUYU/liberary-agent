import request from './request.js'

export function loginApi(data) {
  return request({
    url: '/api/auth/login',
    method: 'post',
    data,
  })
}

// 注册：后端只返回新用户信息，不返回 token，所以调用方拿到后要去登录页
export function registerApi(data) {
  return request({
    url: '/api/auth/register',
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
