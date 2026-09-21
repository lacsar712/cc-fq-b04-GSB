import axios from 'axios'
import { useAuthStore } from '../stores/auth'

const api = axios.create({
  baseURL: '/api',
  timeout: 20000,
})

api.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') {
      err.message = detail
    } else if (Array.isArray(detail)) {
      err.message = detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
    } else if (detail && typeof detail === 'object') {
      // 结构化错误（如 409 同日重复开跑）：页面与接口展示同一句 message
      err.message = detail.message || JSON.stringify(detail)
      err.detail = detail
    }
    return Promise.reject(err)
  },
)

export async function login(username, password) {
  const { data } = await api.post('/auth/login', { username, password })
  return data
}

export async function getHealth() {
  const { data } = await api.get('/health')
  return data
}

export async function listSamples() {
  const { data } = await api.get('/samples')
  return data
}

export async function listJobs() {
  const { data } = await api.get('/jobs')
  return data
}

export async function getJob(id) {
  const { data } = await api.get(`/jobs/${id}`)
  return data
}

export async function getJobStages(id) {
  const { data } = await api.get(`/jobs/${id}/stages`)
  return data
}

export async function createJob(body) {
  const { data } = await api.post('/jobs', body)
  return data
}

export async function listAttempts() {
  const { data } = await api.get('/attempts')
  return data
}

export default api
