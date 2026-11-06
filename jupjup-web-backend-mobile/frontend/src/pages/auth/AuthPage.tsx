import { useState } from 'react'
import { storeSession, startSocialLogin, type Session } from '@/shared/auth/session'
import { api, errorMessage } from '@/shared/api/client'
import { Link, useNavigate } from 'react-router-dom'
import { Brand } from '@/shared/ui/Brand'
import styles from './AuthPage.module.css'

type AuthMode = 'login' | 'signup'
type Provider = 'naver' | 'google'

const providers: Array<{
  id: Provider
  label: string
  className: string
}> = [
  { id: 'naver', label: '네이버로 계속하기', className: 'naver' },
  { id: 'google', label: 'Google로 계속하기', className: 'google' },
]

export function AuthPage({ mode }: { mode: AuthMode }) {
  const isSignup = mode === 'signup'
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [consent, setConsent] = useState(false)
  const [emailBusy, setEmailBusy] = useState(false)
  const submitEmail = async (event: React.FormEvent) => {
    event.preventDefault()
    if (emailBusy || loading) return
    setEmailBusy(true); setError('')
    try {
      const session = await api.post<Session>(`/api/auth/${isSignup ? 'register' : 'login'}`, isSignup
        ? { email: email.trim(), password, nickname: nickname.trim(), requiredConsent: consent, notificationsEnabled: false }
        : { email: email.trim(), password })
      storeSession(session)
      navigate('/dashboard', { replace: true })
    } catch (cause) { setError(errorMessage(cause)) }
    finally { setEmailBusy(false) }
  }
  const [loading, setLoading] = useState<Provider | null>(null)
  const [error, setError] = useState('')
  const start = (provider: Provider) => {
    if (loading) return
    setLoading(provider)
    setError('')
    try { startSocialLogin(provider, isSignup) } catch {
      setLoading(null)
      setError('로그인 페이지를 열지 못했어요. 다시 시도해 주세요.')
    }
  }

  return (
    <main className={styles.page}>
      <section className={styles.authPanel} aria-labelledby="auth-title">
        <div className={styles.authInner}>
          <header className={styles.authHeader}>
            <Brand />
            <Link className={styles.homeLink} to="/">
              홈으로
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M5 12h14m-6-6 6 6-6 6" />
              </svg>
            </Link>
          </header>

          <div className={styles.authContent}>
            <div className={styles.copy}>
              <h1 id="auth-title">
                {isSignup ? (
                  <>마음에 드는 건,<br />이제 줍줍하세요.</>
                ) : (
                  <>모아둔 것들,<br />다시 꺼내볼까요?</>
                )}
              </h1>
              <p className={styles.description}>
                {isSignup
                  ? '여기저기 흩어진 글과 영상, 게시물까지. 마음에 드는 콘텐츠를 한곳에 모아 나만의 저장소를 만들어 보세요.'
                  : '저장해 둔 콘텐츠가 그대로 기다리고 있어요. 기억나는 말로 찾고, 필요한 순간 다시 꺼내보세요.'}
              </p>
            </div>

            <div className={styles.signInArea}>
              <form className={styles.emailForm} onSubmit={submitEmail}>
                <label>이메일<input type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} /></label>
                <label>비밀번호<input type="password" autoComplete={isSignup ? 'new-password' : 'current-password'} required value={password} onChange={event => setPassword(event.target.value)} /></label>
                {isSignup && <>
                  <label>닉네임<input required maxLength={25} value={nickname} onChange={event => setNickname(event.target.value)} /></label>
                  <label><input type="checkbox" required checked={consent} onChange={event => setConsent(event.target.checked)} /> 필수 이용약관 및 개인정보 처리에 동의합니다.</label>
                </>}
                <button className={styles.provider} disabled={emailBusy || !!loading} type="submit">{emailBusy ? '연결 중…' : isSignup ? '이메일로 회원가입' : '이메일로 로그인'}</button>
              </form>
              <div className={styles.providerList}>
                {providers.map((provider) => (
                  <button
                    disabled={emailBusy || loading !== null}
                    onClick={() => start(provider.id)}
                    aria-busy={loading === provider.id}
                    type="button"
                    key={provider.id}
                    className={`${styles.provider} ${styles[provider.className]}`}
                  >
                    <SocialIcon provider={provider.id} />
                    <span>{loading === provider.id ? '연결 중…' : provider.label}</span>
                  </button>
                ))}
              </div>

              <p className={styles.legal}>Google 또는 네이버 계정으로 계속할 수 있어요.</p>
              {loading && <p role="status">로그인 페이지로 이동하고 있어요.</p>}
              {error && <p role="alert">{error}</p>}


              <p className={styles.switchMode}>
                {isSignup ? '이미 계정이 있나요?' : '아직 계정이 없나요?'}{' '}
                <Link to={isSignup ? '/login' : '/signup'}>
                  {isSignup ? '로그인' : '회원가입'}
                  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M5 12h14m-6-6 6 6-6 6" />
                  </svg>
                </Link>
              </p>
            </div>
          </div>
        </div>
      </section>

      <aside className={styles.storyPanel} aria-label="줍줍저장소 소개">
        <div className={styles.storyContent}>
          <div className={styles.storyCopy}>
            <h2>마음에 드는 건 모아두고,<br />필요할 땐 쉽게 찾고.</h2>
            <p className={styles.storyDescription}>
              여기저기 흩어진 글과 영상, 게시물까지.<br />한곳에 모아두고, 기억나는 말로 다시 찾아보세요.
            </p>
          </div>

          <div className={styles.preview} aria-hidden="true">
            <div className={styles.previewHeader}>
              <div className={styles.previewHeading}>
                <span className={styles.previewMark}>✳</span>
                <span>내 보관함</span>
              </div>
              <span className={styles.previewHeaderMeta}>나의 모든 발견</span>
            </div>

            <div className={styles.previewSearch}>
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="10.7" cy="10.7" r="6.7" />
                <path d="m16 16 4.3 4.3" />
              </svg>
              <span>그때 본 오토레이아웃 영상</span>
              <span className={styles.previewSearchKey}>↵</span>
            </div>

            <div className={styles.previewListTitle}>
              <span>이런 콘텐츠를 찾았어요</span>
              <span className={styles.previewResultCount}>2개의 발견</span>
            </div>

            <div className={styles.previewResult}>
              <div className={`${styles.previewThumb} ${styles.previewThumbVideo}`}>
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="m9 6 9 6-9 6V6Z" />
                </svg>
              </div>
              <div className={styles.previewResultText}>
                <span>YouTube · 디자인 참고</span>
                <strong>피그마 오토레이아웃 한 번에 이해하기</strong>
                <p>간격, 정렬, 반응형 레이아웃을 정리한 영상</p>
              </div>
              <span className={styles.previewResultArrow}>↗</span>
            </div>

            <div className={styles.previewResult}>
              <div className={`${styles.previewThumb} ${styles.previewThumbArticle}`}>
                <span>Aa</span>
              </div>
              <div className={styles.previewResultText}>
                <span>Website · 아티클</span>
                <strong>더 유연한 UI를 위한 레이아웃 노트</strong>
                <p>예전에 저장해 둔 웹 디자인 가이드</p>
              </div>
              <span className={styles.previewResultArrow}>↗</span>
            </div>
          </div>

          <p className={styles.storyNote}>흩어져 있던 정보가, 다시 나의 아이디어가 되는 순간.</p>
        </div>
      </aside>
    </main>
  )
}

function SocialIcon({ provider }: { provider: Provider }) {
  if (provider === 'naver') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5 4h5.1l4.3 6.3V4H19v16h-5l-4.4-6.4V20H5V4Z" fill="currentColor" />
      </svg>
    )
  }

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20.7 12.2c0-.7-.1-1.4-.2-2H12v3.7h4.9a4.2 4.2 0 0 1-1.8 2.7V19h3c1.7-1.6 2.6-4 2.6-6.8Z" fill="#4285F4" />
      <path d="M12 21c2.4 0 4.5-.8 6-2.1l-3-2.3c-.8.6-1.9.9-3 .9-2.3 0-4.3-1.6-5-3.7H4v2.4A9 9 0 0 0 12 21Z" fill="#34A853" />
      <path d="M7 13.8a5.4 5.4 0 0 1 0-3.6V7.8H4a9 9 0 0 0 0 8.4l3-2.4Z" fill="#FBBC05" />
      <path d="M12 6.5c1.3 0 2.5.5 3.5 1.4L18.1 5A8.7 8.7 0 0 0 12 3a9 9 0 0 0-8 4.8l3 2.4c.7-2.1 2.7-3.7 5-3.7Z" fill="#EA4335" />
    </svg>
  )
}
