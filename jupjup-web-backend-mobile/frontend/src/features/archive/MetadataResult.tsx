import { categoryName } from './categories'
import type { MetadataClassification } from '@/shared/api/contracts'

export function MetadataResult({ result }: { result: Pick<MetadataClassification, 'metadata' | 'basis' | 'representative_tags' | 'detail_tags' | 'evidence'> & Partial<Pick<MetadataClassification, 'classifier' | 'summary' | 'model'>> }) {
  const m = result.metadata
  return <div aria-label="제목·설명 기반 분류 결과">
    <h3>제목·설명 기반 분류</h3>
    <p>{m.transcript_reason === 'not_requested' ? '자막 사용 안 함' : '자막 미확보'} · {result.basis === 'title_only' ? '설명이 없어 제목만으로 분류했어요.' : '공개 제목과 실제 설명란만으로 분류했어요.'} 영상 전체의 요약이 아닙니다.</p>
    <p style={{ overflowWrap: 'anywhere' }}>{result.classifier === 'local-metadata-llm-v1' ? `로컬 LLM · ${result.model || '모델 정보 없음'}` : '로컬 규칙 분류'} · 카테고리: {categoryName(result.detail_tags.category)}{result.representative_tags.length ? ` · ${result.representative_tags.join(', ')}` : ' · 정보 부족으로 미분류'}</p>
    <p style={{ overflowWrap: 'anywhere' }}>수집한 제목: {m.title}{m.title_truncated && ' (길이 상한으로 잘림)'}</p>
    <details><summary>실제 설명 펼치기</summary><p>출처: {m.description_source === 'absent' ? '설명 필드 없음' : 'YouTube 설명란'}{m.description_truncated && ' · 20,000자 상한으로 잘림'}</p><p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{m.description || (m.description_status === 'empty' ? '설명란이 비어 있어요.' : '설명란을 제공하지 않았어요.')}</p></details>
    {result.classifier === 'local-metadata-llm-v1' && <p>LLM 분류에 따라 컬렉션에 자동 추가해요. 기존 수동 소속은 유지해요.</p>}
    <details><summary>분류 근거</summary>{result.evidence.length ? <ul>{result.evidence.map((e, i) => <li key={i}>{e.tag}: {e.field === 'title' ? '제목' : '설명'}의 “{e.source_span}”</li>)}</ul> : <p>{result.classifier === 'local-metadata-llm-v1' ? '제목과 위 설명을 근거로 생성했어요. 정확한 내용은 원문에서 확인해 주세요.' : '분류할 충분한 단서가 없어요.'}</p>}</details>
  </div>
}
