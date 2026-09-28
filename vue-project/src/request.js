import axios from 'axios'
import { ElMessage } from 'element-plus'

import { getToken } from './auth.js'
import router from './router/index.js'
import { useAuthStore } from './store/authStore.js'

const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 30000,
})

function redirectToLogin() {
  const { logout } = useAuthStore()
  const currentRoute = router.currentRoute.value

  logout()

  if (currentRoute.name !== 'login') {
    router.push({
      name: 'login',
      query: { redirect: currentRoute.fullPath },
    })
  }
}

service.interceptors.request.use(
  (config) => {
    const token = getToken()

    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }

    return config
  },
  (error) => Promise.reject(error),
)

service.interceptors.response.use(
  (response) => {
    const payload = response.data

    if (payload.code !== 200) {
      const message = payload.message || '请求失败'

      ElMessage.error(message)

      if (payload.code === 401) {
        redirectToLogin()
      }

      return Promise.reject(new Error(message))
    }

    return payload.data
  },
  (error) => {
    if (error.response) {
      const status = error.response.status
      const message = error.response.data?.message || '请求失败'

      ElMessage.error(message)

      if (status === 401) {
        redirectToLogin()
      }
    } else {
      ElMessage.error('网络异常，请确认后端服务已启动')
    }

    return Promise.reject(error)
  },
)

export default service
