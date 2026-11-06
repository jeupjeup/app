import { env } from '@/shared/config/env'
import { clearSession, getSession } from '@/shared/auth/session'

type RequestOptions = Omit<RequestInit, 'body'> & { body?: unknown }
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details?: unknown
  constructor(status: number, message: string, code = 'REQUEST_FAILED', details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
    this.name = 'ApiError'
  }
}
export async function requestWithHeaders<T>(path: string, options: RequestOptions = {}): Promise<{ data: T; etag: string | null }> {
  const headers = new Headers(options.headers)
  const session = getSession()
  if (session) {
    headers.set('Authorization', `Bearer ${session.token}`)
    headers.delete('X-User-Id')
  } else {
    headers.delete('X-User-Id')
  }
  if (options.body !== undefined) headers.set('Content-Type', 'application/json')
  const response = await fetch(`${env.apiBaseUrl}${path}`, { ...options, headers, body: options.body === undefined ? undefined : JSON.stringify(options.body) })
  if (response.status === 204) return { data: undefined as T, etag: null }
  const isJson = response.headers.get('content-type')?.includes('application/json')
  const data = isJson ? await response.json() as unknown : null
  if (!response.ok) {
    if (response.status === 401 && session) clearSession()
    const error = data && typeof data === 'object' && 'error' in data ? data.error as Record<string, unknown> : null
    throw new ApiError(response.status, typeof error?.message === 'string' ? error.message : '요청을 처리하지 못했습니다.', typeof error?.code === 'string' ? error.code : 'REQUEST_FAILED', error?.details)
  }
  if (!isJson) throw new ApiError(response.status, '서버 응답 형식을 확인해 주세요.', 'INVALID_RESPONSE')
  return { data: data as T, etag: response.headers.get('ETag') }
}
const request = async <T,>(path: string, options?: RequestOptions) => (await requestWithHeaders<T>(path, options)).data
export const api = {
  get: <T,>(path: string, options?: RequestOptions) => request<T>(path, options),
  post: <T,>(path: string, body?: unknown, options?: RequestOptions) => request<T>(path, { ...options, method: 'POST', body: body ?? {} }),
  patch: <T,>(path: string, body: unknown, options?: RequestOptions) => request<T>(path, { ...options, method: 'PATCH', body }),
  delete: (path: string) => request<void>(path, { method: 'DELETE' }),
}
export const errorMessage = (error: unknown) => error instanceof ApiError ? error.message : '서버에 연결하지 못했어요. 입력은 유지됩니다. 다시 확인해 주세요.'
