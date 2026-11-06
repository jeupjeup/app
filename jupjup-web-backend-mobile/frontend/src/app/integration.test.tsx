import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { detailFixture } from '@/test/fixtures'
import type { MetadataClassification } from '@/shared/api/contracts'
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('automatically applies results, edits with ETag, reanalyzes in auto mode, searches in server rank order, then deletes', async () => {
  const detail = structuredClone(detailFixture)
  detail.summary = { effective: null, source: null, ai: null, user: null }
  let deleted = false
  let jobStatus = 'awaiting_confirmation'
  const writes: { path: string; body: Record<string, unknown>; headers: Headers }[] = []
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const path = new URL(url, 'http://127.0.0.1').pathname
    if (path === '/api/v1/collections') return new Response(JSON.stringify({ items: [] }), { headers: { 'Content-Type': 'application/json' } })
    const method = options?.method || 'GET'
    const body = options?.body ? JSON.parse(String(options.body)) : {}
    const response = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json', ETag: `"content:c_test:${detail.revision}"` } })
    if (method !== 'GET') writes.push({ path, body, headers: new Headers(options?.headers) })
    if (path === '/api/v1/contents' && method === 'GET') return response({ items: [], next_cursor: null, has_more: false })
    if (path === '/api/v1/contents/c_test' && method === 'GET') return deleted ? response({ error: { code: 'NOT_FOUND', message: '찾을 수 없어요.' } }, 404) : response(detail)
    if (path === '/api/v1/jobs/j_test') return response({ id: 'j_test', status: jobStatus, current_stage: 'confirm', result_content_id: 'c_test', next_run_at: null, error: null, steps: [{ stage: 'analyze', status: 'succeeded', attempts: 1 }] })
    if (path.endsWith(':review')) {
      expect(body).toEqual({ candidate_id: 'candidate_1', decision: 'approve' })
      // The queued persist job finishes before the next detail read.
      detail.status = 'ready'; detail.summary = { effective: '승인된 요약', ai: '승인된 요약', source: 'ai', user: null }; jobStatus = 'succeeded'
      detail.analysis.candidate = null
      return response({ content_id: detail.id, job_id: 'j_test', candidate_id: body.candidate_id, decision: 'approve', status: 'queued' }, 202)
    }
    if (path === '/api/v1/contents/c_test' && method === 'PATCH') {
      expect(new Headers(options?.headers).get('If-Match')).toBe(`"content:c_test:${detail.revision}"`)
      if (body.summary) detail.summary = { ...detail.summary, effective: body.summary, user: body.summary, source: 'user' }
      if (body.detail_tags) detail.detail_tags.effective = { ...detail.detail_tags.effective, ...body.detail_tags }
      detail.revision++
      return response(detail)
    }
    if (path.endsWith(':reanalyze')) {
      expect(body).toEqual({ automation_level: 'auto', mode: 'snapshot' })
      // Auto analysis persists directly, retaining user overrides without a review.
      detail.status = 'ready'; detail.analysis.automation_level = 'auto'; detail.analysis.candidate = null; jobStatus = 'succeeded'
      detail.summary.ai = '재분석한 AI 요약'
      return response({ content_id: 'c_test', result_content_id: 'c_test', job_id: 'j_test', status: 'queued', deduplicated: false }, 202)
    }
    if (path === '/api/v1/search') return response({ results: ['c_test', 'c_second'].map((id, i) => ({ content_id: id, rank: i + 1, title: i === 0 ? '서버 첫 번째 결과' : '서버 두 번째 결과', summary: '요약', platform: 'web', content_type: 'webpage', saved_at: i === 0 ? '2020-01-01T00:00:00Z' : '2026-01-01T00:00:00Z', source_url: null, original_available: true, representative_tags: [], match_reasons: [{ type: 'keyword', field: 'summary', terms: ['검증'] }] })), applied_relaxations: [], degraded: false, empty_state: null })
    if (method === 'DELETE') { deleted = true; return new Response(null, { status: 204 }) }
    throw new Error(`Unexpected request ${method} ${path}`)
  })
  vi.stubGlobal('fetch', fetcher)
  vi.stubGlobal('confirm', () => true)
  window.history.replaceState(null, '', '/contents/c_test')
  const user = userEvent.setup()
  render(<App />)
  await screen.findByText('승인된 요약')
  expect(screen.queryByRole('button', { name: '제안 승인' })).not.toBeInTheDocument()
  expect(screen.queryByText('원문은 메모와 별개')).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: '저장된 원문' })).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '요약과 태그 수정' }))
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  expect(screen.getByRole('dialog').closest('.app-shell')).toBeNull()
  const input = screen.getByLabelText('사용자 요약 · 1~1000자')
  await user.clear(input); await user.type(input, '검증한 사용자 요약')
  const topics = screen.getByLabelText('주제 · 최대 10개, 각 30자')
  await user.clear(topics); await user.type(topics, '새 주제')
  await user.click(screen.getByRole('button', { name: '저장하기' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(writes.find(write => write.path === '/api/v1/contents/c_test')?.body).toEqual({ summary: '검증한 사용자 요약', detail_tags: { topics: ['새 주제'] } })
  expect(detail.detail_tags.effective.locations).toEqual([{ name: '서울' }])
  await user.click(screen.getByRole('button', { name: '저장 원문 재분석' }))
  await waitFor(() => expect(writes.some(write => write.path.endsWith(':reanalyze'))).toBe(true))
  await waitFor(() => expect(screen.getByRole('button', { name: '저장 원문 재분석' })).toBeEnabled())
  expect(writes.filter(write => write.path.endsWith(':review'))).toHaveLength(1)
  expect(detail.status).toBe('ready')
  expect(screen.getByText('검증한 사용자 요약')).toBeInTheDocument()
  expect(detail.detail_tags.effective).toMatchObject({ topics: ['새 주제'], locations: [{ name: '서울' }] })
  await user.click(screen.getByRole('button', { name: '콘텐츠 검색' }))
  const search = await screen.findByRole('textbox', { name: '검색어' })
  await user.type(search, '검증')
  await user.click(screen.getByRole('button', { name: '다시 찾기' }))
  await screen.findByText('서버 첫 번째 결과')
  expect(screen.getAllByRole('heading', { level: 3 }).map(node => node.textContent)).toEqual(['서버 첫 번째 결과', '서버 두 번째 결과'])
  await user.click(screen.getAllByRole('link', { name: '서버 첫 번째 결과 상세 보기' })[0])
  await user.click(await screen.findByRole('button', { name: '콘텐츠 삭제' }))
  await waitFor(() => expect(deleted).toBe(true))
  expect(writes.find(write => write.path.endsWith(':reanalyze'))?.headers.get('Idempotency-Key')).toBeTruthy()
})

it('saves replacement text from a failed video without editing or deleting its original', async () => {
  const detail = structuredClone(detailFixture)
  detail.status = 'analysis_failed'
  detail.source = { kind: 'url', url: 'https://www.youtube.com/watch?v=test', original_status: 'unknown' }
  detail.analysis.candidate = null
  detail.snapshot = null
  detail.analysis.source_text_available = false
  detail.analysis.source_text_reason = 'missing_snapshot'
  const writes: { method: string; body: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    const path = new URL(url, 'http://127.0.0.1').pathname
    if (path === '/api/v1/collections') return new Response(JSON.stringify({ items: [] }), { headers: { 'Content-Type': 'application/json' } })
    const response = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
    if (options?.method === 'POST') {
      writes.push({ method: options.method, body: JSON.parse(String(options.body)) })
      return response({ content_id: 'c_new', result_content_id: 'c_new', job_id: 'j_new', status: 'queued', deduplicated: false })
    }
    if (path === '/api/v1/contents') return response({ items: [], next_cursor: null, has_more: false })
    if (path.startsWith('/api/v1/jobs/')) return response({ id: 'j_test', status: 'failed', current_stage: 'fetch', result_content_id: 'c_test', error: { code: 'SOURCE_TEXT_UNAVAILABLE', message: '공개 자막을 가져오지 못했어요.' }, steps: [] })
    return response(detail)
  }))
  window.history.replaceState(null, '', '/contents/c_test')
  const user = userEvent.setup()
  render(<App />)
  await user.type(await screen.findByLabelText('영상 내용·자막 텍스트'), '직접 확인한 영상 본문입니다.')
  expect(screen.getByRole('button', { name: '저장 원문 재분석' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: '다시 정리하기' })).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '입력한 텍스트로 새 항목 저장' }))
  await waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0].body).toMatchObject({ source: { kind: 'text', text: '직접 확인한 영상 본문입니다.' } })
  expect(detail.source.url).toContain('youtube.com')
})

