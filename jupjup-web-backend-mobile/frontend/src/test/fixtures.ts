import type { ContentDetail } from '@/shared/api/contracts'
export const detailFixture: ContentDetail = {
  collection_ids: [], id: 'c_test', canonical_id: 'c_test', revision: 1, status: 'awaiting_confirmation', hidden: false,
  source: { kind: 'text', url: null, original_status: 'unknown' }, platform: 'local', content_type: 'webpage', title: null, author: null, saved_at: '2026-11-05T00:00:00+09:00', user_note: '저장 이유',
  summary: { effective: '사용자 요약', source: 'user', ai: 'AI 요약', user: '사용자 요약' }, representative_tags: { effective: ['사용자 태그'], ai: ['AI 태그'], user: ['사용자 태그'], hidden_ai: ['AI 태그'] },
  detail_tags: { effective: { schema_version: 1, topics: ['주제'], keywords: ['키워드'], locations: [{ name: '서울' }] }, ai: { schema_version: 1 }, user_patch: { topics: ['주제'] } },
  snapshot: { text: '원문은 메모와 별개', ocr_text: null }, analysis: { source_text_available: true, source_text_reason: null, automation_level: 'confirm', analysis_pending: true, latest_job_id: 'j_test', candidate: { id: 'candidate_1', summary: '적용 전 제안', representative_tags: ['후보'], detail_tags: { schema_version: 1, topics: ['제안 주제'] } } },
}
