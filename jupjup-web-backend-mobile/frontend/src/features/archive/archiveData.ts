export type AnalysisStatus = 'analyzing' | 'completed' | 'failed'
export type SourceStatus = 'available' | 'unavailable' | 'unknown'
export type ContentType = 'video' | 'post' | 'web' | 'note'
export type ArchiveDisplay = 'grid' | 'list'
export type ArchiveSort = 'new' | 'old' | 'title'
export type OrganizeMode = 'automatic' | 'confirm'

export type ArchiveItem = {
  id: string
  title: string
  url: string
  source: string
  contentType: ContentType
  savedAt: string
  lastSavedAt?: string
  contentLabel?: string
  serverStatus?: string
  analysisStatus: AnalysisStatus
  sourceStatus: SourceStatus
  aiSummary?: string
  primaryTags: string[]
  detailTags: string[]
  collectionIds: string[]
  userMemo?: string
  relatedContentIds: string[]
  favorite: boolean
  art: string
}

export type ArchiveCollection = {
  contentCount?: number
  id: string
  name: string
  color: string
  bg: string
  ink: string
  updatedAt: string
  organizeMode: 'automatic' | 'confirm' | 'manual'
}

export type ArchiveSettings = {
  organizeMode: OrganizeMode
  analysisNotifications: boolean
  organizeNotifications: boolean
  defaultDisplay: ArchiveDisplay
  defaultSort: ArchiveSort
}

export const contentTypeName: Record<ContentType, string> = {
  video: '영상', post: '게시물', web: '웹페이지', note: '메모',
}

export const seedArchiveCollections: ArchiveCollection[] = [
  { id: 'design', name: '디자인 레퍼런스', color: '#DDB8E5', bg: '#F6EAF9', ink: '#9562A1', updatedAt: '2026-11-03', organizeMode: 'confirm' },
  { id: 'develop', name: '개발 노트', color: '#B3D5F1', bg: '#EAF3FC', ink: '#608EB5', updatedAt: '2026-11-02', organizeMode: 'confirm' },
  { id: 'life', name: '일상과 영감', color: '#E6CA9C', bg: '#FBF1DE', ink: '#A27C45', updatedAt: '2026-10-31', organizeMode: 'manual' },
  { id: 'travel', name: '일본 여행', color: '#B9D3BD', bg: '#E9F4EA', ink: '#6F9E78', updatedAt: '2026-11-04', organizeMode: 'automatic' },
]

