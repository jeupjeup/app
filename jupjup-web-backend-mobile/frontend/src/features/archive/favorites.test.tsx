import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { clearSession, storeSession } from '@/shared/auth/session'
import { ContentDetailPage } from '@/pages/archive/ContentDetailPage'
import { ContentsPage } from '@/pages/archive/ContentsPage'
import { detailFixture } from '@/test/fixtures'
import { ArchiveLayout } from './ArchiveLayout'
import { ArchiveStoreProvider } from './ArchiveStore'

const session = { token: 'a'.repeat(64), expiresAt: '2099-01-01T00:00:00Z', user: { id: '12345678-1234-1234-1234-123456789abc', email: 'a@example.com', nickname: 'A', notificationsEnabled: false } }
afterEach(() => { cleanup(); clearSession(); localStorage.clear(); vi.unstubAllGlobals() })
it('keeps favorites consistent across detail, paginated list, account switches and relogin', async () => {
  storeSession(session)
  const detail = structuredClone(detailFixture)
  detail.status = 'ready'; detail.title = '저장한 자료'; detail.analysis.candidate = null; detail.analysis.latest_job_id = null
  const row = { id: 'c_test', revision: 1, status: 'ready', hidden: false, title: '저장한 자료', platform: 'local', content_type: 'webpage', summary: null, representative_tags: [], saved_at: '2026-11-05T00:00:00Z', updated_at: null, source_url: null, original_available: true, analysis_pending: false, collection_ids: [] }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const parsed = new URL(url, 'http://localhost')
    const data = parsed.pathname.endsWith('/collections') ? { items: [] } : parsed.pathname.endsWith('/c_test') ? detail : parsed.searchParams.has('cursor') ? { items: [row], has_more: false, next_cursor: null } : { items: [], has_more: true, next_cursor: 'next' }
    return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const user = userEvent.setup()
  render(<QueryClientProvider client={client}><ArchiveStoreProvider><MemoryRouter initialEntries={['/contents/c_test']}><Routes><Route element={<ArchiveLayout />}><Route path="/contents/:contentId" element={<ContentDetailPage />} /><Route path="/contents" element={<ContentsPage />} /></Route></Routes></MemoryRouter></ArchiveStoreProvider></QueryClientProvider>)
  await screen.findByRole('heading', { name: '저장한 자료' })
  await user.click(within(screen.getByRole('main')).getByRole('button', { name: '즐겨찾기' }))
  await user.click(screen.getByRole('button', { name: '즐겨찾기' }))
  const card = await screen.findByRole('button', { name: '즐겨찾기 해제' })
  expect(card).toHaveAttribute('aria-pressed', 'true')
  act(() => storeSession({ ...session, token: 'b'.repeat(64), user: { ...session.user, id: 'abcdef12-1234-1234-1234-123456789abc' } }))
  await waitFor(() => expect(screen.queryByRole('button', { name: '즐겨찾기 해제' })).not.toBeInTheDocument())
  act(() => clearSession())
  act(() => storeSession(session))
  await waitFor(() => expect(screen.getByRole('button', { name: '즐겨찾기 해제' })).toHaveAttribute('aria-pressed', 'true'))
  await user.click(screen.getAllByRole('link', { name: '저장한 자료 상세 보기' })[0])
  expect(await within(await screen.findByRole('main')).findByRole('button', { name: '즐겨찾기 해제' })).toHaveAttribute('aria-pressed', 'true')
  await user.click(screen.getByRole('button', { name: '즐겨찾기' }))
  await user.click(await screen.findByRole('button', { name: '즐겨찾기 해제' }))
  expect(screen.queryByRole('button', { name: '즐겨찾기 해제' })).not.toBeInTheDocument()
  client.clear()
})
