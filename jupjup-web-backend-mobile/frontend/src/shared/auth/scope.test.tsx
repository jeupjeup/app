import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { useCollections } from '@/features/archive/queries'
import { clearSession, storeSession } from './session'

afterEach(() => { clearSession(); vi.unstubAllGlobals() })
it('switches archive queries to the active account without showing the previous account cache', async () => {
  const session = { token: 'a'.repeat(64), expiresAt: '2099-01-01T00:00:00Z', user: { id: '12345678-1234-1234-1234-123456789abc', email: 'a@example.com', nickname: 'A', notificationsEnabled: false } }
  storeSession(session)
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (_url, options) => new Response(JSON.stringify({ items: [{ id: options.headers.get('Authorization') }] }), { headers: { 'Content-Type': 'application/json' } })))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const hook = renderHook(() => useCollections(), { wrapper })
  await waitFor(() => expect(hook.result.current.data?.items[0].id).toBe(`Bearer ${session.token}`))
  act(() => storeSession({ ...session, token: 'b'.repeat(64), user: { ...session.user, id: 'abcdef12-1234-1234-1234-123456789abc' } }))
  expect(hook.result.current.data?.items[0]?.id).not.toBe(`Bearer ${session.token}`)
  await waitFor(() => expect(hook.result.current.data?.items[0].id).toBe(`Bearer ${'b'.repeat(64)}`))
  hook.unmount()
  client.clear()
})
