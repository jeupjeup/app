import { typeNames } from './presentation'
import type { ContentDetail, ContentRow, ContentStatus, SearchResult } from '@/shared/api/contracts'
import type { ArchiveItem } from './archiveData'
const platforms: Record<string, string> = { instagram: 'Instagram', youtube: 'YouTube', kakaotalk: '카카오톡', news: '뉴스', blog: '블로그', x: 'X', web: 'Web', local: '직접 저장' }
export const statusLabel = (state?: string) => ({ pending: '분석 중', awaiting_confirmation: '적용 확인 대기', ready: '정리 완료', analysis_failed: '분석 실패', analysis_rejected: '제안 미적용', duplicate: '중복 저장' }[state || ''] || '상태 확인 필요')
export function rowToItem(row: ContentRow): ArchiveItem {
  return {
    id: row.id, title: row.title || row.source_url || '제목 없는 콘텐츠', url: safeUrl(row.source_url),
    source: platforms[row.platform] || row.platform,
    contentType: row.content_type === 'post' ? 'post' : ['video', 'short_video'].includes(row.content_type) ? 'video' : 'web',
    savedAt: row.saved_at, analysisStatus: row.status === 'pending' ? 'analyzing' : row.status === 'analysis_failed' ? 'failed' : 'completed',
    serverStatus: row.status, contentLabel: typeNames[row.content_type] || '콘텐츠', sourceStatus: row.original_available ? 'unknown' : 'unavailable',
    aiSummary: (row.summary_is_mock ?? isMockSummary(row.summary)) ? "시험용 고정 결과예요. 실제 모델 요약은 아직 제공하지 않아요." : row.summary || undefined, primaryTags: row.representative_tags, detailTags: [], collectionIds: row.collection_ids || [], relatedContentIds: [], favorite: false, art: 'editorial',
  }
}
export function detailToItem(data: ContentDetail): ArchiveItem {
  const item = rowToItem({ collection_ids: data.collection_ids, id: data.id, title: data.title, source_url: data.source.url, platform: data.platform, content_type: data.content_type, saved_at: data.saved_at, summary: data.summary.effective, summary_is_mock: data.summary.is_mock ?? (data.summary.source === "user" ? false : undefined), representative_tags: data.representative_tags.effective, status: data.status, revision: data.revision, hidden: data.hidden, updated_at: null, original_available: data.source.original_status !== 'deleted', analysis_pending: data.analysis.analysis_pending })
  return { ...item, contentType: data.source.kind === 'text' ? 'note' : item.contentType, sourceStatus: data.source.original_status === 'available' ? 'available' : data.source.original_status === 'deleted' ? 'unavailable' : 'unknown', userMemo: data.user_note || undefined, detailTags: [...new Set([...(data.detail_tags.effective.topics || []), ...(data.detail_tags.effective.keywords || [])])] }
}
export function searchToItem(row: SearchResult): ArchiveItem {
  const item = rowToItem({ ...row, id: row.content_id, revision: 0, hidden: false, status: 'ready' as ContentStatus, updated_at: null, analysis_pending: false })
  return { ...item, serverStatus: undefined }
}
export function safeUrl(url: string | null) {
  try { const parsed = new URL(url || ''); return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : '' } catch { return '' }
}

export const isMockSummary = (summary: string | null | undefined) => !!summary?.includes("mock 요약")
