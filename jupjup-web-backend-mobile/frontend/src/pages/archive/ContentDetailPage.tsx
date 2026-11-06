import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useArchiveUi } from '@/features/archive/ArchiveLayout'
import { useArchiveStore } from '@/features/archive/ArchiveStore'
import { ContentArt } from '@/features/jupjup-dashboard/components/ContentCard'
import { Icon } from '@/features/jupjup-dashboard/components/Icon'
import { AccessibleDialog } from '@/features/archive/AccessibleDialog'
import { DetailTagGroups, typeNames } from '@/features/archive/presentation'
import { detailToItem, isMockSummary, statusLabel } from '@/features/archive/adapters'
import { activeJob, useContent, useJob, useRefreshArchive } from '@/features/archive/queries'
import { ContentCollectionPicker } from '@/features/archive/CollectionMembership'
import { MetadataResult } from '@/features/archive/MetadataResult'
import { JobProgress } from '@/features/archive/JobProgress'
import { RequestState } from '@/features/archive/RequestState'
import { deleteContent, patchContent, reanalyzeContent, reviewContent, SubmissionKeys } from '@/shared/api/contents'
import { ApiError, errorMessage } from '@/shared/api/client'
import { isAlias, type ContentPatch } from '@/shared/api/contracts'

export function ContentDetailPage() {
  const { contentId = '' } = useParams()
  const navigate = useNavigate()
  const { notify } = useArchiveUi()
  const { saveContent, favorites, toggleFavorite } = useArchiveStore()
  const query = useContent(contentId)
  const data = query.data?.data
  const detail = data && !isAlias(data) ? data : undefined
  const job = useJob(detail?.analysis.latest_job_id)
  const refresh = useRefreshArchive()
  const [editing, setEditing] = useState(false)
  const [summary, setSummary] = useState('')
  const [sourceText, setSourceText] = useState('')
  const [tags, setTags] = useState('')
  const [topics, setTopics] = useState('')
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  const keys = useRef(new SubmissionKeys())
  const seenJob = useRef('')
  const applyingCandidate = useRef('')
  const [applyAttempt, setApplyAttempt] = useState(0)
  useEffect(() => {
    const candidate = detail?.analysis.candidate
    if (detail?.status !== 'awaiting_confirmation' || !candidate || busy) return
    if (detail.analysis.source_text_reason === 'legacy_watch_snapshot' && candidate.source_scope !== 'youtube_metadata') return
    const key = `${contentId}:${candidate.id}:${applyAttempt}`
    if (applyingCandidate.current === key) return
    applyingCandidate.current = key
    setBusy(true)
    setFailure('')
    void reviewContent(contentId, candidate.id, 'approve')
      .then(async () => { await refresh(); await query.refetch(); notify('요약과 태그를 자동으로 정리했어요.') })
      .catch(async (error) => { setFailure(errorMessage(error)); await query.refetch() })
      .finally(() => setBusy(false))
  }, [detail, contentId, busy, applyAttempt, refresh, query.refetch, notify])
  useEffect(() => { setEditing(false); setFailure(''); keys.current.clear() }, [contentId])
  useEffect(() => {
    if (data && isAlias(data)) navigate(`/contents/${encodeURIComponent(data.canonical_id)}`, { replace: true })
  }, [data, navigate])
  useEffect(() => {
    if (!job.data) return
    const state = `${job.data.id}:${job.data.status}`
    if (state === seenJob.current) return
    seenJob.current = state
    if (!activeJob(job.data.status)) {
      void refresh()
      if (job.data.status === 'deduplicated') navigate(`/contents/${encodeURIComponent(job.data.result_content_id)}`, { replace: true })
    }
  }, [job.data, refresh, navigate])
  const perform = async (action: () => Promise<unknown>, success: string) => {
    if (busy) return
    setBusy(true); setFailure('')
    try { await action(); await refresh(); notify(success) }
    catch (error) {
      setFailure(errorMessage(error))
      if (error instanceof ApiError && ['VERSION_CONFLICT', 'REVIEW_CONFLICT', 'CONTENT_BUSY'].includes(error.code)) await query.refetch()
    } finally { setBusy(false) }
  }
  if (!detail) return <main className="content archive-content"><RequestState loading={query.isPending} error={query.error} retry={() => void query.refetch()} />{!query.isPending && !query.error && <p>콘텐츠 상태를 확인하고 있어요.</p>}</main>
  const item = detailToItem(detail)
  const running = job.data ? activeJob(job.data.status) : detail.status === 'pending' || detail.status === 'awaiting_confirmation'
  const sourceUnavailable = !detail.analysis.source_text_available
  const canRetrySnapshot = !sourceUnavailable && !!detail.snapshot && job.data?.error?.code !== 'SOURCE_TEXT_UNAVAILABLE'
  const legacyWatch = detail.analysis.source_text_reason === 'legacy_watch_snapshot'
  const metadata = detail.analysis.metadata
  const candidate = legacyWatch && detail.analysis.candidate?.source_scope !== 'youtube_metadata' ? null : detail.analysis.candidate
  const youtube = detail.platform === 'youtube' && detail.source.kind === 'url'

  const mock = detail.summary.is_mock || (detail.summary.source !== "user" && isMockSummary(detail.summary.effective))
  const openEditor = () => {
    setSummary(detail.summary.effective || '')
    setTags(detail.representative_tags.effective.join(', '))
    setTopics((detail.detail_tags.effective.topics || []).join(', '))
    setEditing(true)
  }
  const split = (text: string) => [...new Set(text.split(',').map(s => s.trim()).filter(Boolean))]
  const saveInfo = (event: FormEvent) => {
    event.preventDefault()
    const patch: ContentPatch = {}
    if (summary !== (detail.summary.effective || '')) patch.summary = summary.trim()
    if (tags !== detail.representative_tags.effective.join(', ')) patch.representative_tags = split(tags)
    if (topics !== (detail.detail_tags.effective.topics || []).join(', ')) patch.detail_tags = { topics: split(topics) }
    void perform(async () => {
      if (!query.data?.etag) throw new Error('ETag unavailable')
      await patchContent(contentId, patch, query.data.etag)
      setEditing(false)
    }, '사용자 요약과 태그를 저장했어요.')
  }
  const resetOverrides = () => void perform(async () => {
    if (!query.data?.etag) throw new Error('ETag unavailable')
    await patchContent(contentId, { summary: null, representative_tags: null, detail_tags: null }, query.data.etag)
  }, legacyWatch ? '사용자 수정을 해제했어요. 영상 본문 확보 실패로 기존 AI 결과는 표시하지 않아요.' : '사용자 수정을 해제했어요. AI 결과가 있으면 다시 표시됩니다.')
  const reanalyze = () => void perform(async () => {
    const level = 'auto'
    await reanalyzeContent(contentId, level, await keys.current.keyFor(contentId, { automation_level: level }))
    keys.current.clear()
  }, '저장된 원문으로 재분석을 접수했어요.')
  const fetchMetadata = () => void perform(async () => {
    const level = 'auto'
    const body = { automation_level: level, mode: 'youtube_metadata' }
    await reanalyzeContent(contentId, level, await keys.current.keyFor(contentId, body), 'youtube_metadata')
    keys.current.clear()
  }, '공개 제목·설명 수집과 분류를 접수했어요.')
  const remove = () => {
    if (!window.confirm('콘텐츠와 처리 기록을 영구 삭제할까요? 복구할 수 없어요.')) return
    void perform(async () => { await deleteContent(contentId); navigate('/contents', { replace: true }) }, '콘텐츠를 삭제했어요.')
  }
  return <main className="content archive-content detail-page">
    <div className="detail-back"><button type="button" onClick={() => navigate('/contents')}><Icon name="arrow" small />보관함</button><span>{metadata || candidate?.source_scope === 'youtube_metadata' ? '저장된 정보 · 제목·설명 기반 분류' : mock ? '저장된 정보 · 시험용 분석' : '저장된 정보 · 로컬 LLM 분석'}</span></div>
    <RequestState error={query.error} retry={() => void query.refetch()} />
    {failure && <div role="alert" className="source-warning"><p>{failure}</p><p>입력은 유지됩니다. 충돌이면 최신 내용을 확인한 후 다시 저장해 주세요.</p></div>}
    <section className="detail-hero">
      <div className="detail-visual"><ContentArt kind={item.art} /><span className={`detail-status ${item.analysisStatus}`}>{statusLabel(detail.status)}</span></div>
      <div className="detail-overview"><div className="detail-meta-line"><span>{item.source}</span><i>·</i><span>{detail.source.kind === 'text' ? '메모' : typeNames[detail.content_type] || '콘텐츠'}</span><i>·</i><span>{new Date(item.savedAt).toLocaleString('ko-KR')} 저장</span></div>
        <h1>{item.title}</h1><ContentCollectionPicker contentId={contentId} collectionIds={detail.collection_ids || []} />
        <div className="detail-primary-actions">{item.url && item.sourceStatus !== 'unavailable' ? <a className="button primary" href={item.url} target="_blank" rel="noreferrer">원본 열기 <Icon name="external" small /></a> : <button className="button primary" disabled>원본 링크 없음</button>}<button className="button" type="button" aria-pressed={favorites.includes(contentId)} onClick={() => { try { const wasFavorite = favorites.includes(contentId); toggleFavorite(contentId); notify(wasFavorite ? '즐겨찾기에서 제외했어요.' : '즐겨찾기에 추가했어요.') } catch { notify('즐겨찾기를 저장하지 못했어요. 브라우저 저장 공간을 확인해 주세요.') } }}><Icon name="star" small />{favorites.includes(contentId) ? '즐겨찾기 해제' : '즐겨찾기'}</button></div>
        <p>{item.sourceStatus === 'unknown' ? '원본의 현재 접근 가능 여부는 확인하지 않았어요.' : item.sourceStatus === 'unavailable' ? '원본이 없어도 저장된 내용은 유지돼요.' : ''}</p>
      </div>
    </section>
    <section className="detail-section" aria-label="콘텐츠 정리 상태">
      <div className="detail-section-heading"><h2>콘텐츠 정리</h2><button type="button" className="button" onClick={() => { void query.refetch(); void job.refetch() }}>상태 확인</button></div>
      {detail.analysis.latest_job_id ? <JobProgress job={job.data} pending={job.isPending} error={!!job.error} updatedAt={job.dataUpdatedAt} /> : <p role="status">{detail.status === 'ready' ? '콘텐츠 정리가 완료됐어요.' : statusLabel(detail.status)}</p>}
      {legacyWatch && <div><h3>영상 본문 확보 실패</h3><p>영상 내용을 가져오지 못해 본문을 요약할 수 없어요. 사용자가 직접 수정한 요약과 태그는 보존하여 표시합니다. 기존 원문도 확인할 수 있어요.</p></div>}
      {(detail.status === 'analysis_failed' || job.data?.status === 'failed' || job.data?.status === 'needs_review') && canRetrySnapshot && <button type="button" className="button" onClick={reanalyze} disabled={busy || running}>다시 정리하기</button>}
      {(legacyWatch || detail.status === 'analysis_failed') && <form className="form-fields" onSubmit={event => {
        event.preventDefault()
        void perform(async () => {
          const result = await saveContent({ kind: 'text', value: sourceText })
          navigate(`/contents/${encodeURIComponent(result.result_content_id)}`)
        }, '입력한 내용을 별도 항목으로 저장했어요. 기존 원본과 수정 내용은 유지됩니다.')
      }}><p>영상 내용이나 자막을 붙여 넣으면 새 콘텐츠로 저장해요.</p><div className="form-field"><label htmlFor="replacementText">영상 내용·자막 텍스트</label><textarea id="replacementText" value={sourceText} onChange={event => setSourceText(event.target.value)} maxLength={100000} required /></div><button className="button primary" disabled={busy || !sourceText.trim()}>입력한 텍스트로 새 항목 저장</button></form>}
      {youtube && <div><button type="button" className="button" onClick={fetchMetadata} disabled={busy || running}>제목·설명 가져오기/분류</button><p>영상 본문 대신 공개된 정보만 사용해요.</p></div>}
    </section>
    {candidate && detail.status === 'awaiting_confirmation' && <section className="detail-section" aria-label="분석 결과 자동 적용"><h2>분석 결과 정리</h2><p>{busy ? '요약과 태그를 자동으로 적용하고 있어요.' : failure ? '자동 적용을 완료하지 못했어요.' : '분석 결과를 정리하고 있어요.'}</p>{failure && <button type="button" className="button" disabled={busy} onClick={() => setApplyAttempt(value => value + 1)}>자동 정리 다시 시도</button>}</section>}
    {metadata && <section className="detail-section"><MetadataResult result={metadata} /><p role="note">{metadata.classifier === 'local-metadata-llm-v1' ? 'YouTube 제목·설명 분류는 로컬 LLM 결과입니다.' : 'YouTube 제목·설명 분류는 로컬 규칙 결과입니다.'} mock 분석은 시험용 고정 예시입니다.</p></section>}
    <div className="detail-layout"><div className="detail-main">
      <section className="detail-section"><div className="detail-section-heading"><h2>{metadata ? (detail.summary.source === 'user' ? '사용자 요약과 분류 태그' : metadata.classifier === 'local-metadata-llm-v1' ? '제목·설명 기반 요약과 태그' : '사용자 요약과 분류 태그') : legacyWatch ? '사용자 요약과 태그' : detail.summary.source === 'user' ? '사용자 요약' : mock ? '시험용 분석 결과' : 'AI 요약'}</h2><span>{statusLabel(detail.status)}</span></div>{!metadata && !mock && detail.summary.model && <p>로컬 LLM · {detail.summary.model} · 저장한 원문 기반 분석 · 분류 결과로 컬렉션에 자동 추가해요.</p>}<p className="ai-summary" style={{ whiteSpace: 'pre-wrap' }}>{item.aiSummary || '아직 적용된 요약이 없어요.'}</p><div className="tag-groups"><div><h3>{mock ? "시험용 대표 태그" : "대표 태그"}</h3><div>{!item.primaryTags.length && <span>아직 대표 태그가 없어요.</span>}{item.primaryTags.map(tag => <span key={tag} className="primary-tag">#{tag}</span>)}</div></div><div><h3>{mock ? "시험용 세부 태그" : "세부 태그"}</h3><div>{!item.detailTags.length && <span>아직 세부 태그가 없어요.</span>}{item.detailTags.map(tag => <span key={tag}>#{tag}</span>)}</div></div></div><DetailTagGroups tags={detail.detail_tags.effective} /></section>
      <section className="detail-section"><div className="detail-section-heading"><h2>저장된 원문</h2></div>{legacyWatch ? <details><summary>보존된 YouTube 페이지 원문 펼치기</summary><p style={{ whiteSpace: 'pre-wrap' }}>{detail.snapshot?.text}</p></details> : <p style={{ whiteSpace: 'pre-wrap' }}>{detail.snapshot?.text || detail.snapshot?.ocr_text || '아직 원문이 수집되지 않았어요.'}</p>}</section>
      <section className="detail-section"><div className="detail-section-heading"><h2>내 메모</h2><button disabled>기존 메모 수정 미지원</button></div><p className="user-memo">{item.userMemo || '저장할 때 입력한 메모가 없어요.'}</p></section>
    </div><aside className="detail-side"><section><h3>콘텐츠 관리</h3><button onClick={openEditor} disabled={busy}><Icon name="edit" small />요약과 태그 수정</button><button onClick={resetOverrides} disabled={busy}>사용자 수정 해제</button><button onClick={() => void perform(async () => { if (!query.data?.etag) throw new Error('ETag unavailable'); await patchContent(contentId, { hidden: !detail.hidden }, query.data.etag) }, detail.hidden ? '숨김을 해제했어요.' : '목록과 검색에서 숨겼어요.')} disabled={busy}>{detail.hidden ? '숨김 해제' : '콘텐츠 숨기기'}</button><button onClick={reanalyze} disabled={busy || running || !canRetrySnapshot}><Icon name="clock" small />저장 원문 재분석</button><button className="danger-link" onClick={remove} disabled={busy}><Icon name="trash" small />콘텐츠 삭제</button><p>제목·기존 메모 수정은 서버 미지원입니다. 즐겨찾기는 이 브라우저에 저장됩니다.</p></section></aside></div>
    {editing && <AccessibleDialog titleId="editContentTitle" onClose={() => { if (!busy) setEditing(false) }}><div className="dialog-header"><h2 id="editContentTitle">요약과 태그 수정</h2><button disabled={busy} className="dialog-close" aria-label="닫기" onClick={() => setEditing(false)}><Icon name="x" /></button></div><form className="form-fields" onSubmit={saveInfo}><div className="form-field"><label htmlFor="contentTitle">제목 · 서버 수정 미지원</label><input id="contentTitle" value={item.title} disabled /></div><div className="form-field"><label htmlFor="contentSummary">사용자 요약 · 1~1000자</label><textarea id="contentSummary" value={summary} onChange={event => setSummary(event.target.value)} maxLength={1000} required /></div><div className="form-field"><label htmlFor="contentPrimaryTags">대표 태그 · 최대 15개</label><input id="contentPrimaryTags" value={tags} onChange={event => setTags(event.target.value)} /></div><div className="form-field"><label htmlFor="contentDetailTags">주제 · 최대 10개, 각 30자</label><input id="contentDetailTags" value={topics} onChange={event => setTopics(event.target.value)} /><small>쉼표로 구분해요. 다른 세부 정보는 유지됩니다.</small></div>{failure && <p role="alert">{failure}</p>}<div className="dialog-footer"><button type="button" className="button" disabled={busy} onClick={() => setEditing(false)}>취소</button><button className="button primary" disabled={busy}>저장하기</button></div></form></AccessibleDialog>}
  </main>
}
