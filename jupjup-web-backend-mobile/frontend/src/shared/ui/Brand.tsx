import { Link } from 'react-router-dom'
import styles from './Brand.module.css'

type BrandProps = {
  compact?: boolean
}

export function Brand({ compact = false }: BrandProps) {
  return (
    <Link
      className={`${styles.brand} ${compact ? styles.compact : ''}`}
      to="/"
      aria-label="줍줍 저장소 홈"
    >
      <svg viewBox="0 0 40 40" aria-hidden="true">
        <rect x="5" y="10" width="25" height="25" rx="9" fill="#ffb466" />
        <path
          d="M12 7h16a5 5 0 0 1 5 5v16a5 5 0 0 1-5 5H12a5 5 0 0 1-5-5V12a5 5 0 0 1 5-5Z"
          stroke="currentColor"
          strokeWidth="2.8"
          fill="#fff8ee"
        />
        <path
          d="m15 20 4 4 7-8"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="30.5" cy="9.5" r="4.7" fill="#ff9f43" />
      </svg>
      <span>
        줍줍<span className={styles.dot}>.</span>저장소
      </span>
    </Link>
  )
}

export function ArrowIcon() {
  return (
    <svg className={styles.icon} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12h14m-7-7 7 7-7 7" />
    </svg>
  )
}
