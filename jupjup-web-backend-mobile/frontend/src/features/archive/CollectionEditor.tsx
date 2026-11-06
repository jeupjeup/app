import { useRef, useState, type FormEvent } from 'react'
import './collection-editor.css'
import { AccessibleDialog } from './AccessibleDialog'
import { Icon } from '@/features/jupjup-dashboard/components/Icon'
import { createCollection, deleteCollection, updateCollection, type Collection } from '@/shared/api/collections'
import { errorMessage } from '@/shared/api/client'
import { useRefreshArchive } from './queries'

const collectionColors = [
  { color: '#DDB8E5', name: '라벤더' },
  { color: '#B3D5F1', name: '하늘색' },
  { color: '#E6CA9C', name: '모래색' },
  { color: '#B9D3BD', name: '세이지' },
]
const defaultColor = collectionColors[0].color

export function CollectionEditor({ collection, onClose, onSaved, onDeleted }: { collection?: Collection; onClose: () => void; onSaved: (id: string) => void; onDeleted?: () => void }) {
  const [name, setName] = useState(collection?.name || '')
  const [color, setColor] = useState(collection?.color || defaultColor)
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [failure, setFailure] = useState('')
  const refresh = useRefreshArchive()
  const perform = async (action: () => Promise<void>) => {
    if (lock.current) return
    lock.current = true; setBusy(true); setFailure('')
    try { await action() } catch (error) { setFailure(errorMessage(error)) }
    finally { lock.current = false; setBusy(false) }
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    void perform(async () => { const result = collection ? await updateCollection(collection.id, name, color) : await createCollection(name, color); await refresh(); onSaved(result.id) })
  }
  const remove = () => {
    if (!collection || !window.confirm(`‘${collection.name}’ 컬렉션을 삭제할까요? 소속만 해제되며 콘텐츠와 원문, 분석 결과는 보관함에 남아요.`)) return
    void perform(async () => { await deleteCollection(collection.id); await refresh(); onDeleted?.() })
  }
  return <AccessibleDialog titleId="collectionEditorTitle" onClose={() => { if (!lock.current) onClose() }}><div className="dialog-header"><h2 id="collectionEditorTitle">{collection ? '컬렉션 관리' : '새 컬렉션 만들기'}</h2><button type="button" className="dialog-close" disabled={busy} aria-label="닫기" onClick={onClose}><Icon name="x" /></button></div><form className="form-fields collection-editor-form" onSubmit={submit}><div className="form-field"><label htmlFor="collectionName">컬렉션 이름</label><input id="collectionName" value={name} onChange={event => setName(event.target.value)} required maxLength={80} disabled={busy} aria-describedby="collectionNameHelp" placeholder="예: 다음 여행 준비" /><small id="collectionNameHelp" className="collection-name-help">1~80자 · 대소문자만 다른 같은 이름은 사용할 수 없어요.</small></div><fieldset className="form-field collection-color-picker" disabled={busy}><legend>컬렉션 색상</legend><div className="collection-color-options">{collectionColors.map(option => <label key={option.color} className="collection-color-option"><input type="radio" name="collectionColor" value={option.color} aria-label={option.name} checked={color === option.color} onChange={() => setColor(option.color)} /><span aria-hidden="true" style={{ backgroundColor: option.color }} /><span>{option.name}</span></label>)}</div><div className="collection-custom-color"><label className="collection-color-option custom-color-option"><input type="radio" name="collectionColor" value="custom" aria-label="사용자 지정 색상" checked={!collectionColors.some(option => option.color === color)} onChange={() => { if (collectionColors.some(option => option.color === color)) setColor('#8A8178') }} /><span>사용자 지정</span></label><input type="color" aria-label="사용자 지정 색상 값" value={color} onChange={event => setColor(event.target.value.toUpperCase())} /></div><small className="collection-color-preview" aria-live="polite"><span aria-hidden="true" style={{ backgroundColor: color }} />선택한 색상 {color}</small></fieldset>{failure && <p role="alert">{failure}</p>}<div className="dialog-footer">{collection && <button type="button" className="button danger-button" disabled={busy} onClick={remove}>컬렉션 삭제</button>}<button type="button" className="button" disabled={busy} onClick={onClose}>취소</button><button className="button primary" disabled={busy || !name.trim()}>{busy ? '저장 중…' : collection ? '이름·색상 저장' : '만들기'}</button></div></form></AccessibleDialog>
}
