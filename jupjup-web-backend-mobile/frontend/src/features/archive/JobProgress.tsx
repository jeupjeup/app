import type { JobDetail } from '@/shared/api/contracts'
import { processingLabel } from './presentation'

const stepState: Record<string, string> = { pending: '대기', running: '진행 중', succeeded: '완료', skipped: '해당 없음', waiting: '확인 대기', retry_wait: '재시도 대기', failed: '실패', approved: '승인됨', rejected: '거절됨' }
export function progressMessage(job: JobDetail): string {
  const stage = processingLabel(job.current_stage)
  switch (job.status) {
    case 'queued': return '정리를 접수했어요. 작업 순서를 기다리고 있어요.'
    case 'running':
      return job.current_stage === 'analyze'
        ? `지금 ${stage} 단계가 진행 중이에요. (AI 분석은 원래 시간이 다소 걸려요)`
        : `지금 ${stage} 단계가 진행 중이에요.`
    case 'retry_wait': return `${stage} 단계에서 잠시 멈췄어요. 자동으로 다시 시도해요.`
    case 'awaiting_confirmation': return '분석 결과를 적용하기 위한 확인을 기다리고 있어요.'
    case 'needs_review': return '자동으로 정리하지 못해 확인이 필요해요.'
    case 'succeeded': return '콘텐츠 정리가 완료됐어요.'
    case 'failed': return '정리를 마치지 못했어요. 저장한 콘텐츠는 그대로 보관되어 있어요.'
    case 'rejected': return '분석 제안을 적용하지 않았어요.'
    case 'deduplicated': return '이미 저장된 콘텐츠에 연결했어요.'
    case 'cancelled': return '정리가 취소됐어요.'
    default: return '정리 상태를 확인하고 있어요.'
  }
}
export function JobProgress({ job, pending, error, updatedAt }: { job?: JobDetail; pending: boolean; error: boolean; updatedAt: number }) {
  const message = error ? '정리 상태를 불러오지 못했어요. 자동으로 다시 확인합니다.' : job ? progressMessage(job) : pending ? '정리 상태를 확인하고 있어요.' : '아직 작업 상태가 없어요.'
  return <div className="job-progress">
    <p className="job-progress-message" role="status" aria-live="polite">{message}</p>
    {job && job.current_stage === 'analyze' && ['running', 'queued'].includes(job.status) && (
      <p className="job-progress-notice" style={{ fontSize: '12px', color: '#855b32', margin: '4px 0 10px' }}>
        AI 모델이 본문 전체를 읽고 요약과 태그를 추출하는 분석 작업은 원래 30초~1분 이상 소요될 수 있어요.
      </p>
    )}
    {job && <>
      <ol className="job-progress-path" aria-label="정리 단계">{job.steps.map(step => <li key={step.stage} className={`job-step job-step-${step.status}`} aria-current={step.stage === job.current_stage && ['running', 'queued', 'retry_wait', 'awaiting_confirmation'].includes(job.status) ? 'step' : undefined}><span>{processingLabel(step.stage)}</span><small>{stepState[step.status] || '상태 확인 필요'}</small></li>)}</ol>
      {job.status === 'retry_wait' && job.next_run_at && <p>다음 시도 예정: {new Date(job.next_run_at).toLocaleString('ko-KR')}</p>}
    </>}
    {updatedAt > 0 && <p className="job-progress-updated">마지막 확인: {new Date(updatedAt).toLocaleTimeString('ko-KR')} {job && ['queued', 'running', 'retry_wait', 'awaiting_confirmation'].includes(job.status) && '· 자동으로 상태를 확인하고 있어요'}</p>}
  </div>
}