it.each([false, true])('shows legacy rejected source repair immediately and preserves user layers (%s)', async hasUser => {
  const detail = structuredClone(detailFixture)
  detail.id = `c_legacy_${hasUser}`
  detail.status = 'analysis_rejected'
  detail.platform = 'youtube'
  detail.source = { kind: 'url', url: 'https://www.youtube.com/watch?v=wpk7AM6FPRc', original_status: 'unknown' }
  detail.title = 'C++ 강의'
  detail.analysis = { ...detail.analysis, source_text_available: false, source_text_reason: 'legacy_watch_snapshot', analysis_pending: false, candidate: null }
  // The API projects user-only effective values and retains the original snapshot.
  detail.summary = { effective: hasUser ? '직접 작성한 요약' : null, user: hasUser ? '직접 작성한 요약' : null, source: hasUser ? 'user' : null, ai: null }
  detail.representative_tags = { effective: hasUser ? ['사용자태그'] : [], user: hasUser ? ['사용자태그'] : [], ai: [], hidden_ai: [] }
  detail.detail_tags = { effective: hasUser ? { schema_version: 1, topics: ['사용자주제'] } : { schema_version: 1 }, ai: { schema_version: 1 }, user_patch: null }
  detail.snapshot = { text: '보존된 페이지 정보와 약관' }
  const writes: { path: string; body: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    const path = new URL(url, 'http://127.0.0.1').pathname
    if (path === '/api/v1/collections') return new Response(JSON.stringify({ items: [] }), { headers: { 'Content-Type': 'application/json' } })
    const response = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json', ETag: '"content:c_test:1"' } })
    if (options?.method && options.method !== 'GET') {
      writes.push({ path, body: JSON.parse(String(options.body)) })
      return response({ content_id: 'c_new', result_content_id: 'c_new', job_id: null, status: 'queued', deduplicated: false })
    }
    if (path === '/api/v1/contents') return response({ items: [{ id: detail.id, revision: 1, status: detail.status, hidden: false, title: detail.title, platform: 'youtube', content_type: 'video', summary: detail.summary.effective, representative_tags: detail.representative_tags.effective, saved_at: detail.saved_at, source_url: detail.source.url, original_available: true, analysis_pending: false }], next_cursor: null, has_more: false })
    if (path.startsWith('/api/v1/jobs/')) return response({ id: 'j_test', status: 'rejected', current_stage: 'confirm', result_content_id: 'c_test', error: null, steps: [] })
    return response(detail)
  }))
  window.history.replaceState(null, '', `/contents/${detail.id}`)
  const user = userEvent.setup()
  render(<App />)
  expect(await screen.findByRole('heading', { name: '영상 본문 확보 실패' })).toBeInTheDocument()
  expect(screen.getByText(/사용자가 직접 수정한 요약과 태그는 보존하여 표시/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '저장 원문 재분석' })).toBeDisabled()
  expect(screen.queryByText('보존된 YouTube 페이지 원문 펼치기')).not.toBeInTheDocument()
  expect(screen.queryByText('보존된 페이지 정보와 약관')).not.toBeInTheDocument()
  if (hasUser) {
    expect(screen.getByText('직접 작성한 요약')).toBeInTheDocument()
    expect(screen.getByText('#사용자태그')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '요약과 태그 수정' }))
    expect(screen.getByLabelText('사용자 요약 · 1~1000자')).toHaveValue('직접 작성한 요약')
    expect(screen.getByLabelText('대표 태그 · 최대 15개')).toHaveValue('사용자태그')
    expect(screen.getByLabelText('주제 · 최대 10개, 각 30자')).toHaveValue('사용자주제')
    await user.click(screen.getByRole('button', { name: '취소' }))
  }
  expect(writes).toEqual([])
  await user.type(screen.getByLabelText('영상 내용·자막 텍스트'), '직접 확인한 C++ 강의 자막입니다.')
  await user.click(screen.getByRole('button', { name: '입력한 텍스트로 새 항목 저장' }))
  await waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0]).toMatchObject({ path: '/api/v1/contents', body: { source: { kind: 'text', text: '직접 확인한 C++ 강의 자막입니다.' } } })
  expect(detail.snapshot.text).toBe('보존된 페이지 정보와 약관')
  // The same list projection renders a card with only the preserved user layers.
  await user.click(screen.getByRole('button', { name: /^보관함$/ }))
  const title = await screen.findByRole('heading', { name: 'C++ 강의', level: 3 })
  const card = title.closest('article')!
  expect(card.textContent).not.toContain('잘못된 AI')
  if (hasUser) expect(card.textContent).toContain('직접 작성한 요약')
})

