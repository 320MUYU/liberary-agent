const TOKEN_KEY = 'labmind-token'
const USER_KEY = 'labmind-user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function removeToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export function getUserInfo() {
  const value = localStorage.getItem(USER_KEY)

  if (!value) return null

  try {
    return JSON.parse(value)
  } catch {
    removeUserInfo()
    return null
  }
}

export function setUserInfo(userInfo) {
  localStorage.setItem(USER_KEY, JSON.stringify(userInfo))
}

export function removeUserInfo() {
  localStorage.removeItem(USER_KEY)
}

export function clearAuthStorage() {
  removeToken()
  removeUserInfo()
}
