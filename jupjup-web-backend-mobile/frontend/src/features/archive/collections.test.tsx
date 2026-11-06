import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { CollectionsPage } from '@/pages/archive/CollectionsPage'
import { CollectionDetailPage } from '@/pages/archive/CollectionDetailPage'
import { ArchiveLayout } from './ArchiveLayout'
import { ArchiveStoreProvider } from './ArchiveStore'
import { ContentCollectionPicker } from './CollectionMembership'
import { useContent } from './queries'
import { detailFixture } from '@/test/fixtures'
import type { Collection } from '@/shared/api/collections'
import type { PropsWithChildren } from 'react'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
const sample: Collection = { id: 'col_one', name: '자료', color: '#DDB8E5', content_count: 0, created_at: '2026-11-05T00:00:00Z', updated_at: '2026-11-05T00:00:00Z' }
function wrapper(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } } })
  return function Wrapper({ children }: PropsWithChildren) { return <QueryClientProvider client={client}><ArchiveStoreProvider><MemoryRouter initialEntries={[path]}><Routes><Route element={<ArchiveLayout />}><Route path="*" element={children} /></Route></Routes></MemoryRouter></ArchiveStoreProvider></QueryClientProvider> }
}

it('creates, preserves conflicting input, renames, pages selectable contents, removes membership and deletes while retaining content', async () => {
  const collections: Collection[] = []
  const memberships = new Set<string>()
  let conflict = true
  const writes: string[] = []
  const row = (id: string) => ({ id, revision: 0, status: 'ready', hidden: false, title: id === 'c_later' ? '다음 페이지 자료' : '첫 자료', platform: 'local', content_type: 'message', summary: null, representative_tags: [], saved_at: '2026-11-05T00:00:00Z', updated_at: null, source_url: null, original_available: true, analysis_pending: false, collection_ids: memberships.has(id) ? ['col_one'] : [] })
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const parsed = new URL(url, 'http://127.0.0.1')
    const path = parsed.pathname.replace('/api', '')
    const method = options?.method || 'GET'
    if (method !== 'GET') writes.push(`${method} ${path}`)
    if (path === '/v1/collections' && method === 'POST') {
      const body = JSON.parse(String(options?.body))
      if (conflict) { conflict = false; return response({ error: { code: 'COLLECTION_NAME_CONFLICT', message: '같은 이름의 컬렉션이 있어요.' } }, 409) }
      collections.push({ ...sample, name: body.name }); return response(collections[0], 201)
    }
    if (path === '/v1/collections') return response({ items: collections })
    if (path === '/v1/collections/col_one' && method === 'PATCH') { collections[0].name = JSON.parse(String(options?.body)).name; return response(collections[0]) }
    if (path === '/v1/collections/col_one' && method === 'DELETE') { collections.length = 0; memberships.clear(); return new Response(null, { status: 204 }) }
    if (path === '/v1/collections/col_one') return response({ ...collections[0], content_count: memberships.size })
    if (path.startsWith('/v1/collections/col_one/contents/')) {
      const id = path.split('/').at(-1)!
      if (method === 'PUT') memberships.add(id); else memberships.delete(id)
      return new Response(null, { status: 204 })
    }
    if (path === '/v1/contents') {
      if (parsed.searchParams.has('collection_id')) return response({ items: [...memberships].map(row), next_cursor: null, has_more: false })
      const later = parsed.searchParams.has('cursor')
      return response({ items: [row(later ? 'c_later' : 'c_first')], next_cursor: later ? null : 'opaque+cursor', has_more: !later })
    }
    throw new Error(`unexpected ${method} ${path}`)
  })
  vi.stubGlobal('fetch', fetcher); vi.stubGlobal('confirm', () => true)
  const user = userEvent.setup()
  render(<Routes><Route path="/collections" element={<CollectionsPage />} /><Route path="/collections/:collectionId" element={<CollectionDetailPage />} /></Routes>, { wrapper: wrapper('/collections') })
  await screen.findByText('아직 만든 컬렉션이 없어요.')
  await user.click(screen.getAllByRole('button', { name: '컬렉션 만들기' }).at(-1)!)
  await user.type(screen.getByLabelText('컬렉션 이름'), '읽을 자료')
  await user.click(screen.getByRole('button', { name: '만들기' }))
  await screen.findByText('같은 이름의 컬렉션이 있어요.')
  expect(screen.getByLabelText('컬렉션 이름')).toHaveValue('읽을 자료')
  await user.click(screen.getByRole('button', { name: '만들기' }))
  await screen.findByRole('heading', { name: '읽을 자료' })
  await screen.findByText('아직 담긴 콘텐츠가 없어요.')
  await user.click(screen.getByRole('button', { name: '컬렉션 관리' }))
  await user.clear(screen.getByLabelText('컬렉션 이름')); await user.type(screen.getByLabelText('컬렉션 이름'), '개발 자료')
  await user.click(screen.getByRole('button', { name: '이름·색상 저장' }))
  await screen.findByRole('heading', { name: '개발 자료' })
  await user.click(screen.getByRole('button', { name: '콘텐츠 추가 및 제외' }))
  const dialog = screen.getByRole('dialog')
  await user.click(await within(dialog).findByRole('checkbox', { name: /첫 자료/ }))
  await waitFor(() => expect(memberships.has('c_first')).toBe(true))
  await user.click(within(dialog).getByRole('button', { name: '보관함 콘텐츠 더 불러오기' }))
  await user.click(await within(dialog).findByRole('checkbox', { name: /다음 페이지 자료/ }))
  await waitFor(() => expect(memberships.has('c_later')).toBe(true))
  await user.click(within(dialog).getByRole('button', { name: '완료' }))
  await screen.findByText('다음 페이지 자료')
  expect(screen.getByText(/콘텐츠 2개/)).toBeInTheDocument()
  await user.click(screen.getAllByRole('button', { name: '이 컬렉션에서 제외' })[0])
  await waitFor(() => expect(memberships.size).toBe(1))
  await user.click(screen.getByRole('button', { name: '컬렉션 관리' }))
  await user.click(screen.getByRole('button', { name: '컬렉션 삭제' }))
  await screen.findByText('아직 만든 컬렉션이 없어요.')
  expect(writes).toContain('PUT /v1/collections/col_one/contents/c_later')
  expect(writes.some(w => w.startsWith('DELETE /v1/contents'))).toBe(false)
  expect(writes.some(w => w.startsWith('PATCH /v1/contents'))).toBe(false)
})