it('uses server source validity for a normal YouTube transcript without inspecting text', async () => {
  const detail = structuredClone(detailFixture)
  detail.id = 'c_transcript'
  detail.status = 'ready'
  detail.source = { kind: 'url', url: 'https://www.youtube.com/watch?v=wpk7AM6FPRc', original_status: 'unknown' }
  detail.analysis = { ...detail.analysis, source_text_available: true, source_text_reason: null, analysis_pending: false, candidate: null, latest_job_id: null }
  detail.snapshot = { text: '자막에서 YouTube 약관과 Google LLC를 설명합니다.' }
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(detail), { headers: { 'Content-Type': 'application/json' } })))
  window.history.replaceState(null, '', '/contents/c_transcript')
  render(<App />)
  expect(await screen.findByRole('button', { name: '저장 원문 재분석' })).toBeEnabled()
  expect(screen.queryByRole('heading', { name: '영상 본문 확보 실패' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('영상 내용·자막 텍스트')).not.toBeInTheDocument()
  expect(screen.queryByText(detail.snapshot.text)).not.toBeInTheDocument()
})

it('explicitly refreshes YouTube metadata with retry idempotency, preserves edits and shows actual results', async () => {
  const detail = structuredClone(detailFixture)
  detail.id = detail.canonical_id = 'c_metadata_refresh'
  detail.status = 'analysis_rejected'; detail.platform = 'youtube'
  detail.source = { kind: 'url', url: 'https://www.youtube.com/watch?v=wpk7AM6FPRc', original_status: 'unknown' }
  detail.analysis = { ...detail.analysis, candidate: null, latest_job_id: null, source_text_available: false, source_text_reason: 'legacy_watch_snapshot' }
  const keys: string[] = []
  let tries = 0
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    const path = new URL(url, 'http://127.0.0.1').pathname
    if (path === '/api/v1/collections') return new Response(JSON.stringify({ items: [] }), { headers: { 'Content-Type': 'application/json' } })
    const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
    if (options?.method === 'POST') {
      expect(path).toBe('/api/v1/contents/c_metadata_refresh:reanalyze')
      expect(JSON.parse(String(options.body))).toEqual({ automation_level: 'auto', mode: 'youtube_metadata' })
      keys.push(new Headers(options.headers).get('Idempotency-Key')!)
      if (++tries === 1) return response({ error: { code: 'INTERNAL', message: '수집 서버 실패' } }, 500)
      detail.analysis.metadata = {
        source_scope: 'youtube_metadata', basis: 'title_description', classifier: 'local-metadata-rules-v1',
        metadata: { title: 'C++ 강의', description: '실제 강의 설명\nhttps://github.com/example/cpp', title_source: 'videoDetails.title', description_source: 'videoDetails.shortDescription', description_status: 'available', title_truncated: false, description_truncated: false, transcript_reason: 'not_requested' },
        representative_tags: ['C++', '강의'], detail_tags: { schema_version: 1, category: 'tech' }, evidence: [{ field: 'title', source_span: 'C++', tag: 'C++' }],
      }
      detail.status = 'ready'
      return response({ content_id: detail.id, result_content_id: detail.id, job_id: 'j_metadata', status: 'queued', deduplicated: false }, 202)
    }
    if (path === '/api/v1/contents') return response({ items: [], next_cursor: null, has_more: false })
    return response(detail)
  }))
  window.history.replaceState(null, '', '/contents/c_metadata_refresh')
  const user = userEvent.setup()
  render(<App />)
  const button = await screen.findByRole('button', { name: '제목·설명 가져오기/분류' })
  expect(button).toBeEnabled()
  await user.click(button)
  await screen.findByText('수집 서버 실패')
  await user.click(button)
  await screen.findByText(/카테고리: 기술/)
  expect(screen.getByRole('note')).toHaveTextContent('YouTube 제목·설명 분류는 로컬 규칙')
  expect(screen.getByRole('note')).toHaveTextContent('mock 분석은 시험용 고정 예시')
  expect(keys[0]).toBeTruthy(); expect(keys[1]).toBe(keys[0])
  expect(screen.getByText('사용자 요약')).toBeInTheDocument()
  expect(screen.getByText(/영상 전체의 요약이 아닙니다/)).toBeInTheDocument()
})

