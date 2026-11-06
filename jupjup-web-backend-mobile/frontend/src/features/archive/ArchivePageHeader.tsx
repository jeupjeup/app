import type { ReactNode } from 'react'
import { Icon } from '@/features/jupjup-dashboard/components/Icon'
import { useArchiveUi } from './ArchiveLayout'

export function ArchivePageHeader({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  const { openAdd } = useArchiveUi()
  return <section className="intro archive-page-header"><div><h1>{title}</h1><p>{description}</p></div><div className="intro-actions">{action || <button type="button" className="button primary" aria-label="콘텐츠 추가" onClick={openAdd}><Icon name="plus" small /><span>콘텐츠 추가</span></button>}</div></section>
}