it('shows server failure with retry and never treats it as an empty collection list', async () => {
  let failing = true
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url.includes('/collections') ? failing ? response({ error: { code: 'INTERNAL', message: '목록 조회 실패' } }, 500) : response({ items: [] }) : response({ items: [], has_more: false, next_cursor: null })))
  const user = userEvent.setup()
  render(<CollectionsPage />, { wrapper: wrapper('/collections') })
  await screen.findByText('목록 조회 실패')
  expect(screen.queryByText('아직 만든 컬렉션이 없어요.')).not.toBeInTheDocument()
  failing = false
  await user.click(screen.getByRole('button', { name: '다시 확인' }))
  await screen.findByText('아직 만든 컬렉션이 없어요.')
})

it('edits multiple content memberships through PUT/DELETE without modifying user content', async () => {
  const detail = structuredClone(detailFixture)
  detail.collection_ids = ['col_one']
  let failDelete = true
  const writes: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    const path = new URL(url, 'http://127.0.0.1').pathname
    if (options?.method) {
      writes.push(`${options.method} ${path}`)
      if (options.method === 'DELETE' && failDelete) { failDelete = false; return response({ error: { code: 'INTERNAL', message: '소속 저장 실패' } }, 500) }
      const id = path.includes('col_two') ? 'col_two' : 'col_one'
      detail.collection_ids = options.method === 'PUT' ? [...detail.collection_ids, id] : detail.collection_ids.filter(c => c !== id)
      return new Response(null, { status: 204 })
    }
    if (path.endsWith('/collections')) return response({ items: [sample, { ...sample, id: 'col_two', name: '공부' }] })
    if (path.endsWith('/contents/c_test')) return response(detail)
    return response({ items: [], has_more: false, next_cursor: null })
  }))
  function DetailPicker() {
    const query = useContent('c_test')
    const data = query.data?.data
    return data && 'source' in data ? <ContentCollectionPicker contentId={data.id} collectionIds={data.collection_ids} /> : null
  }
  const user = userEvent.setup()
  render(<DetailPicker />, { wrapper: wrapper('/contents/c_test') })
  expect(await screen.findByRole('checkbox', { name: '자료' })).toBeChecked()
  await user.click(screen.getByRole('checkbox', { name: '공부' }))
  await waitFor(() => expect(screen.getByRole('checkbox', { name: '공부' })).toBeChecked())
  expect(screen.getByRole('checkbox', { name: '자료' })).toBeChecked()
  await user.click(screen.getByRole('checkbox', { name: '자료' }))
  await screen.findByText('소속 저장 실패')
  expect(screen.getByRole('checkbox', { name: '자료' })).toBeChecked()
  await user.click(screen.getByRole('checkbox', { name: '자료' }))
  await waitFor(() => expect(screen.getByRole('checkbox', { name: '자료' })).not.toBeChecked())
  expect(detail.summary).toEqual(detailFixture.summary)
  expect(writes).toEqual(['PUT /api/v1/collections/col_two/contents/c_test', 'DELETE /api/v1/collections/col_one/contents/c_test', 'DELETE /api/v1/collections/col_one/contents/c_test'])
})