it('retries automatic metadata approval without losing user edits, source or multiple collections', async () => {
  const detail = structuredClone(detailFixture)
  detail.platform = 'youtube'
  detail.source = { kind: 'url', url: 'https://www.youtube.com/watch?v=test', original_status: 'unknown' }
  detail.analysis.latest_job_id = null
  detail.analysis.source_text_reason = 'legacy_watch_snapshot'
  detail.analysis.source_text_available = false
  detail.collection_ids = ['col_one', 'col_two']
  const metadata: MetadataClassification = {
    source_scope: 'youtube_metadata' as const, basis: 'title_description' as const, classifier: 'local-metadata-rules-v1',
    metadata: { title: 'C++ 강의', description: '실제 강의 설명', title_source: 'videoDetails.title', description_source: 'videoDetails.shortDescription', description_status: 'available' as const, title_truncated: false, description_truncated: false, transcript_reason: 'not_requested' },
    representative_tags: ['C++'], detail_tags: { schema_version: 1 as const, category: 'tech' }, evidence: [{ field: 'title' as const, source_span: 'C++', tag: 'C++' }],
  }
  detail.analysis.candidate = { ...detail.analysis.candidate!, ...metadata }
  const original = structuredClone(detail)
  let reviews = 0
  const writes: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
    const path = new URL(url, 'http://127.0.0.1').pathname
    const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
    if (options?.method && options.method !== 'GET') {
      writes.push(path)
      expect(path).toBe('/api/v1/contents/c_test:review')
      expect(JSON.parse(String(options.body))).toEqual({ candidate_id: 'candidate_1', decision: 'approve' })
      if (++reviews === 1) return response({ error: { code: 'INTERNAL', message: '자동 적용 서버 실패' } }, 500)
      // A worker completes the approved queued job before the next GET.
      detail.status = 'ready'; detail.analysis.candidate = null; detail.analysis.metadata = metadata
      return response({ content_id: detail.id, job_id: 'j_test', candidate_id: 'candidate_1', decision: 'approve', status: 'queued' }, 202)
    }
    if (path === '/api/v1/collections') return response({ items: ['col_one', 'col_two'].map((id, i) => ({ id, name: i ? '공부' : '자료', color: '#DDB8E5', content_count: 1, created_at: detail.saved_at, updated_at: detail.saved_at })) })
    if (path === '/api/v1/contents') return response({ items: [], next_cursor: null, has_more: false })
    if (path === '/api/v1/contents/c_test') return response(detail)
    throw new Error(`Unexpected request ${path}`)
  }))
  window.history.replaceState(null, '', '/contents/c_test')
  const user = userEvent.setup()
  render(<App />)
  await screen.findByText('자동 적용 서버 실패')
  expect(reviews).toBe(1)
  expect(detail).toEqual(original)
  expect(screen.queryByRole('button', { name: '제안 승인' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '제안 거절' })).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '자동 정리 다시 시도' }))
  await screen.findByText(/카테고리: 기술/)
  expect(screen.queryByRole('region', { name: '분석 결과 자동 적용' })).not.toBeInTheDocument()
  expect(screen.getByText('사용자 요약')).toBeInTheDocument()
  expect(screen.getByText('#사용자 태그')).toBeInTheDocument()
  expect(screen.getByRole('checkbox', { name: '자료' })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: '공부' })).toBeChecked()
  expect(screen.getAllByRole('link', { name: '자료' }).length).toBeGreaterThan(0)
  expect(screen.getByText('실제 강의 설명')).toBeInTheDocument()
  expect(screen.getByText(/영상 전체의 요약이 아닙니다/)).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '요약과 태그 수정' }))
  expect(screen.getByLabelText('사용자 요약 · 1~1000자')).toHaveValue('사용자 요약')
  expect(screen.getByLabelText('주제 · 최대 10개, 각 30자')).toHaveValue('주제')
  expect(detail.summary).toEqual(original.summary)
  expect(detail.detail_tags).toEqual(original.detail_tags)
  expect(detail.snapshot).toEqual(original.snapshot)
  expect(detail.collection_ids).toEqual(original.collection_ids)
  expect(writes).toHaveLength(2)
})

