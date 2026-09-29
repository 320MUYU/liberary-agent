import request from './request.js'

// 实验室只读接口：登录后即可访问，不要求管理员。
// 管理端的增删改在 adminApi.js 里。

export function getLabListApi() {
  return request({
    url: '/api/lab/list',
    method: 'get',
  })
}

export function getLabDetailApi(labId) {
  return request({
    url: `/api/lab/${labId}`,
    method: 'get',
  })
}
