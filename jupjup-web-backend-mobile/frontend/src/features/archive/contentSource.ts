import type { ArchiveItem, ContentType } from './archiveData'

export type PlatformId = 'instagram' | 'youtube' | 'naver' | 'arxiv' | 'web' | 'text'

export type SourceInfo = {
  contentType: ContentType
  label: string
  source: string
  art: string
  platform: PlatformId
}

const newsHosts = [
  'news.naver.com', 'n.news.naver.com', 'news.google.com', 'bbc.com', 'bbc.co.uk',
  'cnn.com', 'reuters.com', 'apnews.com', 'yonhapnews.co.kr', 'yna.co.kr',
  'hankyung.com', 'chosun.com', 'hani.co.kr', 'khan.co.kr', 'mk.co.kr', 'ytn.co.kr',
]

const hostIs = (host: string, domain: string) => host === domain || host.endsWith(`.${domain}`)

export function parseHttpUrl(input: string): URL | null {
  try {
    const url = new URL(input.trim())
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) return null
    return url
  } catch {
    return null
  }
}

export function normalizeHttpUrl(input: string): string | null {
  const url = parseHttpUrl(input)
  if (!url) return null
  url.hash = ''
  url.hostname = url.hostname.toLowerCase()
  if (url.pathname.length > 1) url.pathname = url.pathname.replace(/\/+$/, '')
  return url.href
}

export function detectSource(url: URL): SourceInfo {
  const host = url.hostname.toLowerCase().replace(/^www\./, '')
  const path = url.pathname.toLowerCase()

  if (hostIs(host, 'instagram.com')) {
    const isReel = path.startsWith('/reel/')
    return { contentType: 'post', label: isReel ? 'Instagram 릴스' : 'Instagram 게시물', source: 'Instagram', art: 'editorial', platform: 'instagram' }
  }
  if (hostIs(host, 'youtube.com') || hostIs(host, 'youtu.be')) {
    const isShort = path.startsWith('/shorts/')
    return { contentType: 'video', label: isShort ? 'YouTube Shorts' : 'YouTube 영상', source: 'YouTube', art: 'motion', platform: 'youtube' }
  }
  if (hostIs(host, 'doi.org') || hostIs(host, 'arxiv.org')) {
    return { contentType: 'web', label: '논문', source: hostIs(host, 'doi.org') ? 'DOI' : 'arXiv', art: 'note', platform: 'arxiv' }
  }
  if (newsHosts.some((domain) => hostIs(host, domain))) {
    const isNaver = hostIs(host, 'naver.com')
    return { contentType: 'web', label: '뉴스 기사', source: isNaver ? 'NAVER 뉴스' : host, art: 'typography', platform: isNaver ? 'naver' : 'web' }
  }
  return { contentType: 'web', label: '웹페이지', source: host, art: 'workspace', platform: 'web' }
}

export function platformFromSource(type: string, source = ''): PlatformId {
  const name = source.toLowerCase()
  if (type === 'video' || name.includes('youtube')) return 'youtube'
  if (type === 'post' || name.includes('instagram')) return 'instagram'
  if (name.includes('arxiv') || name.includes('doi')) return 'arxiv'
  if (name.includes('naver')) return 'naver'
  if (type === 'note' || name.includes('메모')) return 'text'
  return 'web'
}

function titleFromUrl(item: ArchiveItem): string {
  const url = parseHttpUrl(item.url)
  if (!url) return item.title
  const tail = decodeURIComponent(url.pathname.split('/').filter(Boolean).at(-1) || '')
    .replace(/[-_]+/g, ' ')
    .replace(/\.[a-z0-9]{2,5}$/i, '')
    .trim()
  const genericSegments = new Set(['watch', 'shorts', 'reel', 'p', 'abs', 'pdf', 'article', 'post'])
  if (tail && !genericSegments.has(tail.toLocaleLowerCase()) && !/^\d+$/.test(tail) && tail.length > 2) return tail.slice(0, 54)
  if (item.source === 'YouTube') return '나중에 다시 볼 YouTube 영상'
  if (item.source === 'Instagram') return '저장한 Instagram 콘텐츠'
  if (item.source === 'arXiv' || item.source === 'DOI') return '저장한 논문 자료'
  if (item.source.includes('뉴스')) return '저장한 뉴스 기사'
  return `${item.source}에서 저장한 웹페이지`
}

export function createSampleAnalysis(item: ArchiveItem): Partial<ArchiveItem> {
  if (item.contentType === 'note') {
    const text = (item.userMemo || '').trim()
    const title = text.split(/\n/).map((line) => line.trim()).find(Boolean)?.slice(0, 54) || '직접 저장한 메모'
    const candidates = ['디자인', '개발', 'React', '피그마', '여행', '공부', '기획', '요리', '책', '아이디어']
    const matched = candidates.filter((word) => text.toLocaleLowerCase().includes(word.toLocaleLowerCase())).slice(0, 3)
    const tags = matched.length ? matched : ['내 기록']
    return {
      title,
      aiSummary: text.slice(0, 220) || '직접 저장한 텍스트를 정리한 샘플 결과입니다.',
      primaryTags: tags.slice(0, 2),
      detailTags: [...tags.slice(2), '텍스트'],
      art: 'note',
    }
  }

  const hintText = `${item.url} ${item.source}`.toLocaleLowerCase()
  const hintPairs = [['figma', '피그마'], ['react', 'React'], ['design', '디자인'], ['css', 'CSS'], ['travel', '여행'], ['recipe', '레시피'], ['typescript', 'TypeScript']]
  const hints = hintPairs.filter(([needle]) => hintText.includes(needle)).map(([, label]) => label)
  const typeTag = item.contentType === 'video' ? '영상' : item.contentType === 'post' ? '게시물' : item.source.includes('뉴스') ? '뉴스' : item.source === 'arXiv' || item.source === 'DOI' ? '논문' : '웹페이지'
  const tags = Array.from(new Set([typeTag, ...hints]))
  return {
    title: titleFromUrl(item),
    aiSummary: `${item.source}에서 저장한 콘텐츠의 핵심 내용을 AI가 정리한 프론트엔드 샘플 결과입니다. 실제 서비스에서는 원문 분석 결과가 여기에 표시됩니다.`,
    primaryTags: tags.slice(0, 2),
    detailTags: [...tags.slice(2), '새 콘텐츠'],
  }
}