it.each(['missing snapshot', 'source error'])('does not offer failed snapshot retry with %s', async condition => {
  const detail = structuredClone(detailFixture)
  detail.id = condition === 'source error' ? 'c_error' : 'c_missing'; detail.analysis.latest_job_id = `job_${detail.id}`
  detail.status = 'analysis_failed'; detail.analysis.candidate = null; detail.analysis.source_text_available = true
  if (condition === 'missing snapshot') detail.snapshot = null
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const path = new URL(url, 'http://127.0.0.1').pathname
    const data = path.endsWith('/collections') ? { items: [] } : path.endsWith('/contents') ? { items: [], has_more: false, next_cursor: null } : path.includes('/jobs/') ? { id: 'j_test', status: 'failed', current_stage: 'fetch', result_content_id: 'c_test', error: condition === 'source error' ? { code: 'SOURCE_TEXT_UNAVAILABLE' } : null, steps: [] } : detail
    return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
  }))
  window.history.replaceState(null, '', `/contents/${detail.id}`)
  render(<App />)
  await screen.findByRole('heading', { name: '콘텐츠 정리' })
  if (condition === 'source error') await screen.findByText('정리를 마치지 못했어요. 저장한 콘텐츠는 그대로 보관되어 있어요.')
  expect(screen.queryByRole('button', { name: '다시 정리하기' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '저장 원문 재분석' })).toBeDisabled()
})
