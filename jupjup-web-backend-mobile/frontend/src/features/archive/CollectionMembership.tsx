import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AccessibleDialog } from './AccessibleDialog'
import { RequestState } from './RequestState'
import { useCollections, useContents, useRefreshArchive } from './queries'
import { setMembership } from '@/shared/api/collections'
import { errorMessage } from '@/shared/api/client'

export function useMembershipAction() {
  const lock = useRef(false)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  const refresh = useRefreshArchive()
  const change = async (collection: string, content: string, included: boolean) => {
    if (lock.current) return
    lock.current = true; setBusy(true); setFailure('')
    try { await setMembership(collection, content, included); await refresh() }
    catch (error) { setFailure(errorMessage(error)) }
    finally { lock.current = false; setBusy(false) }
  }
  return { busy, failure, change }
}

export function ContentCollectionPicker({ contentId, collectionIds }: { contentId: string; collectionIds: string[] }) {
  const query = useCollections()
  const { busy, failure, change } = useMembershipAction()
  return <div className="content-collection-picker"><strong>컬렉션 소속</strong><RequestState loading={query.isPending} error={query.error} retry={() => void query.refetch()} />
    <div className="detail-collection-line">{query.data?.items.filter(c => collectionIds.includes(c.id)).map(c => <Link key={c.id} to={`/collections/${c.id}`}>{c.name}</Link>)}</div>
    {query.data?.items.length ? <fieldset disabled={busy} className="membership-list"><legend>여러 컬렉션에 담을 수 있어요.</legend>{query.data.items.map(c => <label key={c.id}><input type="checkbox" checked={collectionIds.includes(c.id)} onChange={event => void change(c.id, contentId, event.target.checked)} /><span>{c.name}</span></label>)}</fieldset> : query.isSuccess && <p>아직 컬렉션이 없어요. <Link to="/collections?create=true">컬렉션 만들기</Link></p>}
    {busy && <p role="status">소속 저장 중…</p>}{failure && <p role="alert">{failure}</p>}
  </div>
}

export function CollectionContentPicker({ collectionId, onClose }: { collectionId: string; onClose: () => void }) {
  const query = useContents()
  const { busy, failure, change } = useMembershipAction()
  const rows = query.data?.pages.flatMap(p => p.items) || []
  return <AccessibleDialog titleId="collectionContentsTitle" className="collection-manage-dialog" onClose={() => { if (!busy) onClose() }}><div className="dialog-header"><h2 id="collectionContentsTitle">콘텐츠 추가 및 제외</h2><button className="button" disabled={busy} onClick={onClose}>닫기</button></div><p>보관함의 숨기지 않은 콘텐츠를 최신순으로 불러와요. 다른 컬렉션 소속은 유지됩니다.</p><RequestState loading={query.isPending} error={query.error} retry={() => void query.refetch()} /><fieldset className="membership-list" disabled={busy}><legend>콘텐츠 선택</legend>{rows.map(row => <label key={row.id}><input type="checkbox" checked={row.collection_ids?.includes(collectionId) || false} onChange={event => void change(collectionId, row.id, event.target.checked)} /><span>{row.title || row.source_url || '제목 없는 콘텐츠'}<small>{new Date(row.saved_at).toLocaleDateString('ko-KR')}</small></span></label>)}</fieldset>{query.isSuccess && !rows.length && <p>담을 콘텐츠가 없어요. 먼저 보관함에 저장해 주세요.</p>}{failure && <p role="alert">{failure}</p>}{busy && <p role="status">소속 저장 중…</p>}{query.hasNextPage && <button className="button" disabled={busy || query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>{query.isFetchingNextPage ? '불러오는 중…' : '보관함 콘텐츠 더 불러오기'}</button>}<div className="dialog-footer"><button className="button primary" disabled={busy} onClick={onClose}>완료</button></div></AccessibleDialog>
}
