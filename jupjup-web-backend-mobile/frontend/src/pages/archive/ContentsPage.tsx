import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { platformNames, typeNames } from '@/features/archive/presentation'
import { ArchiveCard } from '@/features/archive/ArchiveCard'
import { ArchiveFilterBar } from '@/features/archive/ArchiveFilterBar'
import { NaturalSearch } from '@/features/archive/NaturalSearch'
import { ArchivePageHeader } from '@/features/archive/ArchivePageHeader'
import { useArchiveStore } from '@/features/archive/ArchiveStore'
import { useContents } from '@/features/archive/queries'
import { rowToItem } from '@/features/archive/adapters'
import { RequestState } from '@/features/archive/RequestState'
import { useArchiveUi } from '@/features/archive/ArchiveLayout'
const PAGE_SIZE = 20
const types = ['post', 'short_video', 'video', 'article', 'paper', 'image', 'message', 'webpage']
const platforms = ['instagram', 'youtube', 'kakaotalk', 'news', 'blog', 'x', 'web', 'local']
export function ContentsPage() {
  const [params] = useSearchParams()
  const { openAdd } = useArchiveUi()
  const { settings, favorites } = useArchiveStore()
  const favoriteView = params.get('favorite') === 'true'
  const [display, setDisplay] = useState(settings.defaultDisplay)
  const [sort, setSort] = useState(settings.defaultSort === 'old' ? 'asc' : 'desc')
  const [type, setType] = useState('')
  const [source, setSource] = useState('')
  const [status, setStatus] = useState('')
  const [hidden, setHidden] = useState('false')
  const [pagination, setPagination] = useState({ scope: '', page: 0 })
  const recent = params.get('period') === 'recent'
  const old = params.get('period') === 'old'
  // Freeze a date boundary for this visit, rather than creating a new query key on every render.
  const [now] = useState(() => Date.now())
  const query = useContents({ platform: source || undefined, content_type: type || undefined, status: status || undefined, hidden, limit: String(PAGE_SIZE), sort: 'saved_at', order: sort, saved_from: recent ? new Date(now - 7 * 86400000).toISOString() : undefined, saved_to: old ? new Date(now - 30 * 86400000).toISOString() : undefined })
  const scope = JSON.stringify([favoriteView, recent, old, type, source, status, hidden, sort])
  const page = pagination.scope === scope ? pagination.page : 0
  const matchingFavorites = favoriteView ? (query.data?.pages.flatMap(result => result.items).filter(item => favorites.includes(item.id)) || []) : []
  const { hasNextPage, isFetching, isFetchNextPageError, fetchNextPage } = query
  useEffect(() => {
    if (favoriteView && matchingFavorites.length <= (page + 1) * PAGE_SIZE && hasNextPage && !isFetching && !isFetchNextPageError) void fetchNextPage()
  }, [favoriteView, matchingFavorites.length, page, hasNextPage, isFetching, isFetchNextPageError, fetchNextPage])
  const maxFavoritePage = Math.max(0, Math.ceil(matchingFavorites.length / PAGE_SIZE) - 1)
  const visiblePage = favoriteView ? Math.min(page, maxFavoritePage) : page
  const items = (favoriteView ? matchingFavorites.slice(visiblePage * PAGE_SIZE, (visiblePage + 1) * PAGE_SIZE) : query.data?.pages[visiblePage]?.items || []).map(rowToItem)
  const hasNext = favoriteView ? matchingFavorites.length > (visiblePage + 1) * PAGE_SIZE : Boolean(query.data?.pages[visiblePage]?.has_more)
  const goNext = async () => {
    if (query.isFetchingNextPage) return
    if (!favoriteView && visiblePage + 1 >= (query.data?.pages.length || 0)) {
      const result = await query.fetchNextPage()
      if (result.isFetchNextPageError || !result.data?.pages[visiblePage + 1]) return
    }
    setPagination({ scope, page: visiblePage + 1 })
  }
  const reset = () => { setType(''); setSource(''); setStatus(''); setHidden('false') }
  return <main className="content archive-content">
    <ArchivePageHeader title={favoriteView ? '즐겨찾기' : recent ? '최근 저장' : old ? '오래된 콘텐츠' : '모든 콘텐츠'} description={favoriteView ? "다시 보고 싶은 콘텐츠를 모아봤어요. 즐겨찾기는 이 브라우저에 저장됩니다." : "저장한 콘텐츠를 모아보고, 원하는 조건으로 찾아보세요."} />
    {!favoriteView && !old && <div className="archive-home archive-list-search"><NaturalSearch /></div>}
    <ArchiveFilterBar ariaLabel="콘텐츠 필터와 보기 설정" onReset={reset} fields={[
      { key: 'type', layout: 'tiles', label: '유형', value: type, onChange: setType, options: [{ value: '', label: '전체 유형' }, ...types.map(value => ({ value, label: typeNames[value] }))] },
      { key: 'source', layout: 'list', label: '출처', value: source, onChange: setSource, options: [{ value: '', label: '전체 출처' }, ...platforms.map(value => ({ value, label: platformNames[value] }))] },
      { key: 'status', layout: 'chips', label: '분석 상태', value: status, onChange: setStatus, options: [{ value: '', label: '전체 상태' }, { value: 'pending', label: '분석 중' }, { value: 'awaiting_confirmation', label: '적용 확인 대기' }, { value: 'ready', label: '정리 완료' }, { value: 'analysis_failed', label: '분석 실패' }, { value: 'analysis_rejected', label: '제안 미적용' }] },
      { key: 'hidden', layout: 'segments', label: '숨김', value: hidden, onChange: setHidden, options: [{ value: 'false', label: '숨김 제외' }, { value: 'true', label: '숨긴 콘텐츠' }, { value: 'all', label: '모두' }] },
      { key: 'sort', label: '정렬', value: sort, onChange: setSort, options: [{ value: 'desc', label: '최신순' }, { value: 'asc', label: '오래된순' }] },
    ]} actions={<div className="view-toggle"><button className={display === 'grid' ? 'active' : ''} onClick={() => setDisplay('grid')}>격자 보기</button><button className={display === 'list' ? 'active' : ''} onClick={() => setDisplay('list')}>목록 보기</button></div>}>
    <RequestState loading={query.isPending} error={query.error} retry={() => void query.refetch()} />
    {!!items.length && <div className={`content-grid archive-library-grid${display === 'list' ? ' is-list' : ''}`}>{items.map((item, index) => <ArchiveCard key={item.id} item={item} index={index} />)}</div>}
    {!query.isPending && !query.error && !(favoriteView && (query.hasNextPage || query.isFetching)) && !items.length && <div className="empty-state archive-empty"><h3>{favoriteView ? '즐겨찾기한 콘텐츠가 없어요.' : '조건에 맞는 콘텐츠가 없어요.'}</h3><button className="button primary" onClick={openAdd}>콘텐츠 저장하기</button></div>}
    {query.isFetchNextPageError && <div role="alert">다음 콘텐츠를 불러오지 못했어요. <button type="button" className="button" onClick={() => void query.fetchNextPage()}>다시 시도</button></div>}
    {(visiblePage > 0 || hasNext || (favoriteView && query.hasNextPage)) && <nav className="archive-pagination" aria-label="콘텐츠 페이지">
      <button type="button" onClick={() => setPagination({ scope, page: visiblePage - 1 })} disabled={visiblePage === 0}>이전</button>
      <span aria-current="page">{visiblePage + 1} 페이지</span>
      <button type="button" onClick={() => void goNext()} disabled={!hasNext || query.isFetchingNextPage}>{query.isFetchingNextPage ? '불러오는 중…' : '다음'}</button>
    </nav>}
    </ArchiveFilterBar>
  </main>
}
