import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearSession, exchangeCode, getSession, startSocialLogin, storeSession } from './session'
const session = { token: 'a'.repeat(64), expiresAt: '2099-01-01T00:00:00Z', user: { id: '12345678-1234-1234-1234-123456789abc', email: 'u@example.com', nickname: 'User', notificationsEnabled: false } }
beforeEach(() => localStorage.clear())
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules() })
it('stores valid sessions and clears expired/corrupt data', () => {
  expect(getSession()).toBeNull()
  storeSession(session)
  expect(getSession()).toEqual(session)
  clearSession()
  expect(getSession()).toBeNull()
  expect(() => storeSession({ ...session, expiresAt: '2000-01-01' })).toThrow()
  localStorage.setItem('jupjup.auth.session', '{corrupt')
  expect(getSession()).toBeNull()
  localStorage.setItem('jupjup.auth.session', JSON.stringify({ ...session, expiresAt: '2000-01-01' }))
  expect(getSession()).toBeNull()
  expect(localStorage.getItem('jupjup.auth.session')).toBeNull()
})
it('starts both providers on canonical 127.0.0.1 when the page is on localhost', () => {
  const assign = vi.fn()
  vi.stubGlobal('window', { location: { origin: 'http://localhost:5177', assign } })
  startSocialLogin('google')
  expect(assign).toHaveBeenLastCalledWith('http://127.0.0.1:5177/api/api/auth/oauth/google/start?return_path=%2Fdashboard')
  startSocialLogin('naver', true)
  expect(assign).toHaveBeenLastCalledWith('http://127.0.0.1:5177/api/api/auth/oauth/naver/start?return_path=%2Fonboarding')
})
it.each(['google', 'naver'] as const)('uses the production origin override for %s independently of the API base', async provider => {
  vi.stubEnv('VITE_OAUTH_PUBLIC_ORIGIN', ' https://login.example.com/ ')
  vi.stubEnv('VITE_API_BASE_URL', '/proxy')
  vi.resetModules()
  const { startSocialLogin: start } = await import('./session')
  const assign = vi.fn()
  vi.stubGlobal('window', { location: { origin: 'http://localhost:5177', assign } })
  start(provider)
  expect(assign).toHaveBeenCalledWith(`https://login.example.com/api/api/auth/oauth/${provider}/start?return_path=%2Fdashboard`)
  const { env } = await import('../config/env')
  expect(env.apiBaseUrl).toBe('/proxy')
})
it('shares in-flight exchanges and sends only code plus cookies', async () => {
  const payload = { session, returnPath: '/dashboard', isNewUser: false }
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload)))
  vi.stubGlobal('fetch', fetcher)
  const first = exchangeCode('one-time')
  expect(exchangeCode('one-time')).toBe(first)
  expect(await first).toEqual(payload)
  expect(fetcher).toHaveBeenCalledOnce()
  expect(fetcher.mock.calls[0]).toEqual(['/api/api/auth/oauth/exchange', {
    method: 'POST', credentials: 'include', referrerPolicy: 'no-referrer', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: 'one-time' }),
  }])
  expect(getSession()).toBeNull()
})
it.each([
  { session, returnPath: 'https://evil.example', isNewUser: false },
  { session: { ...session, token: 'invalid' }, returnPath: '/dashboard', isNewUser: false },
  { session, returnPath: '/dashboard' },
])('rejects malformed responses and non-allowlisted destinations', async payload => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))))
  await expect(exchangeCode('invalid-response')).rejects.toThrow()
  expect(getSession()).toBeNull()
})
it('keeps the stored session across module reloads and revokes it on logout', async () => {
  storeSession(session)
  vi.resetModules()
  const reloaded = await import('./session')
  expect(reloaded.getSession()).toEqual(session)
  const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', fetcher)
  await reloaded.logout()
  expect(fetcher.mock.calls[0][1].headers.Authorization).toBe(`Bearer ${session.token}`)
  expect(reloaded.getSession()).toBeNull()
  expect(localStorage.getItem('jupjup.auth.session')).toBeNull()
})
it('clears the local session even when logout cannot reach the server', async () => {
  storeSession(session)
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
  const { logout } = await import('./session')
  await expect(logout()).rejects.toThrow('offline')
  expect(getSession()).toBeNull()
})
