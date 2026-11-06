import '@/features/archive/collection-cards.css'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArchivePageHeader } from '@/features/archive/ArchivePageHeader'
import { Icon } from '@/features/jupjup-dashboard/components/Icon'
import { useCollections } from '@/features/archive/queries'
import { RequestState } from '@/features/archive/RequestState'
import { CollectionEditor } from '@/features/archive/CollectionEditor'
import type { Collection } from '@/shared/api/collections'

export function CollectionsPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const query = useCollections()
  const [editing, setEditing] = useState<Collection | null>(null)
  const creating = params.get('create') === 'true'
  const close = () => { setEditing(null); setParams({}, { replace: true }) }
  return <main className="content archive-content">
    <ArchivePageHeader title="컬렉션 관리" description="저장한 콘텐츠를 목적과 주제에 맞게 직접 묶어보세요." action={<button type="button" className="button primary" onClick={() => setParams({ create: 'true' })}><Icon name="plus" small />컬렉션 만들기</button>} />
    <RequestState loading={query.isPending} error={query.error} retry={() => void query.refetch()} />
    {!!query.data?.items.length && <div className="collection-management-grid">{query.data.items.map(collection => <div key={collection.id} className="collection-management-card collection-folder-card"><button type="button" className="collection-open" onClick={() => navigate(`/collections/${collection.id}`)}><span className="collection-card-top"><span className="folder-icon" style={{ background: `${collection.color}30`, color: '#5D5148' }}><Icon name="folder" /></span></span><strong>{collection.name}</strong><small>콘텐츠 {collection.content_count}개</small><span className="collection-folder-link">컬렉션 열기<Icon name="arrow" small /></span></button><button type="button" className="collection-manage-action" onClick={() => setEditing(collection)} aria-label={`${collection.name} 관리`} title="이름·색상 수정 및 삭제"><Icon name="more" /></button></div>)}</div>}
    {query.isSuccess && !query.data.items.length && <div className="empty-state archive-empty"><span className="empty-symbol"><Icon name="folder" /></span><h3>아직 만든 컬렉션이 없어요.</h3><p>함께 보고 싶은 콘텐츠를 주제별로 묶어보세요.</p><button className="button primary" onClick={() => setParams({ create: 'true' })}>첫 컬렉션 만들기</button></div>}
    {(creating || editing) && <CollectionEditor key={editing?.id || 'new'} collection={editing || undefined} onClose={close} onSaved={id => { close(); if (creating) navigate(`/collections/${id}`) }} onDeleted={close} />}
  </main>
}
