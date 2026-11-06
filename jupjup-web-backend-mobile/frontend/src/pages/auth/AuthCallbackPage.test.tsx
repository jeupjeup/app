import { StrictMode } from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { getSession } from '@/shared/auth/session'
import { AuthCallbackPage } from './AuthCallbackPage'
const session = { token: 'a'.repeat(64), expiresAt: '2099-01-01T00:00:00Z', user: { id: '12345678-1234-1234-1234-123456789abc', email: 'u@example.com', nickname: 'User', notificationsEnabled: false } }
const code = 'c'.repeat(43)
beforeEach(() => localStorage.clear())
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
function Probe() {
  const location = useLocation()
  const navigate = useNavigate()
  return <><span data-testid="location">{location.pathname + location.search}</span><button onClick={() => navigate(-1)}>뒤로</button></>
}
function mount(query = `?code=${code}`) {
  return render(<StrictMode><MemoryRouter initialEntries={['/login', `/auth/callback${query}`]}><Probe /><Routes>
    <Route path="/auth/callback" element={<AuthCallbackPage />} />
    <Route path="/dashboard" element={<h1>Dashboard</h1>} />
    <Route path="/onboarding" element={<h1>Onboarding</h1>} />
    <Route path="/login" element={<h1>Login</h1>} />
  </Routes></MemoryRouter></StrictMode>)
}
it.each([true, false])('exchanges once under StrictMode, stores session and replaces history (new=%s)', async isNewUser => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ session, returnPath: '/dashboard', isNewUser })))
  vi.stubGlobal('fetch', fetcher)
  mount()
  await screen.findByRole('heading', { name: isNewUser ? 'Onboarding' : 'Dashboard' })
  expect(fetcher).toHaveBeenCalledOnce()
  expect(fetcher.mock.calls[0][0]).toBe('/api/api/auth/oauth/exchange')
  expect(getSession()).toEqual(session)
  expect(screen.getByTestId('location').textContent).not.toContain(code)
  await userEvent.click(screen.getByRole('button', { name: '뒤로' }))
  await screen.findByRole('heading', { name: 'Login' })
})
it.each(['?error=access_denied', '', '?code=invalid'])('scrubs invalid callback %s without exchange', async query => {
  const fetcher = vi.fn()
  vi.stubGlobal('fetch', fetcher)
  mount(query)
  expect(await screen.findByRole('alert')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(/^\/auth\/callback$/))
  expect(fetcher).not.toHaveBeenCalled()
  expect(getSession()).toBeNull()
})
it('announces exchange failure without storing session or exposing provider text', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private-provider-error', { status: 400 })))
  mount()
  expect(await screen.findByRole('alert')).toHaveTextContent('다시 시도')
  expect(screen.queryByText('private-provider-error')).not.toBeInTheDocument()
  expect(getSession()).toBeNull()
})
it('shows progress and scrubs code while exchange is pending', async () => {
  vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})))
  mount(`?code=${'p'.repeat(43)}`)
  expect(screen.getByRole('status')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(/^\/auth\/callback$/))
})
