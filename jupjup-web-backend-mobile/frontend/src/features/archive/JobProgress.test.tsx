import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { JobDetail } from '@/shared/api/contracts'
import { JobProgress, progressMessage } from './JobProgress'
import { activeJob, jobPollInterval } from './queries'

const job: JobDetail = { id: 'j', status: 'running', current_stage: 'analyze', result_content_id: 'c', next_run_at: null, error: null, steps: [{ stage: 'fetch', status: 'succeeded', attempts: 1 }, { stage: 'analyze', status: 'running', attempts: 1 }, { stage: 'index', status: 'pending', attempts: 0 }] }
describe('job progress', () => {
  it('shows only reported step outcomes and announces the current stage', () => {
    render(<JobProgress job={job} pending={false} error={false} updatedAt={0} />)
    expect(screen.getByRole('status')).toHaveTextContent('내용 분석 단계가 진행 중')
    expect(screen.getByText('검색 반영').parentElement).toHaveTextContent('대기')
    expect(screen.getByText('내용 분석').parentElement).toHaveAttribute('aria-current', 'step')
  })
  it('describes retry and terminal outcomes without treating them as success', () => {
    expect(progressMessage({ ...job, status: 'retry_wait' })).toContain('다시 시도')
    expect(progressMessage({ ...job, status: 'needs_review' })).toContain('확인')
    expect(progressMessage({ ...job, status: 'rejected' })).toContain('적용하지')
    expect(progressMessage({ ...job, status: 'deduplicated' })).toContain('이미 저장된')
    expect(activeJob('awaiting_confirmation')).toBe(true)
    expect(activeJob('failed')).toBe(false)
    expect(jobPollInterval('running')).toBe(2000)
    expect(jobPollInterval('awaiting_confirmation')).toBe(2000)
    expect(jobPollInterval('failed')).toBe(false)
    expect(jobPollInterval('failed', true)).toBe(2000)
  })
})

it.each([['approved', '승인됨'], ['rejected', '거절됨']])('renders confirm state %s', (status, label) => {
  render(<JobProgress job={{ ...job, current_stage: 'confirm', steps: [{ stage: 'confirm', status, attempts: 1 }] }} pending={false} error={false} updatedAt={0} />)
  expect(screen.getByText(label)).toBeInTheDocument()
})
