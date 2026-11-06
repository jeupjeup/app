import { Link } from 'react-router-dom'
import { Brand } from '@/shared/ui/Brand'
import styles from './NotFoundPage.module.css'

export function NotFoundPage() {
  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <Brand compact />
      </header>

      <section className={styles.content}>
        <div className={styles.archive} aria-hidden="true">
          <span className={styles.backSheet} />
          <span className={styles.middleSheet} />
          <span className={styles.frontSheet}>
            <strong>404</strong>
            <i />
            <i />
          </span>
        </div>

        <div className={styles.copy}>
          <h1>이 페이지는<br />아직 줍지 못했어요.</h1>
          <p>주소가 바뀌었거나, 사라진 페이지예요.<br />보관함으로 돌아가 저장한 콘텐츠를 둘러보세요.</p>
          <div className={styles.actions}>
            <Link className={styles.primary} to="/dashboard">내 보관함으로</Link>
            <Link className={styles.secondary} to="/">첫 화면으로</Link>
          </div>
        </div>
      </section>

      <p className={styles.footnote}>길을 잃은 콘텐츠도 다시 찾을 수 있도록</p>
    </main>
  )
}
