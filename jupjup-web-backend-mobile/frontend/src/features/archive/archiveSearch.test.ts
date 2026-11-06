import { describe, expect, it } from 'vitest'
import { completeArchiveAnalysis, effectiveSavedAt, seedArchiveCollections, seedArchiveItems } from './archiveData'
import { describeSearchMatch, searchArchive } from './archiveSearch'

describe('archive demo search', () => {
  it('expands the 오사카 alias into travel and transport matches', () => {
    const results = searchArchive(seedArchiveItems, seedArchiveCollections, '오사카 갈 때 볼 교통 영상')
    expect(results.map((result) => result.item.id)).toContain('osaka-subway')
    expect(results.find((result) => result.item.id === 'osaka-subway')?.matchedTerms).toContain('교통')
    expect(results[0].score).toBeGreaterThanOrEqual(results.at(-1)?.score || 0)
    expect(describeSearchMatch(results[0])).toContain('연결됐어요')
  })

  it('uses the latest duplicate-save date when present', () => {
    expect(effectiveSavedAt({ savedAt: '2026-10-01', lastSavedAt: '2026-11-04' })).toBe('2026-11-04')
    expect(effectiveSavedAt({ savedAt: '2026-10-01' })).toBe('2026-10-01')
  })

  it('preserves a user-edited title when analysis is retried', () => {
    const edited = { ...seedArchiveItems[0], id: 'user-1', title: '내가 바꾼 제목', analysisStatus: 'analyzing' as const }
    expect(completeArchiveAnalysis(edited).title).toBe('내가 바꾼 제목')
  })
})
