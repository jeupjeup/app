import { afterEach, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MetadataResult } from './MetadataResult'
import type { MetadataClassification } from '@/shared/api/contracts'

afterEach(cleanup)
export const metadataFixture: MetadataClassification = {
  source_scope: 'youtube_metadata', basis: 'title_description', classifier: 'local-metadata-rules-v1',
  metadata: { title: '[C++ 프로그래밍] 강의 소개', description: '강의자료\nhttps://github.com/example/cpp\n<script>alert(1)</script>', title_source: 'videoDetails.title', description_source: 'videoDetails.shortDescription', description_status: 'available', title_truncated: false, description_truncated: false, transcript_reason: 'empty_captions' },
  representative_tags: ['C++', '프로그래밍', '강의'], detail_tags: { schema_version: 1, category: 'tech', purpose: ['공부자료'] }, evidence: [{ field: 'title', source_span: 'C++', tag: 'C++' }],
}
it('shows real classification, bounded source, collapsed description and literal unsafe text', async () => {
  const { container } = render(<MetadataResult result={metadataFixture} />)
  expect(screen.getByText(/자막 미확보/)).toHaveTextContent('영상 전체의 요약이 아닙니다')
  expect(screen.getByText(/카테고리: 기술/)).toHaveTextContent('C++, 프로그래밍, 강의')
  expect(screen.getByText('출처: YouTube 설명란')).toBeInTheDocument()
  expect(screen.getByText('실제 설명 펼치기').closest('details')).not.toHaveAttribute('open')
  await userEvent.click(screen.getByText('실제 설명 펼치기'))
  expect(screen.getByText('실제 설명 펼치기').closest('details')).toHaveAttribute('open')
  expect(container.querySelector('script')).toBeNull()
  expect(screen.getByText(/<script>alert/).textContent).toContain('\nhttps://github.com/example/cpp\n')
  expect(screen.getByText(/제목의 “C\+\+”/)).toBeInTheDocument()
})
it('explains explicit metadata-only and insufficient title-only results', () => {
  const result = structuredClone(metadataFixture)
  result.basis = 'title_only'; result.metadata.description = ''; result.metadata.description_status = 'missing'; result.metadata.description_source = 'absent'; result.metadata.transcript_reason = 'not_requested'; result.representative_tags = []; result.detail_tags.category = 'other'; result.evidence = []
  render(<MetadataResult result={result} />)
  expect(screen.getByText(/자막 사용 안 함/)).toHaveTextContent('제목만으로 분류')
  expect(screen.getByText(/카테고리: 기타/)).toHaveTextContent('정보 부족으로 미분류')
  expect(screen.getByText('설명란을 제공하지 않았어요.')).toBeInTheDocument()
})

it('identifies the actual local model and automatic collection scope', () => {
  render(<MetadataResult result={{ ...metadataFixture, classifier: 'local-metadata-llm-v1', model: 'kanana-local@verified', summary: '공개 제목과 설명만을 근거로 생성한 요약입니다.' }} />)
  expect(screen.getByText(/로컬 LLM · kanana-local@verified/)).toBeInTheDocument()
  expect(screen.getByText(/LLM 분류에 따라 컬렉션에 자동 추가/)).toBeInTheDocument()
  expect(screen.getByText(/자막 미확보/)).toHaveTextContent('영상 전체의 요약이 아닙니다')
  expect(screen.queryByText(/로컬 규칙 분류/)).toBeNull()
})
