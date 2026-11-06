import { statusLabel as serverStatusLabel } from '@/features/archive/adapters'
import { errorMessage } from '@/shared/api/client'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useArchiveUi } from '@/features/archive/ArchiveLayout'
import { useArchiveStore } from '@/features/archive/ArchiveStore'
import { detectSource, parseHttpUrl, platformFromSource } from '@/features/archive/contentSource'
import { PlatformLogo } from '@/features/archive/PlatformLogo'
import { Icon } from '@/features/jupjup-dashboard/components/Icon'
import '@/features/archive/new-content.css'

type Mode = 'url' | 'text'


export function NewContentPage() {
  const navigate = useNavigate()
  const { notify } = useArchiveUi()
  const { items, saveContent } = useArchiveStore()
  const [pending, setPending] = useState(false)
  const [failure, setFailure] = useState('')
  const [mode, setMode] = useState<Mode>('url')
  const [urlValue, setUrlValue] = useState('')
  const [textValue, setTextValue] = useState('')
  const [touched, setTouched] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const textRef = useRef<HTMLTextAreaElement>(null)
  const urlTabRef = useRef<HTMLButtonElement>(null)
  const textTabRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus())
    return () => window.cancelAnimationFrame(frame)
  }, [])

  const value = (mode === 'url' ? urlValue : textValue).trim()
  const url = mode === 'url' ? parseHttpUrl(value) : null
  const source = url ? detectSource(url) : null
  const invalidUrl = mode === 'url' && touched && Boolean(value) && !url
  const canSubmit = Boolean(value) && (mode === 'text' || Boolean(url))
  const recent = items.slice(0, 4)

  const chooseMode = (next: Mode, focusInput = true) => {
    setMode(next)
    setTouched(false)
    if (focusInput) window.requestAnimationFrame(() => (next === 'url' ? inputRef.current : textRef.current)?.focus())
  }

  const moveTab = (event: React.KeyboardEvent<HTMLButtonElement>, next: Mode) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const target = event.key === 'Home' ? 'url' : event.key === 'End' ? 'text' : next
    chooseMode(target, false)
    ;(target === 'url' ? urlTabRef : textTabRef).current?.focus()
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setTouched(true)
    if (!canSubmit || pending) return
    setPending(true)
    setFailure('')
    try {
      const result = await saveContent({ kind: mode, value })
      notify({ message: result.deduplicated ? '이미 저장한 콘텐츠예요. 기존 내용과 날짜는 유지됩니다.' : '저장 요청을 접수했어요. 서버 처리 상태를 확인해 주세요.', actions: [{ label: '상세 보기', onClick: () => navigate(`/contents/${encodeURIComponent(result.result_content_id)}`) }] })
      if (mode === 'url') setUrlValue('')
      else setTextValue('')
      navigate(`/contents/${encodeURIComponent(result.result_content_id)}`)
    } catch (error) { setFailure(errorMessage(error)) }
    finally { setPending(false) }
  }

  return <main className="content upload-page">
    {failure && <p role="alert">{failure}</p>}
    <header className="upload-heading">
      <h1>새로 줍기</h1>
      <p>마음에 드는 콘텐츠, 링크 또는 텍스트를 저장하세요. 공개 URL도 접근 차단·JS 렌더링 등으로 수집에 실패할 수 있어요.</p>
    </header>
    <div className="upload-layout">
      <section className="upload-primary" aria-label="콘텐츠 추가">
        <div className="upload-tabs" role="tablist" aria-label="저장 방식">
          <button ref={urlTabRef} type="button" role="tab" id="upload-tab-url" aria-controls="upload-tabpanel" aria-selected={mode === 'url'} tabIndex={mode === 'url' ? 0 : -1} className={mode === 'url' ? 'is-active' : ''} onKeyDown={(event) => moveTab(event, 'text')} onClick={() => chooseMode('url')}>URL 저장</button>
          <button ref={textTabRef} type="button" role="tab" id="upload-tab-text" aria-controls="upload-tabpanel" aria-selected={mode === 'text'} tabIndex={mode === 'text' ? 0 : -1} className={mode === 'text' ? 'is-active' : ''} onKeyDown={(event) => moveTab(event, 'url')} onClick={() => chooseMode('text')}>텍스트 저장</button>
        </div>

        {mode === 'url' && <div className="upload-platforms" aria-label="지원하는 콘텐츠 유형">
          <div className="upload-platforms-heading">공개 페이지의 텍스트만 수집해요</div>
          <div className="upload-platforms-list">
            <span className="upload-platform-chip"><PlatformLogo platform="instagram" size={21} />Instagram</span>
            <span className="upload-platform-chip"><PlatformLogo platform="youtube" size={21} />YouTube</span>
            <span className="upload-platform-chip"><PlatformLogo platform="naver" size={21} />뉴스</span>
            <span className="upload-platform-chip"><PlatformLogo platform="arxiv" size={21} />논문</span>
            <span className="upload-platform-chip"><PlatformLogo platform="web" size={21} />웹페이지</span>
          </div>
        </div>}

        <form className="upload-form" id="upload-tabpanel" role="tabpanel" aria-labelledby={mode === 'url' ? 'upload-tab-url' : 'upload-tab-text'} noValidate onSubmit={submit}>
          {mode === 'url' ? <>
            <label className="upload-label" htmlFor="upload-url">저장할 링크</label>
            <div className={`upload-input-wrap${invalidUrl ? ' has-error' : ''}`}>
              <Icon name="link" />
              <input ref={inputRef} id="upload-url" type="url" inputMode="url" autoComplete="url" spellCheck={false} value={urlValue} onChange={(event) => { setUrlValue(event.target.value); if (touched) setTouched(false) }} onBlur={() => setTouched(true)} placeholder="https://" aria-invalid={invalidUrl} aria-describedby={invalidUrl ? 'upload-url-error' : undefined} />
              {urlValue && <button type="button" className="upload-clear" aria-label="링크 지우기" onClick={() => { setUrlValue(''); setTouched(false); inputRef.current?.focus() }}><Icon name="x" small /></button>}
            </div>
            {invalidUrl && <p className="upload-validation" id="upload-url-error" role="alert">올바른 http:// 또는 https:// 링크를 입력해 주세요.</p>}
            {source && <div className="upload-detected" aria-live="polite">
              <span className="upload-detected-symbol"><PlatformLogo platform={source.platform} size={26} /></span>
              <span><strong>{source.label}</strong><small>{url?.hostname}</small></span>
              <Icon name="check" small />
            </div>}
          </> : <>
            <label className="upload-label" htmlFor="upload-text">저장할 텍스트</label>
            <textarea ref={textRef} id="upload-text" maxLength={15000} value={textValue} onChange={(event) => setTextValue(event.target.value)} placeholder="기억해두고 싶은 문장이나 메모를 붙여넣으세요." rows={8} />
          </>}
          <div className="upload-actions">
            <span className="upload-supported">{mode === 'url' ? '접수 후 원본 수집과 분석 상태를 확인해 주세요.' : '글이나 메모를 바로 보관할 수 있어요.'}</span>
            <button type="submit" className="upload-submit" disabled={!canSubmit || pending}>주워두기 <Icon name="arrow" small /></button>
          </div>
        </form>
      </section>

      <aside className="upload-side" aria-label="최근 저장한 콘텐츠">
        <div className="upload-guide">
          <div className="upload-guide-title">발견한 곳은 달라도,<br />보관함은 하나.</div>
          <div className="upload-card-scene" role="img" aria-label="영상과 게시물 카드 위에 오렌지색 저장 카드가 겹쳐 떠 있는 그래픽">
            <div className="upload-card-shadow" />
            <div className="floating-content content-sheet-back" aria-hidden="true"><PlatformLogo platform="instagram" size={23} /><span className="sheet-picture" /><span className="sheet-rule" /><span className="sheet-rule short" /></div>
            <div className="floating-content content-sheet-middle" aria-hidden="true"><PlatformLogo platform="youtube" size={25} /><span className="sheet-picture video-picture"><Icon name="video" /></span><span className="sheet-rule" /><span className="sheet-rule short" /></div>
            <div className="floating-content content-sheet-cover" aria-hidden="true"><span className="cover-bookmark"><Icon name="note" /></span><span className="cover-caption">나중에 꺼내볼<br /><strong>좋은 발견들.</strong></span><span className="cover-brand">줍줍 저장소</span></div>
          </div>
        </div>
        <div className="upload-side-head"><h2>방금 주운 콘텐츠</h2><span>최근 저장</span></div>
        {recent.length ? <div className="upload-recent-list">
          {recent.map((item) => <button className="upload-recent-item" type="button" key={item.id} onClick={() => navigate(`/contents/${item.id}`)}>
            <span className="upload-recent-icon"><PlatformLogo platform={platformFromSource(item.contentType, item.source)} size={25} /></span>
            <span className="upload-recent-body"><strong>{item.title}</strong><small>{item.source}</small></span>
            <span className={`upload-state state-${item.analysisStatus}`}>{item.analysisStatus === 'analyzing' && <i aria-hidden="true" />}{serverStatusLabel(item.serverStatus)}</span>
          </button>)}
        </div> : <p className="upload-recent-empty">첫 번째 콘텐츠를 저장해 보세요.</p>}
        {recent.length > 0 && <p className="upload-side-foot">항목을 선택하면 분석 결과를 확인할 수 있어요.</p>}
      </aside>
    </div>
  </main>
}
