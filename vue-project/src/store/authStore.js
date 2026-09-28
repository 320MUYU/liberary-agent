import { computed, readonly, ref } from 'vue'
import {
  clearAuthStorage,
  getToken,
  getUserInfo,
  setToken,
  setUserInfo,
} from '../auth.js'

const token = ref(getToken())
const userInfo = ref(getUserInfo())
const isAuthenticated = computed(() => Boolean(token.value && userInfo.value))

export function useAuthStore() {
  function saveLoginData(data) {
    setToken(data.token)
    setUserInfo(data.user)
    token.value = data.token
    userInfo.value = data.user
  }

  function updateUser(user) {
    setUserInfo(user)
    userInfo.value = user
  }

  function reloadAuth() {
    token.value = getToken()
    userInfo.value = getUserInfo()
  }

  function logout() {
    clearAuthStorage()
    token.value = null
    userInfo.value = null
  }

  return {
    token: readonly(token),
    userInfo: readonly(userInfo),
    isAuthenticated,
    saveLoginData,
    updateUser,
    reloadAuth,
    logout,
  }
}
