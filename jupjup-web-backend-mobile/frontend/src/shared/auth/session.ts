import { useSyncExternalStore } from 'react'
import { env } from '@/shared/config/env'

export type Session = {
  token: string
  expiresAt: string
  user: { id: string; email: string; nickname: string; notificationsEnabled: boolean }
}
export type OAuthExchange = { session: Session; returnPath: '/dashboard' | '/onboarding'; isNewUser: boolean }
const KEY = 'jupjup.auth.session'

export function isSession(value: unknown): value is Session {
  if (!value || typeof value !== 'object') return false
  const s = value as Partial<Session>
  return typeof s.token === 'string' && /^[a-f0-9]{64}$/.test(s.token)
    && typeof s.expiresAt === 'string' && Date.parse(s.expiresAt) > Date.now()
    && !!s.user && typeof s.user.id === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(s.user.id)
    && typeof s.user.email === 'string' && typeof s.user.nickname === 'string'
    && typeof s.user.notificationsEnabled === 'boolean'
}
const SESSION_EVENT = 'jupjup-session-change'
function changed() { window.dispatchEvent(new Event(SESSION_EVENT)) }
export function clearSession() {
  if (localStorage.getItem(KEY) !== null) {
    localStorage.removeItem(KEY)
    changed()
  }
}
function subscribe(listener: () => void) {
  window.addEventListener(SESSION_EVENT, listener)
  window.addEventListener('storage', listener)
  return () => { window.removeEventListener(SESSION_EVENT, listener); window.removeEventListener('storage', listener) }
}
export function sessionScope() { return getSession()?.user.id || env.userId }
export function useAuthenticatedUserId() { return useSyncExternalStore(subscribe, () => getSession()?.user.id || null, () => null) }
export function useSessionScope() { return useSyncExternalStore(subscribe, sessionScope, sessionScope) }
export async function logout() {
  const session = getSession()
  try {
    if (session) await fetch(`${env.apiBaseUrl}/api/auth/logout`, {
      method: 'POST', headers: { Authorization: `Bearer ${session.token}`, 'Content-Type': 'application/json' }, body: '{}',
    })
  } finally { clearSession() }
}
export function getSession(): Session | null {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (isSession(value)) return value
    clearSession()
  } catch { /* Storage may be disabled. */ }
  return null
}
export function storeSession(session: Session) {
  if (!isSession(session)) throw new Error('로그인 응답을 확인해 주세요.')
  localStorage.setItem(KEY, JSON.stringify(session))
  changed()
}
export function startSocialLogin(provider: 'google' | 'naver', signup = false) {
  const path = signup ? '/onboarding' : '/dashboard'
  window.location.assign(`${env.oauthPublicOrigin}/api/auth/oauth/${provider}/start?return_path=${encodeURIComponent(path)}`)
}

// React StrictMode can mount effects twice. Share only the in-flight exchange.
const pending = new Map<string, Promise<OAuthExchange>>()
export function exchangeCode(code: string): Promise<OAuthExchange> {
  const existing = pending.get(code)
  if (existing) return existing
  const promise = (async () => {
    const response = await fetch(`${env.apiBaseUrl}/api/auth/oauth/exchange`, {
      method: 'POST', credentials: 'include', referrerPolicy: 'no-referrer', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    })
    if (!response.ok) throw new Error('로그인을 완료하지 못했어요. 다시 시도해 주세요.')
    const data: unknown = await response.json()
    if (!data || typeof data !== 'object') throw new Error('로그인 응답을 확인해 주세요.')
    const result = data as OAuthExchange
    if (!isSession(result.session) || !['/dashboard', '/onboarding'].includes(result.returnPath)
      || typeof result.isNewUser !== 'boolean') throw new Error('로그인 응답을 확인해 주세요.')
    return result
  })()
  pending.set(code, promise)
  void promise.finally(() => pending.delete(code)).catch(() => {})
  return promise
}