export const seedArchiveItems: ArchiveItem[] = [
  { id: 'osaka-subway', title: '오사카 지하철 처음 타는 사람을 위한 노선 정리', url: 'https://example.com/osaka-subway', source: 'YouTube', contentType: 'video', savedAt: '2026-11-04', analysisStatus: 'completed', sourceStatus: 'available', aiSummary: '오사카 주요 지하철 노선과 교통카드 사용법, 환승할 때 알아둘 점을 한 번에 설명한 여행 영상이에요.', primaryTags: ['오사카', '교통'], detailTags: ['일본', '지하철', '여행 준비'], collectionIds: ['travel'], userMemo: '간사이 공항 도착 전에 다시 보기', relatedContentIds: ['osaka-food', 'tokyo-cafe'], favorite: true, art: 'motion' },
  { id: 'figma-layout', title: '피그마 오토레이아웃 제대로 이해하기', url: 'https://example.com/figma-layout', source: 'YouTube', contentType: 'video', savedAt: '2026-11-03', analysisStatus: 'completed', sourceStatus: 'available', aiSummary: '오토레이아웃의 정렬, 간격, 리사이징 원리를 실제 컴포넌트 예제로 설명해요.', primaryTags: ['피그마', 'UI'], detailTags: ['오토레이아웃', '컴포넌트', '디자인 시스템'], collectionIds: ['design', 'develop'], relatedContentIds: ['design-system', 'spacing-rules'], favorite: true, art: 'figma' },
  { id: 'osaka-food', title: '오사카에서 꼭 먹어볼 작은 식당 8곳', url: 'https://example.com/osaka-food', source: 'Instagram', contentType: 'post', savedAt: '2026-11-02', analysisStatus: 'completed', sourceStatus: 'available', aiSummary: '현지인이 자주 찾는 우동, 오코노미야키, 디저트 가게를 동선별로 소개한 게시물이에요.', primaryTags: ['오사카', '맛집'], detailTags: ['일본', '여행', '식당'], collectionIds: ['travel', 'life'], relatedContentIds: ['osaka-subway'], favorite: false, art: 'food' },
  { id: 'react-components', title: 'React 컴포넌트 설계할 때 생각할 것들', url: 'https://example.com/react-components', source: 'Web', contentType: 'web', savedAt: '2026-11-01', analysisStatus: 'completed', sourceStatus: 'available', aiSummary: '컴포넌트의 책임을 나누고 재사용 가능한 인터페이스를 설계하는 기준을 정리한 글이에요.', primaryTags: ['React', '프론트엔드'], detailTags: ['TypeScript', '개발', '컴포넌트'], collectionIds: ['develop'], relatedContentIds: ['typescript-note'], favorite: false, art: 'code' },
  { id: 'design-system', title: '컬러 팔레트에서 시작하는 디자인 시스템', url: 'https://example.com/design-system', source: 'Instagram', contentType: 'post', savedAt: '2026-10-29', analysisStatus: 'failed', sourceStatus: 'available', aiSummary: undefined, primaryTags: [], detailTags: [], collectionIds: ['design'], relatedContentIds: ['figma-layout'], favorite: false, art: 'palette' },
  { id: 'new-article', title: '새로 저장한 디자인 아티클', url: 'https://example.com/new-design', source: 'Web', contentType: 'web', savedAt: '2026-10-28', analysisStatus: 'analyzing', sourceStatus: 'available', primaryTags: [], detailTags: [], collectionIds: [], relatedContentIds: [], favorite: false, art: 'editorial' },
  { id: 'tokyo-cafe', title: '도쿄에서 발견한 조용한 카페 공간', url: 'https://example.com/tokyo-cafe', source: 'Web', contentType: 'web', savedAt: '2026-10-25', analysisStatus: 'completed', sourceStatus: 'unavailable', aiSummary: '도쿄 골목의 작은 카페와 재료, 조명, 좌석 배치를 기록한 공간 레퍼런스예요.', primaryTags: ['도쿄', '카페'], detailTags: ['인테리어', '일본', '공간'], collectionIds: ['travel', 'design'], relatedContentIds: ['osaka-subway'], favorite: true, art: 'cafe' },
  { id: 'spacing-rules', title: '좋은 인터페이스를 만드는 여백의 규칙', url: 'https://example.com/spacing', source: 'Web', contentType: 'web', savedAt: '2026-10-20', analysisStatus: 'completed', sourceStatus: 'available', aiSummary: '정보의 관계를 명확하게 만드는 간격, 정렬, 시각적 계층 원칙을 사례와 함께 정리했어요.', primaryTags: ['UI/UX', '레이아웃'], detailTags: ['여백', '디자인', '타이포그래피'], collectionIds: ['design'], relatedContentIds: ['figma-layout'], favorite: false, art: 'typography' },
  { id: 'typescript-note', title: 'TypeScript 타입 정리 노트', url: '', source: '직접 메모', contentType: 'note', savedAt: '2026-10-18', analysisStatus: 'completed', sourceStatus: 'available', aiSummary: '유니언 타입과 인터페이스의 차이를 프로젝트 예제와 함께 정리한 개인 메모예요.', primaryTags: ['TypeScript', '개발'], detailTags: ['타입', '프론트엔드', '과제'], collectionIds: ['develop'], relatedContentIds: ['react-components'], favorite: false, art: 'typescript' },
  { id: 'workspace', title: '책상 위 작은 기록들, 워크스페이스 아이디어', url: 'https://example.com/workspace', source: 'Instagram', contentType: 'post', savedAt: '2026-09-21', analysisStatus: 'completed', sourceStatus: 'available', aiSummary: '작업에 집중하기 좋은 책상 배치와 수납 아이디어를 모은 이미지 자료예요.', primaryTags: ['공간', '영감'], detailTags: ['워크스페이스', '수납'], collectionIds: [], relatedContentIds: [], favorite: false, art: 'workspace' },
]

export const defaultArchiveSettings: ArchiveSettings = {
  organizeMode: 'confirm', analysisNotifications: true, organizeNotifications: true, defaultDisplay: 'grid', defaultSort: 'new',
}

export const searchAliases: Record<string, string[]> = {
  오사카: ['일본', '여행', '교통', '지하철'],
  피그마: ['ui', '디자인', '오토레이아웃'],
  과제: ['논문', '기사', '통계', '참고자료'],
  개발: ['react', 'typescript', '프론트엔드'],
}

export const isoToday = () => {
  const now = new Date()
  return [now.getFullYear(), String(now.getMonth() + 1).padStart(2, '0'), String(now.getDate()).padStart(2, '0')].join('-')
}
export const effectiveSavedAt = (item: Pick<ArchiveItem, 'savedAt' | 'lastSavedAt'>) => item.lastSavedAt || item.savedAt
const archiveDate = (date: string) => new Date(/^\d{4}-\d{2}-\d{2}$/.test(date) ? `${date}T12:00:00+09:00` : date).getTime()
export const isWithinRecentDays = (date: string, days = 7) => { const difference = (Date.now() - archiveDate(date)) / 86_400_000; return difference >= 0 && difference <= days }
export const isOlderThanDays = (date: string, days = 30) => (Date.now() - archiveDate(date)) / 86_400_000 > days
export const completeArchiveAnalysis = (item: ArchiveItem): ArchiveItem => ({ ...item, analysisStatus: 'completed', aiSummary: '저장한 콘텐츠의 내용을 AI가 요약한 프론트엔드 데모 예시입니다.', primaryTags: ['참고자료'], detailTags: [item.contentType === 'note' ? '새 메모' : '새 콘텐츠', item.contentType === 'note' ? '텍스트' : '웹페이지'] })
