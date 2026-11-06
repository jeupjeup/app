import { categoryName } from './categories'
import type { DetailTags } from '@/shared/api/contracts'
export const platformNames: Record<string, string> = { instagram: '인스타그램', youtube: '유튜브', kakaotalk: '카카오톡', news: '뉴스', blog: '블로그', x: '엑스', web: '웹', local: '직접 저장' }
export const typeNames: Record<string, string> = { post: '게시물', short_video: '짧은 영상', video: '영상', article: '아티클', paper: '논문', image: '이미지', message: '메시지', webpage: '웹페이지' }
const labels: Record<string, string> = {
  queued: '접수 대기', running: '처리 중', retry_wait: '자동 재시도 대기', awaiting_confirmation: '적용 확인 대기', succeeded: '처리 완료', failed: '처리 실패', needs_review: '분석 결과 검토 필요', rejected: '제안 미적용', deduplicated: '기존 콘텐츠에 연결됨', cancelled: '처리 취소됨',
  fetch: '원본 가져오기', extract: '본문 정리', vision: '이미지 텍스트 처리', chunk: '본문 나누기', analyze: '내용 분석', confirm: '제안 확인', persist: '분석 결과 저장', embed: '검색 준비', index: '검색 반영',
  pending: '대기', skipped: '해당 없음', waiting: '확인 대기', approved: '승인됨',
}
export const processingLabel = (value: string) => labels[value] || '상태 확인 필요'
export function DetailTagGroups({ tags }: { tags: DetailTags }) {
  const groups: [string, string[]][] = [
    ['분류', typeof tags.category === 'string' ? [categoryName(tags.category)] : []],
    ['주제', tags.topics || []], ['키워드', tags.keywords || []],
    ['저장 목적', Array.isArray(tags.purpose) ? tags.purpose.filter((v): v is string => typeof v === 'string') : []],
    ['장소', Array.isArray(tags.locations) ? tags.locations.flatMap(v => v && typeof v === 'object' && 'name' in v && typeof v.name === 'string' ? [v.name] : []) : []],
  ]
  return <div className="tag-groups">{groups.filter(([, values]) => values.length).map(([label, values]) => <div key={label}><h3>{label}</h3><div>{values.map((value, index) => <span key={`${value}-${index}`}>{value}</span>)}</div></div>)}</div>
}
