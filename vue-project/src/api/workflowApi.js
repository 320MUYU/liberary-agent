import request from '@/request'

const base = '/api/workflows'
export const startWorkflow = (data) => request({ url: base, method: 'post', data, timeout: 70000 })
export const getWorkflow = (id) => request({ url: `${base}/${encodeURIComponent(id)}` })
export const retryWorkflow = (id) => request({ url: `${base}/${encodeURIComponent(id)}/retry`, method: 'post', timeout: 70000 })
export const cancelWorkflow = (id) => request({ url: `${base}/${encodeURIComponent(id)}/cancel`, method: 'post', timeout: 70000 })
export const setWorkflowConditions = (id, conditions) => request({ url: `${base}/${encodeURIComponent(id)}/conditions`, method: 'post', data: { conditions } })
export const clarifyWorkflow = (id, text) => request({ url: `${base}/${encodeURIComponent(id)}/clarify`, method: 'post', data: { text } })
export const operateWorkflowStep = (id, data) => request({ url: `${base}/${encodeURIComponent(id)}/steps`, method: 'post', data, timeout: 70000 })
