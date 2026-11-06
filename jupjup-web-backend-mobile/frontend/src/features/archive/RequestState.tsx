import { errorMessage } from '@/shared/api/client'
export function RequestState({ loading, error, retry }: { loading?: boolean; error?: unknown; retry?: () => void }) {
  if (error) return <div className="source-warning" role="alert"><p>{errorMessage(error)}</p>{retry && <button className="button" onClick={retry}>다시 확인</button>}</div>
  if (loading) return <p role="status" className="archive-result-count">서버에서 불러오는 중…</p>
  return null
}
