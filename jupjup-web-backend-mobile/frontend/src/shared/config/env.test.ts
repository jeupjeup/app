import { afterEach, expect, it, vi } from 'vitest'

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules() })

it('defaults OAuth to the canonical local origin and keeps API requests relative', async () => {
  vi.stubEnv('VITE_OAUTH_PUBLIC_ORIGIN', undefined)
  vi.resetModules()
  const { env } = await import('./env')
  expect(env.oauthPublicOrigin).toBe('http://127.0.0.1:5177')
  expect(env.apiBaseUrl).toBe('/api')
})

it.each([
  '', '/api', '//example.com', 'not a URL', 'javascript:alert(1)',
  'https://user:password@example.com', 'https://example.com/path',
  'https://example.com?next=evil', 'https://example.com#fragment',
  'https://example.com?', 'https://example.com#',
  'https://example.com\\evil', 'https://exa\nmple.com',
  'http://example.com', 'https://example.com:invalid',
])('rejects unsafe or malformed OAuth origin %j', async value => {
  vi.stubEnv('VITE_OAUTH_PUBLIC_ORIGIN', value)
  vi.resetModules()
  await expect(import('./env')).rejects.toThrow('Invalid VITE_OAUTH_PUBLIC_ORIGIN')
})
