import { describe, expect, it } from 'vitest'
import { createSampleAnalysis, detectSource, normalizeHttpUrl, parseHttpUrl } from './contentSource'
import type { ArchiveItem } from './archiveData'

describe('content source detection', () => {
  it('accepts only usable HTTP URLs', () => {
    expect(parseHttpUrl('https://example.com/article')).not.toBeNull()
    expect(parseHttpUrl('javascript:alert(1)')).toBeNull()
    expect(parseHttpUrl('https://user:secret@example.com')).toBeNull()
  })

  it('detects supported platforms and normalizes duplicate URLs', () => {
    expect(detectSource(new URL('https://www.youtube.com/shorts/abc')).label).toBe('YouTube Shorts')
    expect(detectSource(new URL('https://www.instagram.com/reel/abc')).contentType).toBe('post')
    expect(detectSource(new URL('https://arxiv.org/abs/1234.5678')).platform).toBe('arxiv')
    expect(normalizeHttpUrl('https://EXAMPLE.com/article/#section')).toBe('https://example.com/article')
  })

  it('creates an honest sample analysis for saved text', () => {
    const item: ArchiveItem = {
      id: 'user-test', title: '임시 제목', url: '', source: '직접 메모', contentType: 'note',
      savedAt: '2026-11-05', analysisStatus: 'analyzing', sourceStatus: 'available',
      primaryTags: [], detailTags: [], collectionIds: [], relatedContentIds: [], favorite: false,
      userMemo: 'React 기획 아이디어를 다음 회의 전에 정리하기', art: 'note',
    }
    const result = createSampleAnalysis(item)
    expect(result.title).toContain('React')
    expect(result.primaryTags).toContain('React')
    expect(result.aiSummary).toContain('기획 아이디어')
  })

  it('does not use generic route segments as generated titles', () => {
    const item: ArchiveItem = {
      id: 'user-video', title: 'YouTube 영상', url: 'https://www.youtube.com/watch?v=demo', source: 'YouTube', contentType: 'video',
      savedAt: '2026-11-05', analysisStatus: 'analyzing', sourceStatus: 'available', primaryTags: [], detailTags: [],
      collectionIds: [], relatedContentIds: [], favorite: false, art: 'motion',
    }
    expect(createSampleAnalysis(item).title).toBe('나중에 다시 볼 YouTube 영상')
  })
})
