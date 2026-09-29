import request from './request.js'

// 管理端接口：后端每个接口都挂了 get_current_admin，非管理员调用会被 403 挡回来。
// 前端隐藏菜单只是体验优化，不能当成权限控制。

// 用户列表：分页与筛选都交给后端做（数据量大了不可能全量拉到前端再过滤）
export function getUserListApi(params) {
  return request({
    url: '/api/admin/user/list',
    method: 'get',
    params,
  })
}

export function updateUserRoleApi(userId, role) {
  return request({
    url: `/api/admin/user/${userId}/role`,
    method: 'put',
    data: { role },
  })
}

export function updateUserStatusApi(userId, status) {
  return request({
    url: `/api/admin/user/${userId}/status`,
    method: 'put',
    data: { status },
  })
}

// 重置他人密码：不需要原密码，所以这个接口的权限必须严格锁在管理员上
export function resetUserPasswordApi(userId, newPassword) {
  return request({
    url: `/api/admin/user/${userId}/password`,
    method: 'put',
    data: { new_password: newPassword },
  })
}
