import type { ReactNode } from 'react'
import type { Collection, View } from '../data/demo'
import { Icon, IconSymbols } from './Icon'
import { Sidebar } from './Sidebar'

type DashboardShellProps = {
  children: ReactNode
  collections: Collection[]
  itemCount: number
  view: View
  activeCollection: string | null
  settingsActive?: boolean
  navigationActive?: boolean
  sidebarOpen: boolean
  breadcrumb: string
  topActions: ReactNode
  onSidebarToggle: () => void
  onSidebarClose: () => void
  onNavigate: (view: View, collectionId?: string) => void
  onAddCollection: () => void
  onSettings: () => void
}

export function DashboardShell({
  children,
  collections,
  itemCount,
  view,
  activeCollection,
  settingsActive = false,
  navigationActive = true,
  sidebarOpen,
  breadcrumb,
  topActions,
  onSidebarToggle,
  onSidebarClose,
  onNavigate,
  onAddCollection,
  onSettings,
}: DashboardShellProps) {
  return (
    <>
      <IconSymbols />
      <div className="app-shell">
        <Sidebar
          collections={collections}
          itemCount={itemCount}
          view={view}
          activeCollection={activeCollection}
          settingsActive={settingsActive}
          navigationActive={navigationActive}
          open={sidebarOpen}
          onNavigate={onNavigate}
          onAddCollection={onAddCollection}
          onSettings={onSettings}
          onClose={onSidebarClose}
        />
        <div className="main-shell">
          <header className="topbar">
            <button type="button" aria-label="메뉴 열기" className="mobile-menu" onClick={onSidebarToggle}><Icon name="menu" large /></button>
            <div className="breadcrumbs"><span>나의 저장소</span><Icon name="chevron" small /><b>{breadcrumb}</b></div>
            <div className="top-actions">{topActions}</div>
          </header>
          {children}
        </div>
      </div>
    </>
  )
}
