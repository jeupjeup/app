import { api, requestWithHeaders } from './client'
import type { AliasDetail, ContentDetail, ContentPage, ContentPatch, CreateContent, JobDetail, SearchBody, SearchResponse, SubmitResponse } from './contracts'
const path = (id: string) => `/v1/contents/${encodeURIComponent(id)}`
export type ListParams = Record<string, string | string[] | undefined>
export function listContents(params: ListParams = {}, signal?: AbortSignal) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) for (const v of Array.isArray(value) ? value : value === undefined ? [] : [value]) query.append(key, v)
  return api.get<ContentPage>(`/v1/contents?${query}`, { signal })
}
export const getContent = (id: string, signal?: AbortSignal) => requestWithHeaders<ContentDetail | AliasDetail>(path(id), { signal })
export const createContent = (body: CreateContent, key: string) => api.post<SubmitResponse>('/v1/contents', body, { headers: { 'Idempotency-Key': key } })
export const patchContent = (id: string, body: ContentPatch, etag: string) => requestWithHeaders<ContentDetail>(path(id), { method: 'PATCH', body, headers: { 'If-Match': etag } })
export const deleteContent = (id: string) => api.delete(path(id))
export const reanalyzeContent = (id: string, level: 'auto' | 'confirm', key: string, mode: 'snapshot' | 'youtube_metadata' = 'snapshot') => api.post<SubmitResponse>(`${path(id)}:reanalyze`, { automation_level: level, mode }, { headers: { 'Idempotency-Key': key } })
export const reviewContent = (id: string, candidate: string, decision: 'approve' | 'reject') => api.post(`${path(id)}:review`, { candidate_id: candidate, decision })
export const getJob = (id: string, signal?: AbortSignal) => api.get<JobDetail>(`/v1/jobs/${encodeURIComponent(id)}?trace=none`, { signal })
export const searchContents = (body: SearchBody, signal?: AbortSignal) => api.post<SearchResponse>('/v1/search', body, { signal })

// Retain the key for an uncertain response, without persisting the source body.
export class SubmissionKeys {
  private pending = new Map<string, string>()
  async keyFor(scope: string, body: unknown): Promise<string> {
    const bytes = new TextEncoder().encode(JSON.stringify(body))
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), n => n.toString(16).padStart(2, '0')).join('')
    const fingerprint = `${scope}:${digest}`
    if (!this.pending.has(fingerprint)) this.pending.set(fingerprint, crypto.randomUUID())
    return this.pending.get(fingerprint)!
  }
  clear() { this.pending.clear() }
}
