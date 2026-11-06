import { createContext, useContext, useEffect, useState, type PropsWithChildren } from 'react'
import { defaultArchiveSettings, type ArchiveCollection, type ArchiveItem, type ArchiveSettings } from './archiveData'
import { useCollections, useContents, useRefreshArchive } from './queries'
import { rowToItem } from './adapters'
import { createContent, SubmissionKeys } from '@/shared/api/contents'
import { env } from '@/shared/config/env'
import { useAuthenticatedUserId } from '@/shared/auth/session'
import type { SubmitResponse } from '@/shared/api/contracts'

const keys = new SubmissionKeys()
function readFavorites(key: string | null): string[] {
  if (!key) return []
  try { const value: unknown = JSON.parse(localStorage.getItem(key) || '[]'); return Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string') : [] } catch { return [] }
}
function readSettings(): ArchiveSettings {
  try { const stored = JSON.parse(localStorage.getItem('jupjup_archive_settings_v1') || '{}'); return { ...defaultArchiveSettings, ...stored, defaultSort: stored.defaultSort === 'old' ? 'old' : 'new' } } catch { return defaultArchiveSettings }
}
type Value = {
  items: ArchiveItem[]; collections: ArchiveCollection[]; settings: ArchiveSettings
  setSettings: React.Dispatch<React.SetStateAction<ArchiveSettings>>
  loading: boolean; error: unknown; refresh: () => Promise<void>
  favorites: string[]; toggleFavorite: (id: string) => void
  saveContent: (input: { kind: 'url' | 'text'; value: string }) => Promise<SubmitResponse>

}
const Context = createContext<Value | null>(null)
export function ArchiveStoreProvider({ children }: PropsWithChildren) {
  const [settings, setSettings] = useState(readSettings)
  const userId = useAuthenticatedUserId()
  const favoriteKey = userId ? `jupjup_favorites_v2:${new URL(env.apiBaseUrl, window.location.href).href}:${userId}` : null
  const [favoriteState, setFavoriteState] = useState(() => ({ key: favoriteKey, ids: readFavorites(favoriteKey) }))
  const favorites = favoriteState.key === favoriteKey ? favoriteState.ids : readFavorites(favoriteKey)
  useEffect(() => {
    setFavoriteState({ key: favoriteKey, ids: readFavorites(favoriteKey) })
    const sync = (event: StorageEvent) => { if (event.key === favoriteKey || event.key === null) setFavoriteState({ key: favoriteKey, ids: readFavorites(favoriteKey) }) }
    window.addEventListener('storage', sync)
    return () => window.removeEventListener('storage', sync)
  }, [favoriteKey])
  const toggleFavorite = (id: string) => {
    if (!favoriteKey) throw new Error('Authentication required')
    const current = readFavorites(favoriteKey)
    const next = current.includes(id) ? current.filter(value => value !== id) : [...current, id]
    localStorage.setItem(favoriteKey, JSON.stringify(next))
    setFavoriteState({ key: favoriteKey, ids: next })
  }
  const feed = useContents()
  const collectionQuery = useCollections()
  const collections: ArchiveCollection[] = (collectionQuery.data?.items || []).map(c => ({ id: c.id, name: c.name, color: c.color, bg: `${c.color}30`, ink: "#5D5148", updatedAt: c.updated_at, organizeMode: "manual", contentCount: c.content_count }))
  const refresh = useRefreshArchive()
  const items = feed.data?.pages.flatMap(page => page.items).map(rowToItem) || []
  useEffect(() => { try { localStorage.setItem('jupjup_archive_settings_v1', JSON.stringify(settings)) } catch { /* In-memory settings remain usable when storage is blocked. */ } }, [settings])
  const saveContent: Value['saveContent'] = async ({ kind, value }) => {
    const body = { source: kind === 'url' ? { kind, url: value.trim() } : { kind, text: value.trim() }, automation_level: settings.organizeMode === 'automatic' ? 'auto' as const : 'confirm' as const }
    const key = await keys.keyFor('create', body)
    const result = await createContent(body, key)
    keys.clear()
    await refresh()
    return result
  }
  return <Context.Provider value={{ items, collections, settings, setSettings, loading: feed.isPending, error: feed.error, refresh, saveContent, favorites, toggleFavorite }}>{children}</Context.Provider>
}
export function useArchiveStore() {
  const value = useContext(Context)
  if (!value) throw new Error('useArchiveStore must be used inside ArchiveStoreProvider')
  return value
}
