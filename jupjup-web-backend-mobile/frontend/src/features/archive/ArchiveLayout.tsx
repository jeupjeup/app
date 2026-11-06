import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { DashboardShell } from '@/features/jupjup-dashboard/components/DashboardShell'
import { Icon } from '@/features/jupjup-dashboard/components/Icon'
import type { View } from '@/features/jupjup-dashboard/data/demo'
import { useArchiveStore } from './ArchiveStore'
import '@/features/jupjup-dashboard/styles.css'
import './archive.css'
import './dashboard-colors.css'
import './save-banner-preview.css'
import { useAuthenticatedUserId } from '@/shared/auth/session'
import { RequestState } from './RequestState'

type Notice = { message: string; actions?: Array<{ label: string; onClick: () => void }> }
type ArchiveUiValue = { openAdd: () => void; notify: (notice: string | Notice) => void }
const ArchiveUiContext = createContext<ArchiveUiValue | null>(null)

export function useArchiveUi() {
  const value = useContext(ArchiveUiContext)
  if (!value) throw new Error('useArchiveUi must be used inside ArchiveLayout')
  return value
}

function breadcrumbFromPath(pathname: string, collectionName?: string) {
  if (pathname === '/dashboard') return '홈'
  if (pathname.startsWith('/search')) return '검색 결과'
  if (pathname === '/contents/new') return '새로 줍기'
  if (/^\/contents\/.+/.test(pathname)) return '콘텐츠 상세'
  if (pathname === '/contents') return '모든 콘텐츠'
  if (/^\/collections\/.+/.test(pathname)) return collectionName || '컬렉션 상세'
  if (pathname === '/collections') return '컬렉션 관리'
  if (pathname === '/settings') return '설정'
  return '나의 저장소'
}

export function ArchiveLayout() {
  const userId = useAuthenticatedUserId()
  const navigate = useNavigate()
  const location = useLocation()
  const params = useParams()
  const { items, collections, settings, loading, error, refresh } = useArchiveStore()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const noticeTimer = useRef<number | null>(null)
  const activeCollection = params.collectionId || (location.pathname.startsWith('/collections/') ? location.pathname.split('/')[2] : null)
  const collectionName = collections.find((collection) => collection.id === activeCollection)?.name
  const settingsActive = location.pathname === '/settings'
  const searchParams = new URLSearchParams(location.search)
  const view: View = location.pathname === '/dashboard' ? 'home' : location.pathname === '/contents' && searchParams.get('period') === 'recent' ? 'recent' : location.pathname === '/contents' && searchParams.get('favorite') === 'true' ? 'favorites' : location.pathname === '/contents' ? 'all' : location.pathname === '/collections' ? 'collections' : activeCollection ? 'collection' : 'home'
  const navigationActive = location.pathname === '/dashboard' || location.pathname === '/contents' || location.pathname === '/collections' || Boolean(activeCollection)

  const notify = (next: string | Notice) => {
    setNotice(typeof next === 'string' ? { message: next } : next)
    if (noticeTimer.current !== null) window.clearTimeout(noticeTimer.current)
    noticeTimer.current = window.setTimeout(() => setNotice(null), 5200)
  }
  useEffect(() => () => { if (noticeTimer.current !== null) window.clearTimeout(noticeTimer.current) }, [])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); navigate('/search') }
      if (event.key === 'Escape') setSidebarOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navigate])
  useEffect(() => {
    const onComplete = (event: Event) => {
      if (!settings.analysisNotifications) return
      const { id, status } = (event as CustomEvent<{ id: string; status: 'completed' | 'failed' }>).detail
      notify({ message: status === 'failed' ? '콘텐츠는 저장했지만 AI 분석에 실패했어요.' : '새 콘텐츠 분석이 끝났어요.', actions: [{ label: status === 'failed' ? '확인하기' : '상세 보기', onClick: () => navigate(`/contents/${id}`) }] })
    }
    window.addEventListener('jupjup:analysis-complete', onComplete)
    return () => window.removeEventListener('jupjup:analysis-complete', onComplete)
  }, [navigate, settings.analysisNotifications])

  const onNavigate = (next: View, collectionId?: string) => {
    setSidebarOpen(false)
    const routes: Record<View, string> = { home: '/dashboard', all: '/contents', recent: '/contents?period=recent', favorites: '/contents?favorite=true', collections: '/collections', collection: `/collections/${collectionId || ''}` }
    navigate(routes[next])
  }
  const ui = useMemo<ArchiveUiValue>(() => ({ openAdd: () => navigate('/contents/new'), notify }), [navigate])


  if (!userId) return <Navigate to="/login" replace />
  return <>
    <DashboardShell
      collections={collections}
      itemCount={items.length}
      view={view}
      activeCollection={activeCollection}
      settingsActive={settingsActive}
      navigationActive={navigationActive}
      sidebarOpen={sidebarOpen}
      breadcrumb={breadcrumbFromPath(location.pathname, collectionName)}
      topActions={<><button type="button" aria-label="콘텐츠 검색" className="top-search" onClick={() => navigate('/search')}><Icon name="search" small /><span>콘텐츠 검색</span><kbd>⌘ K</kbd></button><button type="button" aria-label="계정 및 설정" className="top-profile" onClick={() => navigate('/settings')}>내</button></>}
      onSidebarToggle={() => setSidebarOpen((open) => !open)}
      onSidebarClose={() => setSidebarOpen(false)}
      onNavigate={onNavigate}
      onAddCollection={() => { setSidebarOpen(false); navigate('/collections?create=true') }}
      onSettings={() => navigate('/settings')}
    >
      <ArchiveUiContext.Provider value={ui}><RequestState loading={loading} error={error} retry={() => void refresh()} /><Outlet /></ArchiveUiContext.Provider>
    </DashboardShell>
    <div className={`toast archive-toast${notice ? ' show' : ''}`} aria-live="polite" role="status"><span>{notice?.message}</span>{notice?.actions?.map((action) => <button key={action.label} type="button" onClick={() => { action.onClick(); setNotice(null) }}>{action.label}</button>)}</div>
  </>
}
