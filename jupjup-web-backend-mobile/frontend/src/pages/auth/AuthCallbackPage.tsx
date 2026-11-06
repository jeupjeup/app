import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { exchangeCode, storeSession } from '@/shared/auth/session'
import { Brand } from '@/shared/ui/Brand'
import styles from './AuthPage.module.css'

export function AuthCallbackPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const [params] = useState(() => new URLSearchParams(location.search))
  const code = params.get('code')
  const validCode = !params.has('error') && !!code && /^[A-Za-z0-9_-]{43}$/.test(code)
  const [error, setError] = useState(validCode ? '' : '로그인을 완료하지 못했어요. 다시 시도해 주세요.')
  useEffect(() => {
    const subscription = new AbortController()
    // Remove the one-time code/error from browser history before any async work.
    navigate('/auth/callback', { replace: true })
    if (!validCode || !code) return
    void exchangeCode(code).then(result => {
      if (subscription.signal.aborted) return
      storeSession(result.session)
      navigate(result.isNewUser ? '/onboarding' : result.returnPath, { replace: true })
    }).catch(() => {
      if (!subscription.signal.aborted) setError('로그인을 완료하지 못했어요. 다시 시도해 주세요.')
    })
    return () => subscription.abort()
  }, [navigate, code, validCode])
  return <main className={styles.callbackPage} aria-busy={!error}><Brand />
    <h1>{error ? '로그인을 다시 시도해 주세요' : '로그인을 완료하고 있어요'}</h1>
    {error ? <><p role="alert">{error}</p><Link to="/login">로그인으로 돌아가기</Link></> : <p role="status">잠시만 기다려 주세요.</p>}
  </main>
}
