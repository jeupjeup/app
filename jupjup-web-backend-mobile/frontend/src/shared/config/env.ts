const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') || ''

function oauthPublicOrigin(value = 'http://127.0.0.1:5177'): string {
  const input = value.trim()
  let url: URL
  try { url = new URL(input) } catch { throw new Error('Invalid VITE_OAUTH_PUBLIC_ORIGIN') }
  if (!/^https?:\/\//i.test(input) || /[\\\s]/.test(input)
    || !['http:', 'https:'].includes(url.protocol) || url.username || url.password
    || (url.protocol === 'http:' && !['127.0.0.1', 'localhost'].includes(url.hostname))
    || url.pathname !== '/' || input.includes('?') || input.includes('#')) {
    throw new Error('Invalid VITE_OAUTH_PUBLIC_ORIGIN: expected an HTTP(S) origin')
  }
  return url.origin
}

export const env = {
  apiBaseUrl,
  oauthPublicOrigin: oauthPublicOrigin(import.meta.env.VITE_OAUTH_PUBLIC_ORIGIN),
  userId: import.meta.env.VITE_DEV_USER_ID || 'u_frontend_dev',
} as const
