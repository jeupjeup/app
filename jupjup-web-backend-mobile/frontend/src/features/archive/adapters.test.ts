import { isWithinRecentDays, isOlderThanDays } from './archiveData'
import { detailFixture } from '@/test/fixtures'
import { describe, expect, it } from 'vitest'
import { detailToItem, rowToItem, safeUrl, searchToItem, statusLabel } from './adapters'
import type { ContentRow, SearchResult } from '@/shared/api/contracts'
describe('archive adapters', () => {
  it('keeps confirmation distinct and uses effective user layers without modifying structured data', () => {
    const original = JSON.stringify(detailFixture)
    const item = detailToItem(detailFixture)
    expect(item.serverStatus).toBe('awaiting_confirmation')
    expect(statusLabel(item.serverStatus)).toBe('적용 확인 대기')
    expect(item.aiSummary).toBe('사용자 요약')
    expect(item.primaryTags).toEqual(['사용자 태그'])
    expect(item.userMemo).toBe('저장 이유')
    expect(item.userMemo).not.toBe(detailFixture.snapshot?.text)
    expect(item.detailTags).toEqual(['주제', '키워드'])
    expect(JSON.stringify(detailFixture)).toBe(original)
  })
  it('does not infer current original availability or completion from reduced indexing', () => {
    const row = { id: 'c_a', revision: 1, hidden: false, updated_at: null, title: null, source_url: null, platform: 'web', content_type: 'image', saved_at: '', summary: null, representative_tags: [], status: 'analysis_rejected', original_available: true, analysis_pending: true } as ContentRow
    const item = rowToItem(row)
    expect(item.sourceStatus).toBe('unknown')
    expect(item.serverStatus).toBe('analysis_rejected')
    expect(item.contentLabel).toBe('이미지')
  })
  it('maps search ids without inventing server completion state and blocks unsafe original links', () => {
    expect(searchToItem({ content_id: 'c_other', title: '검색', representative_tags: [] } as unknown as SearchResult).serverStatus).toBeUndefined()
    expect(safeUrl('javascript:alert(1)')).toBe('')
    expect(safeUrl('https://example.com/a')).toBe('https://example.com/a')
  })
})

it('accepts server timestamps for dashboard recent and older sections', () => {
  expect(isWithinRecentDays(new Date(Date.now() - 1000).toISOString())).toBe(true)
  expect(isOlderThanDays('2020-01-01T10:00:00+09:00')).toBe(true)
})

it('labels fixed mock output without exposing it as a model summary', () => {
  const detail = structuredClone(detailFixture)
  detail.summary = { effective: '고정 예시', source: 'ai', ai: '고정 예시', user: null, is_mock: true }
  expect(detailToItem(detail).aiSummary).toContain('실제 모델 요약은 아직 제공하지 않아요')
  detail.summary = { effective: '내가 쓴 mock 요약 검토', source: 'user', ai: null, user: '내가 쓴 mock 요약 검토', is_mock: false }
  expect(detailToItem(detail).aiSummary).toBe('내가 쓴 mock 요약 검토')
})
