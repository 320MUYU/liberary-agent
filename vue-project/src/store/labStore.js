import { reactive } from 'vue'
import { getLabListApi } from '../labApi.js'
import { cancelReservationApi, createReservationApi, getMyReservationsApi } from '../reservationApi.js'
import { getUserInfo } from '../auth.js'

// 实验室数据现在来自后端（这里原来是写死的 6 条假数据）。
// 仍然导出成 reactive 数组，是因为 LabsView / DashboardView / BookingDialog
// 都直接遍历它渲染，保持这个形状可以让这些页面少改。
export const labs = reactive([])

let pending = null

// 拉取实验室列表。多个页面同时挂载会一起调它，共用一个请求，不会重复打接口。
// force=true 用于管理员改完数据后强制刷新。
export function loadLabs(force = false) {
  if (pending) return pending

  if (labs.length && !force) return Promise.resolve(labs)

  pending = getLabListApi()
    .then((list) => {
      // 用 splice 就地替换，而不是 labs.value = ...：保持对外暴露的
      // 还是同一个数组对象，已经引用了它的组件不会失联
      labs.splice(0, labs.length, ...list)
      return labs
    })
    .finally(() => {
      pending = null
    })

  return pending
}

// 卡片配色和图标按"类别"给。这类纯展示的取色不该存进数据库让管理员填，
// 所以从原来每条数据里挪到了这里，统一按类别映射。
const LAB_CATEGORY_STYLE = {
  人工智能: { color: '#dceee8', accent: '#387d70' },
  网络安全: { color: '#e7e9f2', accent: '#59658f' },
  嵌入式: { color: '#f3e8d7', accent: '#9b7440' },
  数字媒体: { color: '#f1dfde', accent: '#a75f5b' },
  云计算: { color: '#e1e9ed', accent: '#527488' },
  大数据: { color: '#e2eddd', accent: '#638754' },
}

const LAB_CATEGORY_ICON = {
  人工智能: 'DataAnalysis',
  网络安全: 'Lock',
  嵌入式: 'Cpu',
  数字媒体: 'VideoCamera',
  云计算: 'Cloudy',
  大数据: 'Histogram',
}

// 新类别（管理员自己加的）取不到预设值时给一套中性配色，不至于渲染成空白
export function labStyle(category) {
  return LAB_CATEGORY_STYLE[category] || { color: '#eaf0ee', accent: '#54807a' }
}

export function labIcon(category) {
  return LAB_CATEGORY_ICON[category] || 'Histogram'
}

// 设备台数：按数量累加，不是按"设备种类"数
export function labUnitCount(lab) {
  return (lab.equipments || []).reduce((sum, item) => sum + item.total, 0)
}

// 设备完好率 = 状态正常的设备种类 / 全部设备种类。
// 这是从真实设备数据算出来的，替换掉了原来手写的"利用率 68%"那种假数字。
export function labHealthyRate(lab) {
  const list = lab.equipments || []
  if (!list.length) return 0
  return Math.round((list.filter(isEquipmentHealthy).length / list.length) * 100)
}

// 全部实验室的整体设备完好率，给页面顶部的统计用
export function overallHealthyRate(list = labs) {
  const all = list.flatMap((lab) => lab.equipments || [])
  if (!all.length) return 0
  return Math.round((all.filter(isEquipmentHealthy).length / all.length) * 100)
}

export const bookings = reactive([])
export const notifications = reactive([])
let bookingsPending = null
let loadedUserId = null
let pendingUserId = null
let bookingRequestVersion = 0

export function clearBookings() {
  bookingRequestVersion += 1
  bookingsPending = null
  pendingUserId = null
  loadedUserId = null
  bookings.splice(0)
  notifications.splice(0)
}

if (typeof window !== 'undefined') {
  window.addEventListener('labmind:logout', clearBookings)
}

function displayBooking(record) {
  return {
    id: record.id,
    labId: record.lab_id,
    lab: record.lab_name,
    room: record.lab_code,
    date: record.date,
    start: record.start?.slice(0, 5),
    end: record.end?.slice(0, 5),
    purpose: record.purpose,
    people: record.people,
    note: record.note,
    status: record.status,
    reviewNote: record.review_note,
    createdAt: record.created_at,
  }
}

export function loadBookings(force = false) {
  const userId = getUserInfo()?.id
  if (!userId) {
    clearBookings()
    return Promise.resolve(bookings)
  }
  if (loadedUserId !== userId) {
    bookingRequestVersion += 1
    bookingsPending = null
    pendingUserId = null
    bookings.splice(0)
    loadedUserId = userId
  }
  if (bookingsPending && pendingUserId === userId && !force) return bookingsPending
  if (bookings.length && !force) return Promise.resolve(bookings)
  pendingUserId = userId
  const requestVersion = ++bookingRequestVersion
  const request = getMyReservationsApi()
    .then((records) => {
      if (
        getUserInfo()?.id === userId
        && loadedUserId === userId
        && requestVersion === bookingRequestVersion
      ) {
        bookings.splice(0, bookings.length, ...records.map(displayBooking))
      }
      return bookings
    })
    .finally(() => { if (bookingsPending === request) bookingsPending = null })
  bookingsPending = request
  return bookingsPending
}

export async function addBooking(data) {
  const userId = getUserInfo()?.id
  const record = await createReservationApi({
    lab_id: Number(data.labId), date: data.date, start: data.start, end: data.end,
    people: data.people, purpose: data.purpose, note: data.note,
  })
  const booking = displayBooking(record)
  if (getUserInfo()?.id !== userId) return booking
  bookingRequestVersion += 1
  bookingsPending = null
  pendingUserId = null
  loadedUserId = userId
  const existingIndex = bookings.findIndex((item) => item.id === booking.id)
  if (existingIndex !== -1) bookings.splice(existingIndex, 1)
  bookings.unshift(booking)
  return booking
}

export async function cancelBooking(id) {
  const userId = getUserInfo()?.id
  const record = await cancelReservationApi(id)
  if (getUserInfo()?.id !== userId) return
  bookingRequestVersion += 1
  bookingsPending = null
  pendingUserId = null
  const index = bookings.findIndex((item) => item.id === id)
  if (index !== -1) bookings.splice(index, 1, displayBooking(record))
}

export const statusMap = {
  approved: { label: '已通过', class: '' }, pending: { label: '审核中', class: 'pending' },
  rejected: { label: '未通过', class: 'cancelled' },
  completed: { label: '已完成', class: 'completed' }, cancelled: { label: '已取消', class: 'cancelled' },
}

export const labStatusMap = {
  available: { label: '可预约', type: 'success' }, busy: { label: '使用中', type: 'warning' }, maintenance: { label: '维护中', type: 'info' },
}

// 设备状态：取值与后端 EquipmentCreateRequest 的 Literal 一一对应
export const equipmentStatusMap = {
  normal: { label: '正常', type: 'success' },
  repair: { label: '维修中', type: 'warning' },
  scrapped: { label: '已报废', type: 'danger' },
}

// "算不算完好"只在这里定义一次，下面两个完好率函数都走它，
// 免得以后加状态时改漏一处
export function isEquipmentHealthy(equipment) {
  return equipment.status === 'normal'
}
