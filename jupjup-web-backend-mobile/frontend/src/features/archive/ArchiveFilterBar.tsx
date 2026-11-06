import { useId, useState, type ReactNode } from 'react'
import './archive-filter-layout.css'
import { Icon } from '@/features/jupjup-dashboard/components/Icon'

export type ArchiveFilterOption = {
  value: string
  label: string
}

export type ArchiveFilterField = {
  key: string
  label: string
  layout?: 'tiles' | 'list' | 'chips' | 'segments'
  value: string
  options: readonly ArchiveFilterOption[]
  onChange: (value: string) => void
}

type SearchControl = {
  value: string
  onChange: (value: string) => void
  placeholder: string
  ariaLabel: string
}

type Props = {
  ariaLabel: string
  fields: readonly ArchiveFilterField[]
  search?: SearchControl
  onReset?: () => void
  resetLabel?: string
  actions?: ReactNode
  children?: ReactNode
  className?: string
}

/** Filtering and results share one responsive exploration layout. */
export function ArchiveFilterBar({ ariaLabel, fields, search, onReset, resetLabel = '필터 초기화', actions, children, className = '' }: Props) {
  const idPrefix = useId()
  const [expanded, setExpanded] = useState(false)
  const filters = fields.filter(field => field.key !== 'sort')
  const sort = fields.find(field => field.key === 'sort')
  const activeCount = filters.filter(field => field.value !== field.options[0]?.value).length

  return <div className={`archive-explorer ${className}`}>
    <button type="button" className="explorer-filter-toggle" aria-expanded={expanded} aria-controls={`${idPrefix}-filters`} onClick={() => setExpanded(!expanded)}>필터{activeCount > 0 ? ` · ${activeCount}` : ''}<Icon name="chevdown" small /></button>
    <aside id={`${idPrefix}-filters`} className={`explorer-filters${expanded ? ' expanded' : ''}`} aria-label={ariaLabel}>
      <div className="explorer-filter-heading"><h2>필터</h2>{onReset && <button type="button" onClick={onReset}>{resetLabel}</button>}</div>
      {search && <label className="archive-filter-search"><span className="sr-only">{search.ariaLabel}</span><Icon name="search" small /><input value={search.value} onChange={event => search.onChange(event.target.value)} placeholder={search.placeholder} aria-label={search.ariaLabel} /></label>}
      {filters.map(field => <details className="explorer-filter-group" data-layout={field.layout || 'list'} key={field.key} open>
        <summary>{field.label}{field.value !== field.options[0]?.value && <span>1</span>}<Icon name="chevdown" small /></summary>
        <fieldset><legend className="sr-only">{field.label}</legend>{field.options.map(option => <label key={option.value}>
          <input type="radio" name={`${idPrefix}-${field.key}`} value={option.value} checked={field.value === option.value} onChange={() => field.onChange(option.value)} />
          {field.layout === 'tiles' && <Icon name={({ post: 'note', short_video: 'video', video: 'video', article: 'note', paper: 'note', image: 'image', message: 'note', webpage: 'link' } as Record<string, string>)[option.value] || 'grid'} small />}
          {field.key === 'status' && option.value && <i className={`filter-status-dot ${option.value}`} aria-hidden="true" />}
          <span>{option.label}</span>
        </label>)}</fieldset>
      </details>)}
    </aside>
    <div className="explorer-results">
      {(sort || actions) && <div className="explorer-toolbar">
        {sort && <label>{sort.label}<select value={sort.value} onChange={event => sort.onChange(event.target.value)}>{sort.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>}
        {actions}
      </div>}
      {children}
    </div>
  </div>
}
