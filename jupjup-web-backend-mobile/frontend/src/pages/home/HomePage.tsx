import { useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import styles from './HomePage.module.css'

export function HomePage() {
  const frameRef = useRef<HTMLIFrameElement>(null)
  const navigate = useNavigate()

  function connectAuthRoutes() {
    const frameDocument = frameRef.current?.contentDocument

    if (!frameDocument || frameDocument.documentElement.dataset.authRoutesBound) {
      return
    }

    frameDocument.documentElement.dataset.authRoutesBound = 'true'
    frameDocument.addEventListener(
      'click',
      (event) => {
        const target = event.target

        if (!(target instanceof frameDocument.defaultView!.Element)) {
          return
        }

        const authLink = target.closest<HTMLAnchorElement>(
          '.nav-login, [data-demo-link]',
        )

        if (!authLink) {
          return
        }

        event.preventDefault()
        event.stopImmediatePropagation()

        const isLoginLink =
          authLink.classList.contains('nav-login') ||
          authLink.textContent?.includes('로그인')

        navigate(isLoginLink ? '/login' : '/signup')
      },
      true,
    )
  }

  return (
    <main className={styles.page}>
      <iframe
        ref={frameRef}
        className={styles.frame}
        src="/jupjup-landing.html"
        title="줍줍 저장소 랜딩페이지"
        onLoad={connectAuthRoutes}
      />
    </main>
  )
}
