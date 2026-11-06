export type MetadataClassification = {
  source_scope: 'youtube_metadata'; basis: 'title_description' | 'title_only'; classifier: 'local-metadata-rules-v1' | 'local-metadata-llm-v1'; summary?: string; model?: string
  metadata: { title: string; description: string; title_source: 'videoDetails.title'; description_source: 'videoDetails.shortDescription' | 'absent'; description_status: 'available' | 'empty' | 'missing'; title_truncated: boolean; description_truncated: boolean; transcript_reason: 'captions_unavailable' | 'empty_captions' | 'empty_or_invalid_captions' | 'not_requested' }
  representative_tags: string[]; detail_tags: DetailTags; evidence: { field: 'title' | 'description'; source_span: string; tag: string }[]
}
export type ContentStatus = 'pending' | 'awaiting_confirmation' | 'ready' | 'analysis_failed' | 'analysis_rejected' | 'duplicate'
export type JobStatus = 'queued' | 'running' | 'retry_wait' | 'awaiting_confirmation' | 'succeeded' | 'failed' | 'needs_review' | 'rejected' | 'deduplicated' | 'cancelled'
export type DetailTags = { schema_version: number; topics?: string[]; keywords?: string[]; [key: string]: unknown }
export type ContentRow = {
  collection_ids?: string[]; id: string; revision: number; status: ContentStatus; hidden: boolean; title: string | null
  platform: string; content_type: string; summary: string | null; summary_is_mock?: boolean; representative_tags: string[]
  saved_at: string; updated_at: string | null; source_url: string | null; original_available: boolean; analysis_pending: boolean
}
export type ContentPage = { items: ContentRow[]; next_cursor: string | null; has_more: boolean }
export type ContentDetail = {
  collection_ids: string[]; id: string; canonical_id: string; revision: number; status: ContentStatus; hidden: boolean
  source: { kind: 'text' | 'url' | 'image'; url: string | null; original_status: 'available' | 'deleted' | 'unknown' }
  platform: string; content_type: string; title: string | null; author: string | null; saved_at: string; user_note: string | null
  summary: { model?: string | null; effective: string | null; source: string | null; is_mock?: boolean; ai: string | null; user: string | null }
  representative_tags: { effective: string[]; ai: string[]; user: string[]; hidden_ai: string[] }
  detail_tags: { effective: DetailTags; ai: DetailTags; user_patch: Record<string, unknown> | null }
  snapshot: { text: string; ocr_text?: string | null } | null
  analysis: { metadata?: MetadataClassification | null; source_text_available: boolean; source_text_reason: 'legacy_watch_snapshot' | 'missing_snapshot' | 'empty_snapshot' | null; automation_level: 'auto' | 'confirm'; analysis_pending: boolean; latest_job_id: string | null; candidate: { meta?: { model?: string }; id: string; summary?: string; representative_tags: string[]; detail_tags: DetailTags; source_scope?: 'youtube_metadata'; metadata?: MetadataClassification['metadata']; basis?: MetadataClassification['basis']; evidence?: MetadataClassification['evidence'] } | null }
}
export type AliasDetail = { id: string; canonical_id: string; revision: number; status: 'duplicate' }
export const isAlias = (data: ContentDetail | AliasDetail): data is AliasDetail => !('source' in data)
export type CreateContent = { source: { kind: 'url'; url: string } | { kind: 'text'; text: string }; automation_level: 'auto' | 'confirm' }
export type ContentPatch = { summary?: string | null; representative_tags?: string[] | null; detail_tags?: Record<string, unknown> | null; hidden?: boolean }
export type SubmitResponse = { content_id: string; job_id: string | null; status: string; deduplicated: boolean; result_content_id: string; warnings?: string[] }
export type JobDetail = { id: string; status: JobStatus; current_stage: string; result_content_id: string; next_run_at: string | null; error: { code: string; message?: string; retryable?: boolean } | null; steps: { stage: string; status: string; attempts: number }[] }
export type SearchBody = { query: string; limit?: number; filters?: { platforms?: string[]; content_types?: string[] } }
export type SearchResult = Omit<ContentRow, 'id' | 'revision' | 'status' | 'hidden' | 'updated_at' | 'analysis_pending'> & { content_id: string; rank: number; match_reasons: { type: string; field?: string; terms?: string[]; detail?: string }[] }
export type SearchResponse = { results: SearchResult[]; applied_relaxations: string[]; degraded: boolean; empty_state: { message?: string; [key: string]: unknown } | null }
