import { useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { platformNames, typeNames } from '@/features/archive/presentation'
import { ArchiveCard } from '@/features/archive/ArchiveCard'
import { ArchiveFilterBar } from '@/features/archive/ArchiveFilterBar'
import { ArchivePageHeader } from '@/features/archive/ArchivePageHeader'
import { searchToItem } from '@/features/archive/adapters'
import { RequestState } from '@/features/archive/RequestState'
import { searchContents } from '@/shared/api/contents'
import { useSessionScope } from '@/shared/auth/session'
export function SearchResultsPage() {
  const scope = useSessionScope()
  const [params, setParams] = useSearchParams()
  const query = params.get('q') || ''
  const [draft, setDraft] = useState(query)
  const [source, setSource] = useState('')
  const [type, setType] = useState('')
  const result = useQuery({ queryKey: ['search', scope, query, source, type], enabled: !!query.trim(), queryFn: ({ signal }) => searchContents({ query, limit: 30, filters: { ...(source ? { platforms: [source] } : {}), ...(type ? { content_types: [type] } : {}) } }, signal) })
  const submit = (event: FormEvent) => { event.preventDefault(); if (draft.trim()) setParams({ q: draft.trim() }) }
  return <main className="content archive-content search-results-page">
    <ArchivePageHeader title="검색 결과" description="기존 자연어 검색 API의 관련도 순서입니다. 컬렉션·분석 상태 필터는 서버 미지원입니다." />
    <form className="results-search" onSubmit={submit}><input value={draft} onChange={event => setDraft(event.target.value)} placeholder="기억나는 대로 검색해 보세요" aria-label="검색어" /><button className="button primary">다시 찾기</button></form>
    <ArchiveFilterBar ariaLabel="검색 필터" fields={[
      { key: 'source', layout: 'list', label: '출처', value: source, onChange: setSource, options: [{ value: '', label: '전체 출처' }, ...['instagram', 'youtube', 'kakaotalk', 'news', 'blog', 'x', 'web', 'local'].map(value => ({ value, label: platformNames[value] }))] },
      { key: 'type', layout: 'tiles', label: '유형', value: type, onChange: setType, options: [{ value: '', label: '전체 유형' }, ...['post', 'short_video', 'video', 'article', 'paper', 'image', 'message', 'webpage'].map(value => ({ value, label: typeNames[value] }))] },
    ]} onReset={() => { setSource(''); setType('') }}>
    <RequestState loading={!!query && result.isPending} error={result.error} retry={() => void result.refetch()} />
    {!query && <p>검색어를 입력해 주세요.</p>}
    {result.data && <><div className="search-query-summary"><h2>“{query}”</h2><strong>반환된 결과 {result.data.results.length}개</strong></div>{result.data.degraded && <p role="status">검색의 일부 기능이 제한된 상태입니다.</p>}{result.data.applied_relaxations.length > 0 && <p>적용된 검색 조건 완화: {'더 넓은 조건으로 찾은 결과가 포함되어 있어요.'}</p>}<div className="content-grid search-result-grid">{result.data.results.map((row, index) => <ArchiveCard key={row.content_id} item={searchToItem(row)} index={index} reason={row.match_reasons.map(reason => reason.detail || `${({title:'제목', summary:'요약', tags:'태그', detail:'세부 정보'}[reason.field || ''] || '일치하는 표현')}: ${(reason.terms || []).join(', ')}`).join(' · ')} />)}</div>{!result.data.results.length && <section className="search-empty"><h2>일치하는 콘텐츠를 찾지 못했어요.</h2><p>{result.data.empty_state?.message || '검색어와 필터를 바꾸어 다시 찾아보세요.'}</p></section>}</>}
    </ArchiveFilterBar>
  </main>
}
