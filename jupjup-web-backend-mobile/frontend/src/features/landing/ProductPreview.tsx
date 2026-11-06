import { useState } from 'react'
import type { CSSProperties } from 'react'
import styles from './ProductPreview.module.css'

type PreviewMode = 'save' | 'organize' | 'search'

const previewCopy: Record<PreviewMode, { title: string; caption: string }> = {
  save: {
    title: '발견한 콘텐츠, 한곳에 모아요.',
    caption: '영상과 게시물, 웹사이트까지 한 번에',
  },
  organize: {
    title: '쌓인 콘텐츠, 알아서 정리해요.',
    caption: '내용을 읽고 어울리는 컬렉션으로',
  },
  search: {
    title: '기억나는 말로 다시 찾아요.',
    caption: '정확한 제목이나 URL은 몰라도 괜찮아요',
  },
}

const items = [
  { title: '피그마 오토레이아웃 이해하기', source: 'YouTube', tone: 'blue' },
  { title: '여행 가기 전에 저장한 풍경', source: 'Instagram', tone: 'green' },
  { title: '타이포그래피 레퍼런스 모음', source: 'Website', tone: 'peach' },
] as const

export function ProductPreview() {
  const [mode, setMode] = useState<PreviewMode>('save')
  const copy = previewCopy[mode]

  return (
    <div className={styles.stage}>
      <div className={styles.backdrop} aria-hidden="true" />
      <div className={styles.surface} aria-hidden="true" />
      <section className={styles.window} aria-label="줍줍 저장소 제품 미리보기">
        <div className={styles.browserBar}>
          <div className={styles.dots} aria-hidden="true">
            <i />
            <i />
            <i />
          </div>
          <span>jupjup.app / archive</span>
        </div>
        <div className={styles.shell}>
          <aside className={styles.sidebar}>
            <strong>줍줍 저장소</strong>
            <button className={styles.activeSide} type="button">
              내 보관함
            </button>
            <button type="button">최근 저장</button>
            <button type="button">컬렉션</button>
            <small>내 컬렉션</small>
            <span>디자인 영감</span>
            <span>여행 리스트</span>
          </aside>
          <div className={styles.workspace}>
            <div className={styles.workspaceHead}>
              <div>
                <h2>{copy.title}</h2>
                <p>{copy.caption}</p>
              </div>
              <button type="button">+ 콘텐츠 추가</button>
            </div>

            <div className={styles.modeTabs} role="tablist" aria-label="제품 기능">
              {(['save', 'organize', 'search'] as const).map((value) => (
                <button
                  key={value}
                  className={mode === value ? styles.selectedTab : ''}
                  type="button"
                  role="tab"
                  aria-selected={mode === value}
                  onClick={() => setMode(value)}
                >
                  {value === 'save' && '간편한 저장'}
                  {value === 'organize' && 'AI 자동 정리'}
                  {value === 'search' && '자연어 검색'}
                </button>
              ))}
            </div>

            {mode === 'search' ? (
              <div className={styles.searchPanel}>
                <div className={styles.searchBox}>
                  <SearchIcon />
                  <span>예전에 봤던 피그마 오토레이아웃 설명 영상</span>
                </div>
                <p>기억과 가장 가까운 콘텐츠를 찾았어요.</p>
                <ContentCard item={items[0]} featured />
              </div>
            ) : (
              <div className={styles.grid}>
                {items.map((item, index) => (
                  <ContentCard
                    key={item.title}
                    item={item}
                    organized={mode === 'organize'}
                    delay={index}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}

function ContentCard({
  item,
  featured = false,
  organized = false,
  delay = 0,
}: {
  item: (typeof items)[number]
  featured?: boolean
  organized?: boolean
  delay?: number
}) {
  return (
    <article
      className={`${styles.card} ${featured ? styles.featuredCard : ''}`}
      style={{ '--item-delay': `${delay * 70}ms` } as CSSProperties}
    >
      <div className={`${styles.art} ${styles[item.tone]}`} aria-hidden="true">
        <span />
        <i />
        <b />
      </div>
      <div className={styles.cardCopy}>
        <strong>{item.title}</strong>
        <span>{item.source}</span>
        {organized && <em>AI 분류 완료</em>}
      </div>
    </article>
  )
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m15.5 15.5 5 5" />
    </svg>
  )
}
