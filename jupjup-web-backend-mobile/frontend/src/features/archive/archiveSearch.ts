import { searchAliases, type ArchiveCollection, type ArchiveItem } from './archiveData'

export type SearchField = 'title' | 'summary' | 'tag' | 'source' | 'collection'
export type SearchMatch = { item: ArchiveItem; matchedTerms: string[]; matchedFields: SearchField[]; score: number }

const fieldLabel: Record<SearchField, string> = {
  title: '제목', summary: 'AI 요약', tag: '태그', source: '출처', collection: '컬렉션',
}

export function searchArchive(items: ArchiveItem[], collections: ArchiveCollection[], query: string): SearchMatch[] {
  const terms = query.toLocaleLowerCase('ko').match(/[\p{L}\p{N}]+/gu) || []
  const expanded = new Set(terms)
  for (const [alias, values] of Object.entries(searchAliases)) {
    if (terms.some((term) => alias.toLocaleLowerCase('ko').includes(term) || term.includes(alias.toLocaleLowerCase('ko')))) {
      values.forEach((value) => expanded.add(value.toLocaleLowerCase('ko')))
    }
  }
  if (!expanded.size) return []
  return items.flatMap((item) => {
    const collectionNames = item.collectionIds.map((id) => collections.find((collection) => collection.id === id)?.name || '')
    const rawFields: Array<{ field: SearchField; value: string; weight: number }> = [
      { field: 'title', value: item.title, weight: 8 },
      { field: 'summary', value: item.aiSummary || '', weight: 4 },
      { field: 'tag', value: [...item.primaryTags, ...item.detailTags].join(' '), weight: 6 },
      { field: 'source', value: item.source, weight: 2 },
      { field: 'collection', value: collectionNames.join(' '), weight: 5 },
    ]
    const fields = rawFields.map((entry) => ({ ...entry, value: entry.value.toLocaleLowerCase('ko') }))
    const matchedTerms = Array.from(expanded).filter((term) => fields.some(({ value }) => value.includes(term)))
    if (!matchedTerms.length) return []
    const matchedFields = fields.filter(({ value }) => matchedTerms.some((term) => value.includes(term))).map(({ field }) => field)
    const normalizedQuery = query.trim().toLocaleLowerCase('ko')
    const phraseBonus = fields.some(({ value }) => value.includes(normalizedQuery)) ? 10 : 0
    const score = phraseBonus + fields.reduce((total, field) => total + matchedTerms.filter((term) => field.value.includes(term)).length * field.weight, 0)
    return [{ item, matchedTerms: matchedTerms.slice(0, 3), matchedFields, score }]
  }).sort((a, b) => b.score - a.score || b.item.savedAt.localeCompare(a.item.savedAt))
}

export function describeSearchMatch(match: Pick<SearchMatch, 'matchedTerms' | 'matchedFields'>): string {
  const fields = match.matchedFields.slice(0, 2).map((field) => fieldLabel[field]).join('·')
  const terms = match.matchedTerms.slice(0, 2).map((term) => `‘${term}’`).join(', ')
  return `${fields}에서 ${terms} 표현과 연결됐어요.`
}

export const searchSuggestions = ['오사카 여행 관련 영상', '오사카에서 저장한 맛집', '일본 여행 컬렉션의 교통 자료', '오사카 지하철 이용 방법', '피그마 오토레이아웃 자료', '개발 공부 참고자료']