it('blocks duplicate create requests and closing the dialog while the server is pending', async () => {
  const { CollectionEditor } = await import('./CollectionEditor')
  let complete!: (value: Response) => void
  const pending = new Promise<Response>(resolve => { complete = resolve })
  let posts = 0
  vi.stubGlobal('fetch', vi.fn(async (_url: string, options?: RequestInit) => {
    if (options?.method === 'POST') { posts++; return pending }
    return response({ items: [], next_cursor: null, has_more: false })
  }))
  const close = vi.fn()
  const saved = vi.fn()
  const user = userEvent.setup()
  render(<CollectionEditor onClose={close} onSaved={saved} />, { wrapper: wrapper('/collections') })
  await user.type(screen.getByLabelText('컬렉션 이름'), '새 자료')
  await user.dblClick(screen.getByRole('button', { name: '만들기' }))
  expect(posts).toBe(1)
  expect(screen.getByRole('button', { name: '저장 중…' })).toBeDisabled()
  expect(screen.getByRole('radio', { name: '라벤더' })).toBeDisabled()
  expect(screen.getByLabelText('사용자 지정 색상 값')).toBeDisabled()
  expect(screen.getByRole('button', { name: '닫기' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '취소' })).toBeDisabled()
  await user.keyboard('{Escape}')
  expect(close).not.toHaveBeenCalled()
  complete(response(sample, 201))
  await waitFor(() => expect(saved).toHaveBeenCalledWith(sample.id))
})

it('sends the selected color on create and displays the server color on collection cards', async () => {
  const created: Collection = { ...sample, name: '읽을 자료', color: '#B3D5F1' }
  let posted: unknown
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    const path = new URL(url, 'http://127.0.0.1').pathname
    if (options?.method === 'POST') { posted = JSON.parse(String(options.body)); return response(created, 201) }
    if (path.endsWith('/collections')) return response({ items: [created] })
    if (path.endsWith('/collections/col_one')) return response(created)
    return response({ items: [], has_more: false, next_cursor: null })
  }))
  const user = userEvent.setup()
  render(<CollectionsPage />, { wrapper: wrapper('/collections') })
  await user.click(screen.getAllByRole('button', { name: '컬렉션 만들기' })[0])
  await user.type(screen.getByLabelText('컬렉션 이름'), '읽을 자료')
  await user.click(screen.getByRole('radio', { name: '하늘색' }))
  expect(screen.getByText('선택한 색상 #B3D5F1')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '만들기' }))
  await screen.findAllByText('읽을 자료')
  expect(posted).toEqual({ name: '읽을 자료', color: '#B3D5F1' })
  expect((document.querySelector('.folder-icon') as HTMLElement).style.background).toBe('rgba(179, 213, 241, 0.19)')
})

it('reopens a custom hex color, preserves it on failure, and retries the edited color', async () => {
  const custom = { ...sample, color: '#123ABC' }
  let patchBody: unknown
  let fail = true
  vi.stubGlobal('fetch', vi.fn(async (_url: string, options?: RequestInit) => {
    if (options?.method === 'PATCH') {
      patchBody = JSON.parse(String(options.body))
      if (fail) { fail = false; return response({ error: { code: 'INTERNAL', message: '저장 실패' } }, 500) }
      return response({ ...custom, ...(patchBody as Partial<Collection>) })
    }
    if (_url.includes('/collections')) return response({ items: [custom] })
    return response({ items: [], has_more: false, next_cursor: null })
  }))
  const user = userEvent.setup()
  render(<CollectionsPage />, { wrapper: wrapper('/collections') })
  await user.click(await screen.findByRole('button', { name: '자료 관리' }))
  expect(screen.getByRole('radio', { name: '사용자 지정 색상' })).toBeChecked()
  expect(screen.getByLabelText('사용자 지정 색상 값')).toHaveValue('#123abc')
  expect(screen.getByText('선택한 색상 #123ABC')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('사용자 지정 색상 값'), { target: { value: '#ABCDEF' } })
  await user.click(screen.getByRole('button', { name: '이름·색상 저장' }))
  await screen.findByText('저장 실패')
  expect(screen.getByLabelText('컬렉션 이름')).toHaveValue('자료')
  expect(screen.getByLabelText('사용자 지정 색상 값')).toHaveValue('#abcdef')
  expect(screen.getByText('선택한 색상 #ABCDEF')).toBeInTheDocument()
  expect(patchBody).toEqual({ name: '자료', color: '#ABCDEF' })
  await user.click(screen.getByRole('button', { name: '이름·색상 저장' }))
  await waitFor(() => expect(patchBody).toEqual({ name: '자료', color: '#ABCDEF' }))
})
