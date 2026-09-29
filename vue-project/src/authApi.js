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

// 修改个人信息：只提交姓名/邮箱/手机号/头像，账号和角色由后端保护
export function updateUserInfoApi(data) {
  return request({
    url: '/api/user/info',
    method: 'put',
    data,
  })
}

// 上传文件：FormData 交给 axios 自动设 multipart 边界，不要手动写 Content-Type
export function uploadFileApi(file) {
  const formData = new FormData()
  formData.append('file', file)

  return request({
    url: '/api/file/upload',
    method: 'post',
    data: formData,
  })
}
