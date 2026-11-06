import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Icon } from '@/features/jupjup-dashboard/components/Icon'
import { ArchiveCard } from '@/features/archive/ArchiveCard'
import { ArchivePageHeader } from '@/features/archive/ArchivePageHeader'
import { useCollection, useContents } from '@/features/archive/queries'
import { RequestState } from '@/features/archive/RequestState'
import { CollectionEditor } from '@/features/archive/CollectionEditor'
import { CollectionContentPicker, useMembershipAction } from '@/features/archive/CollectionMembership'
import { rowToItem } from '@/features/archive/adapters'

export function CollectionDetailPage() {
  const { collectionId = '' } = useParams()
  return <CollectionContents key={collectionId} id={collectionId} />
}
function CollectionContents({ id }: { id: string }) {
  const navigate = useNavigate()
  const collection = useCollection(id)
  const feed = useContents({ collection_id: id })
  const [manage, setManage] = useState(false)
  const [picker, setPicker] = useState(false)
  const { busy, failure, change } = useMembershipAction()
  const rows = feed.data?.pages.flatMap(page => page.items) || []
  if (!collection.data) return <main className="content archive-content"><RequestState loading={collection.isPending} error={collection.error} retry={() => void collection.refetch()} /><Link to="/collections">컬렉션 목록으로</Link></main>
  return <main className="content archive-content"><ArchivePageHeader title={collection.data.name} description={`이 컬렉션에 저장한 콘텐츠 ${collection.data.content_count}개 · 수동으로 모은 콘텐츠예요.`} action={<div className="detail-primary-actions"><button className="button primary" onClick={() => setPicker(true)}>콘텐츠 추가 및 제외</button><button className="button" onClick={() => setManage(true)}>컬렉션 관리</button></div>} />
    <RequestState loading={feed.isPending} error={feed.error} retry={() => void feed.refetch()} />{failure && <p role="alert">{failure}</p>}
    {!!rows.length && <div className="content-grid archive-library-grid">{rows.map((row, index) => <ArchiveCard key={row.id} item={rowToItem(row)} index={index} footerAction={<button type="button" className="collection-remove-action" disabled={busy} onClick={() => void change(id, row.id, false)} aria-label="이 컬렉션에서 제외" title="이 컬렉션에서만 제외하며, 저장한 콘텐츠는 유지돼요."><Icon name="x" small /><span>제외</span></button>} />)}</div>}
    {feed.isSuccess && !rows.length && <div className="empty-state archive-empty"><h3>아직 담긴 콘텐츠가 없어요.</h3><p>보관함의 콘텐츠를 이곳에 모아보세요.</p><button className="button primary" onClick={() => setPicker(true)}>콘텐츠 추가</button></div>}
    {feed.hasNextPage && <button className="button" disabled={feed.isFetchingNextPage} onClick={() => void feed.fetchNextPage()}>{feed.isFetchingNextPage ? '불러오는 중…' : '콘텐츠 더 보기'}</button>}
    {manage && <CollectionEditor collection={collection.data} onClose={() => setManage(false)} onSaved={() => setManage(false)} onDeleted={() => navigate('/collections', { replace: true })} />}
    {picker && <CollectionContentPicker collectionId={id} onClose={() => setPicker(false)} />}
  </main>
}
