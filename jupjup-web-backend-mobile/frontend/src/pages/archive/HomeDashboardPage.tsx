import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArchiveCard } from '@/features/archive/ArchiveCard'
import { useArchiveUi } from '@/features/archive/ArchiveLayout'
import { useArchiveStore } from '@/features/archive/ArchiveStore'
import { NaturalSearch } from '@/features/archive/NaturalSearch'
import { Icon } from '@/features/jupjup-dashboard/components/Icon'
import { effectiveSavedAt, isOlderThanDays, isWithinRecentDays } from '@/features/archive/archiveData'

export function HomeDashboardPage() {
  const navigate = useNavigate()
  const { openAdd } = useArchiveUi()
  const { items, collections, settings } = useArchiveStore()
  const recentItems = useMemo(() => [...items].filter((item) => isWithinRecentDays(effectiveSavedAt(item))).sort((a, b) => effectiveSavedAt(b).localeCompare(effectiveSavedAt(a))), [items])
  const recent = recentItems.slice(0, 6)
  const analyzing = items.filter((item) => item.analysisStatus === 'analyzing')
  const unorganized = items.filter((item) => item.serverStatus === 'awaiting_confirmation')
  const rediscovery = [
    { title: '이번 주에 저장한 콘텐츠', count: recentItems.length, query: '최근 저장' },
    { title: '일본 여행 관련 자료', count: items.filter((item) => [item.title, item.aiSummary, ...item.primaryTags, ...item.detailTags].join(' ').includes('일본')).length, query: '일본 여행' },
    { title: '한 달 이상 확인하지 않은 자료', count: items.filter((item) => isOlderThanDays(effectiveSavedAt(item))).length, query: '오래된 자료' },
    { title: '최근 다시 찾은 디자인 자료', count: items.filter((item) => [item.title, ...item.primaryTags, ...item.detailTags].join(' ').toLocaleLowerCase('ko').includes('디자인')).length, query: '디자인' },
  ]

  const search = (value: string) => { if (value === '최근 저장') navigate('/contents?period=recent'); else if (value === '오래된 자료') navigate('/contents?period=old'); else if (value.trim()) navigate(`/search?q=${encodeURIComponent(value.trim())}`) }

  return <main className="content archive-content archive-home">
    <header className="intro archive-page-header"><div><h1>내 저장소</h1><p>저장한 콘텐츠를 둘러보고, 기억나는 말로 다시 찾아보세요.</p></div></header>
    <div className="home-primary-actions">
    <NaturalSearch />
    <div className="home-save-prompt">
      <div><strong>놓치기 아까운 콘텐츠가 있나요?</strong><span>지금 저장해두면 필요할 때 다시 찾아볼 수 있어요.</span></div>
      <button type="button" onClick={openAdd}>콘텐츠 저장하기 <Icon name="arrow" small /></button>
    </div>
    </div>

    <section className="repository-status" aria-labelledby="repositoryStatusTitle">
      <div className="section-heading">
        <div><h2 id="repositoryStatusTitle">저장소 현황</h2><p>현재 불러온 콘텐츠의 정리 현황을 확인해 보세요.</p></div>
        <button type="button" className="inline-link" onClick={openAdd}><Icon name="plus" small /> 콘텐츠 저장</button>
      </div>
      <div className={`repository-status-grid${settings.organizeNotifications ? '' : ' is-compact'}`}>
        <article className="status-card">
          <div className="status-card-heading"><span className="small-icon"><Icon name="clock" /></span><div><h3>내용 정리 중</h3><p>{analyzing.length ? `${analyzing.length}개의 콘텐츠를 분석하고 있어요.` : '지금 분석 중인 콘텐츠가 없어요.'}</p></div></div>
          {analyzing.length ? analyzing.slice(0, 2).map((item) => <button type="button" key={item.id} className="status-card-item" onClick={() => navigate(`/contents/${item.id}`)}><span>{item.title}</span><i>분석 중</i></button>) : <p className="status-card-note">새 콘텐츠를 저장하면 분석 상태를 여기서 확인할 수 있어요.</p>}
        </article>
        {settings.organizeNotifications && <article className="status-card">
          <div className="status-card-heading"><span className="small-icon soft"><Icon name="folder" /></span><div><h3>확인을 기다리는 제안</h3><p>{unorganized.length ? `확인이 필요한 콘텐츠 ${unorganized.length}개` : items.length ? '확인을 기다리는 제안이 없어요.' : '아직 저장한 콘텐츠가 없어요.'}</p></div></div>
          {unorganized.slice(0, 2).map((item) => <button type="button" key={item.id} className="status-card-item" onClick={() => navigate(`/contents/${item.id}`)}><span>{item.title}</span><Icon name="chevron" small /></button>)}
          {!unorganized.length && <p className="status-card-note">분석 제안은 상세에서 승인하거나 거절할 수 있어요.</p>}
        </article>}
        <article className="status-card">
          <div className="status-card-heading"><span className="small-icon saved"><Icon name="database" /></span><div><h3>저장된 콘텐츠</h3><p>콘텐츠 {items.length}개를 불러왔어요.</p></div></div>
          <button type="button" className="status-card-item" onClick={() => navigate('/contents')}><span>전체 콘텐츠 보기</span><Icon name="arrow" small /></button>
          <p className="status-card-note">컬렉션 기능은 현재 준비 중이에요.</p>
        </article>
      </div>
    </section>

    <section className="items-section" aria-labelledby="recentTitle"><div className="section-heading"><div><h2 id="recentTitle">최근 저장한 콘텐츠</h2><p>최근 저장한 콘텐츠부터 확인해 보세요.</p></div><button type="button" className="inline-link" onClick={() => navigate('/contents?period=recent')}>모두 보기 <Icon name="arrow" small /></button></div><div className="content-grid">{recent.map((item, index) => <ArchiveCard key={item.id} item={item} index={index} />)}</div></section>

    <section className="rediscovery-section" aria-labelledby="rediscoveryTitle"><div className="section-heading"><div><h2 id="rediscoveryTitle">다시 주워볼까요?</h2><p>불러온 콘텐츠를 주제별로 다시 살펴보세요.</p></div></div><div className="rediscovery-grid">{rediscovery.map((card, index) => <button type="button" key={card.title} className={`rediscovery-card tone-${index + 1}`} onClick={() => search(card.query)}><span className="rediscovery-count">{card.count}<small>개</small></span><strong>{card.title}</strong><span>모아보기 <Icon name="arrow" small /></span></button>)}</div></section>

    <section className="recent-collections" aria-labelledby="recentCollectionsTitle"><div className="section-heading"><div><h2 id="recentCollectionsTitle">컬렉션</h2><p>관련 있는 콘텐츠를 컬렉션으로 모아보세요.</p></div><button type="button" className="inline-link" onClick={() => navigate('/collections')}>컬렉션 관리 <Icon name="arrow" small /></button></div><div className="collection-summary-row">{collections.slice(0, 4).map((collection) => <button key={collection.id} type="button" onClick={() => navigate(`/collections/${collection.id}`)}><span className="folder-icon" style={{ background: collection.bg, color: collection.ink }}><Icon name="folder" /></span><span><strong>{collection.name}</strong><small>콘텐츠 {collection.contentCount ?? 0}개</small></span><Icon name="chevron" /></button>)}</div></section>
  </main>
}
