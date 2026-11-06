import { api, requestWithHeaders } from './client'
export type Collection = { id: string; name: string; color: string; content_count: number; created_at: string; updated_at: string }
const path = (id: string) => `/v1/collections/${encodeURIComponent(id)}`
export const listCollections = (signal?: AbortSignal) => api.get<{ items: Collection[] }>('/v1/collections', { signal })
export const getCollection = (id: string, signal?: AbortSignal) => api.get<Collection>(path(id), { signal })
export const createCollection = (name: string, color: string) => api.post<Collection>('/v1/collections', { name, color })
export const updateCollection = (id: string, name: string, color: string) => api.patch<Collection>(path(id), { name, color })
export const deleteCollection = (id: string) => api.delete(path(id))
export const setMembership = (id: string, contentId: string, included: boolean) => requestWithHeaders<void>(`${path(id)}/contents/${encodeURIComponent(contentId)}`, { method: included ? 'PUT' : 'DELETE' })
