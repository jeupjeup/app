import type { ReactNode } from 'react'
import './collection-cards.css'
import { Link } from 'react-router-dom'
import { ContentArt } from '@/features/jupjup-dashboard/components/ContentCard'
import { Icon } from '@/features/jupjup-dashboard/components/Icon'
import { typeIcon } from '@/features/jupjup-dashboard/data/demo'
import { statusLabel as serverStatusLabel } from './adapters'
import { useArchiveStore } from './ArchiveStore'
import { useArchiveUi } from './ArchiveLayout'
import { contentTypeName, effectiveSavedAt, type ArchiveItem } from './archiveData'


export function ArchiveCard({ item, index = 0, reason, footerAction }: { item: ArchiveItem; index?: number; reason?: string; footerAction?: ReactNode }) {
  const { collections, favorites, toggleFavorite } = useArchiveStore()
  const { notify } = useArchiveUi()
  const favorite = favorites.includes(item.id)
  const onFavorite = () => { try { toggleFavorite(item.id); notify(favorite ? '즐겨찾기에서 제외했어요.' : '즐겨찾기에 추가했어요.') } catch { notify('즐겨찾기를 저장하지 못했어요. 브라우저 저장 공간을 확인해 주세요.') } }
  const itemCollections = item.collectionIds.map((id) => collections.find((collection) => collection.id === id)).filter(Boolean)
  return <article className="content-card archive-card" style={{ animationDelay: `${Math.min(index, 7) * 35}ms` }}>
    <Link className="card-art" to={`/contents/${item.id}`} aria-label={`${item.title} 상세 보기`}>
      <ContentArt kind={item.art} />
      <span className="type-pill"><Icon name={typeIcon[item.contentType]} />{item.contentLabel || contentTypeName[item.contentType]}</span>
      <span className={`analysis-chip ${item.analysisStatus}`}>{item.serverStatus ? serverStatusLabel(item.serverStatus) : '검색 결과'}</span>
    </Link>
    <button type="button" className={`favorite${favorite ? ' active' : ''}`} onClick={onFavorite} aria-label={favorite ? '즐겨찾기 해제' : '즐겨찾기 추가'} aria-pressed={favorite}><Icon name="star" /></button>
    <div className="card-body">
      <div className="card-source"><span className={`platform-mark ${item.source.toLowerCase()}`} />{item.source}<span className="dot-separator">·</span>{new Date(effectiveSavedAt(item)).toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric' })}</div>
      <Link to={`/contents/${item.id}`}><h3 className="card-title">{item.title}</h3></Link>
      {item.analysisStatus === 'analyzing' ? <div className="card-skeleton" aria-label="AI 분석 중"><span /><span /></div> : item.analysisStatus === 'failed' ? <p className="card-summary failed">내용을 분석하지 못했어요. 상세에서 원문이나 자막을 직접 저장해 주세요.</p> : <p className="card-summary">{item.aiSummary}</p>}
      {reason && <p className="match-reason"><Icon name="search" small />{reason}</p>}
      <div className="card-bottom"><div className="tags">{item.primaryTags.slice(0, 2).map((tag) => <span key={tag} className="tag">#{tag}</span>)}{!item.primaryTags.length && <span className="tag muted-tag">태그 없음</span>}</div><Link className="card-more" to={`/contents/${item.id}`} aria-label={`${item.title} 상세 보기`}><Icon name="chevron" /></Link></div>
      <div className={footerAction ? "card-context-row" : undefined}>{!!itemCollections.length && <div className="card-collections">{itemCollections.slice(0, 2).map((collection) => <span key={collection!.id}><i style={{ background: collection!.color }} />{collection!.name}</span>)}{itemCollections.length > 2 && <span title={itemCollections.slice(2).map(c => c!.name).join(", ")}>외 {itemCollections.length - 2}개</span>}</div>}
      {footerAction}
      </div>
    </div>
  </article>
}
