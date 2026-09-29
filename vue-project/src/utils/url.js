// 后端上传接口返回的是相对路径（形如 /uploads/xxx.jpg），浏览器直接用它
// 会打到前端自己的地址上，需要拼上后端地址（VITE_API_BASE_URL）。
// 已经是完整的 http(s) 地址就原样返回，方便以后换成 CDN 或图床。
export function resolveAssetUrl(path) {
  if (!path) return ''
  if (/^https?:\/\//.test(path)) return path
  return `${import.meta.env.VITE_API_BASE_URL}${path}`
}
