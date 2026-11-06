import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, requestWithHeaders } from './client'
import { listContents, SubmissionKeys } from './contents'
afterEach(() => vi.unstubAllGlobals())
describe('API transport contract', () => {
  it('sends mutation headers without anonymous development identity; reads ETag', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'c_1' }), { headers: { 'Content-Type': 'application/json', ETag: '"content:c_1:4"' } }))
    vi.stubGlobal('fetch', fetcher)
    const result = await requestWithHeaders('/v1/contents/c_1', { method: 'PATCH', body: { summary: '사용자 요약' }, headers: { 'If-Match': '"content:c_1:3"' } })
    expect(result.etag).toBe('"content:c_1:4"')
    const [url, options] = fetcher.mock.calls[0]
    expect(url).toBe('/api/v1/contents/c_1')
    expect(options.headers.get('X-User-Id')).toBeNull()
    expect(options.headers.get('If-Match')).toBe('"content:c_1:3"')
    expect(JSON.parse(options.body)).toEqual({ summary: '사용자 요약' })
  })
  it('handles empty 204 without trying to parse JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    expect(await api.delete('/v1/contents/c_1')).toBeUndefined()
  })
  it('preserves nested error code and details for conflict handling', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'VERSION_CONFLICT', message: '변경된 내용', details: { field: 'revision' } } }), { status: 409, headers: { 'Content-Type': 'application/json' } })))
    await expect(api.get('/v1/contents/c_1')).rejects.toMatchObject({ status: 409, code: 'VERSION_CONFLICT', message: '변경된 내용', details: { field: 'revision' } })
  })
  it('rejects non-JSON errors without treating an API outage as an empty list', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>offline</html>', { status: 502 })))
    await expect(listContents()).rejects.toBeInstanceOf(ApiError)
  })
  it('sends repeated filters and opaque cursor safely', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{}', { headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetcher)
    await listContents({ platform: ['web', 'local'], cursor: 'a+b/=' })
    const params = new URL(fetcher.mock.calls[0][0], 'http://127.0.0.1').searchParams
    expect(params.getAll('platform')).toEqual(['web', 'local'])
    expect(params.get('cursor')).toBe('a+b/=')
  })
  it('reuses a key only for the same operation and body until success', async () => {
    const keys = new SubmissionKeys()
    const first = await keys.keyFor('create', { text: '원문' })
    expect(await keys.keyFor('create', { text: '원문' })).toBe(first)
    expect(await keys.keyFor('create', { text: '다른 원문' })).not.toBe(first)
    expect(await keys.keyFor('reanalyze', { text: '원문' })).not.toBe(first)
    keys.clear()
    expect(await keys.keyFor('create', { text: '원문' })).not.toBe(first)
  })
})

it('attaches stored Bearer session and removes development identity', async () => {
  const { storeSession, clearSession } = await import('@/shared/auth/session')
  const token = 'b'.repeat(64)
  storeSession({ token, expiresAt: '2099-01-01T00:00:00Z', user: { id: '12345678-1234-1234-1234-123456789abc', email: 'u@example.com', nickname: 'User', notificationsEnabled: false } })
  const fetcher = vi.fn().mockResolvedValue(new Response('{}', { headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetcher)
  try {
    await api.get('/v1/contents', { headers: { 'X-User-Id': 'u_spoof' } })
    expect(fetcher.mock.calls[0][1].headers.get('Authorization')).toBe(`Bearer ${token}`)
    expect(fetcher.mock.calls[0][1].headers.has('X-User-Id')).toBe(false)
  } finally { clearSession() }
})
it('does not add development fallback to explicit Bearer requests', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response('{}', { headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetcher)
  await api.get('/v1/contents', { headers: { Authorization: 'Bearer invalid' } })
  expect(fetcher.mock.calls[0][1].headers.has('X-User-Id')).toBe(false)
})
