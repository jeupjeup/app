import { useEffect, useRef, type FormEvent, type ReactNode } from 'react';
import { ContentArt } from './ContentCard';
import { Icon } from './Icon';
import { formatDate, namedType, type Collection, type ContentItem } from '../data/demo';

export type DialogState = {kind:'add'|'collection'|'settings'} | {kind:'edit'|'detail';id:ContentItem['id']};
export type NewItemInput = {url:string;title:string;collection:string;tags:string};
export type EditItemInput = {title:string;collection:string;tags:string;description:string};

export type ModalProps = {
  dialog: DialogState | null;
  onClose:()=>void;
  collections: Collection[];
  items: ContentItem[];
  onAddItem:(value:NewItemInput)=>void;
  onAddCollection:(name:string,color:string)=>void;
  onEditItem:(id:ContentItem['id'],value:EditItemInput)=>void;
  onDeleteItem:(id:ContentItem['id'])=>void;
  onFavorite:(id:ContentItem['id'])=>void;
  onReset:()=>void;
  onEditOpen:(id:ContentItem['id'])=>void;
  onCopy:(url:string)=>void;
};

const colorNames = [
  ['peach','따뜻한 오렌지'],['purple','라벤더'],['blue','하늘색'],['green','세이지 그린']
];

function Footer({children}: {children:ReactNode}) {return <div className="dialog-footer">{children}</div>}
function CollectionOptions({collections}: {collections:Collection[]}) {return <><option value="">컬렉션 없음</option>{collections.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</>}

export function Modal(props: ModalProps) {
  const {dialog,onClose,collections,items,onAddItem,onAddCollection,onEditItem,onDeleteItem,onFavorite,onReset,onEditOpen,onCopy}=props;
  const dialogRef=useRef<HTMLDivElement>(null);
  const item=dialog && 'id' in dialog ? items.find(x=>String(x.id)===String(dialog.id)) : undefined;
  const collection=collections.find(c=>c.id===item?.collection);
  useEffect(()=>{
    if(!dialog)return;
    const old=document.body.style.overflow;
    document.body.style.overflow='hidden';
    const id=window.setTimeout(()=>dialogRef.current?.querySelector<HTMLElement>('input, select, textarea, button')?.focus(),30);
    const handleKey=(event:KeyboardEvent)=>{if(event.key==='Escape')onClose()};
    window.addEventListener('keydown',handleKey);
    return ()=>{document.body.style.overflow=old;window.clearTimeout(id);window.removeEventListener('keydown',handleKey)};
  },[dialog,onClose]);
  if(!dialog)return null;

  const titles={add:'새 콘텐츠 저장하기',collection:'새 컬렉션 만들기',edit:'콘텐츠 관리',detail:'콘텐츠 상세 보기',settings:'설정'};
  const handleAdd=(event:FormEvent<HTMLFormElement>)=>{event.preventDefault();const d=new FormData(event.currentTarget);onAddItem({url:String(d.get('url')||''),title:String(d.get('title')||''),collection:String(d.get('collection')||''),tags:String(d.get('tags')||'')})};
  const handleCollection=(event:FormEvent<HTMLFormElement>)=>{event.preventDefault();const d=new FormData(event.currentTarget);onAddCollection(String(d.get('name')||''),String(d.get('color')||'peach'))};
  const handleEdit=(event:FormEvent<HTMLFormElement>)=>{event.preventDefault();if(!item)return;const d=new FormData(event.currentTarget);onEditItem(item.id,{title:String(d.get('title')||''),collection:String(d.get('collection')||''),tags:String(d.get('tags')||''),description:String(d.get('description')||'')})};

  return <div className="dialog-backdrop open" role="presentation" onMouseDown={event=>{if(event.target===event.currentTarget)onClose()}}>
    <div className={`dialog${dialog.kind==='detail'?' wide':''}`} role="dialog" aria-modal="true" aria-labelledby="modalTitle" ref={dialogRef}>
      <div className="dialog-header"><h2 id="modalTitle">{titles[dialog.kind]}</h2><button type="button" className="dialog-close" aria-label="닫기" onClick={onClose}><Icon name="x"/></button></div>
      {dialog.kind==='add' && <form className="form-fields" onSubmit={handleAdd}>
        <div className="form-field"><label htmlFor="addURL">콘텐츠 URL</label><input name="url" id="addURL" type="url" placeholder="https://..." required/><span className="help">유튜브, 인스타그램, 웹페이지 링크 등을 추가할 수 있어요.</span></div>
        <div className="form-field"><label htmlFor="addTitle">제목</label><input name="title" id="addTitle" maxLength={100} placeholder="예: 나중에 다시 보고 싶은 디자인 레퍼런스"/><span className="help">제목을 비워두면 사이트 주소를 임시 제목으로 사용해요.</span></div>
        <div className="form-row"><div className="form-field"><label htmlFor="addCollection">컬렉션</label><select id="addCollection" name="collection"><CollectionOptions collections={collections}/></select></div><div className="form-field"><label htmlFor="addTags">태그</label><input id="addTags" name="tags" placeholder="디자인, 참고자료" maxLength={70}/></div></div>
        <div className="notice">이 화면은 프론트엔드 데모예요. 직접 입력한 내용은 브라우저에 저장되지만, 실제 AI 분석과 썸네일 수집은 서버 연결 후 사용할 수 있어요.</div>
        <Footer><button type="button" className="button" onClick={onClose}>취소</button><button type="submit" className="button primary">저장하기</button></Footer>
      </form>}
      {dialog.kind==='collection' && <form className="form-fields" onSubmit={handleCollection}>
        <div className="form-field"><label htmlFor="colName">컬렉션 이름</label><input name="name" id="colName" maxLength={24} required placeholder="예: 나중에 볼 영상"/></div>
        <div className="form-field"><label htmlFor="colColor">컬렉션 컬러</label><select id="colColor" name="color">{colorNames.map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></div>
        <Footer><button type="button" className="button" onClick={onClose}>취소</button><button type="submit" className="button primary">만들기</button></Footer>
      </form>}
      {dialog.kind==='edit' && item && <form key={item.id} className="form-fields" onSubmit={handleEdit}>
        <div className="form-field"><label htmlFor="editTitle">제목</label><input id="editTitle" name="title" maxLength={100} defaultValue={item.title} required/></div>
        <div className="form-row"><div className="form-field"><label htmlFor="editCollection">컬렉션</label><select id="editCollection" name="collection" defaultValue={item.collection}><CollectionOptions collections={collections}/></select></div><div className="form-field"><label htmlFor="editTags">태그 · 쉼표로 구분</label><input id="editTags" name="tags" maxLength={100} defaultValue={item.tags.join(', ')}/></div></div>
        <div className="form-field"><label htmlFor="editDescription">설명 / 메모</label><textarea id="editDescription" name="description" maxLength={500} defaultValue={item.description}/></div>
        <div className="dialog-footer" style={{justifyContent:'space-between'}}><button type="button" className="button" style={{color:'#B05B48'}} onClick={()=>onDeleteItem(item.id)}><Icon name="trash" small/> 삭제</button><span style={{display:'flex',gap:8}}><button type="button" className="button" onClick={onClose}>취소</button><button type="submit" className="button primary">변경 저장</button></span></div>
      </form>}
      {dialog.kind==='detail' && item && <>
        <div className="detail-art"><ContentArt kind={item.art}/></div>
        <div className="detail-category">{item.platform} · {namedType[item.type]} · {formatDate(item.date)}</div>
        <h3 className="detail-title">{item.title}</h3><p className="detail-desc">{item.description||'설명 없음'}</p>
        <div className="detail-meta">{collection&&<span><Icon name="folder" small/> {collection.name}</span>}{item.tags.map(t=><span key={t}>#{t}</span>)}</div>
        <div className="detail-buttons"><button type="button" className="button" onClick={()=>onFavorite(item.id)}><Icon name="star" small/>{item.favorite?'즐겨찾기 해제':'즐겨찾기'}</button><button type="button" className="button" onClick={()=>onEditOpen(item.id)}><Icon name="edit" small/>수정</button>
          {item.url ? <><a className="button primary" href={item.url} target="_blank" rel="noopener noreferrer">원본 열기 <Icon name="external" small/></a><button type="button" className="button" onClick={()=>onCopy(item.url)}><Icon name="copy" small/> 링크 복사</button></> : <span style={{alignSelf:'center',color:'#A3978C',fontSize:11}}>샘플 콘텐츠 · 원본 링크 미연결</span>}
        </div>
      </>}
      {dialog.kind==='settings' && <div className="form-fields">
        <div className="notice">줍줍 저장소 웹 대시보드 React 데모입니다. 예시 콘텐츠와 직접 추가한 항목은 현재 브라우저의 로컬 저장소에 보관돼요.</div>
        <div><p style={{color:'#5D5148',fontSize:13,margin:'0 0 8px'}}>저장된 샘플 및 사용자 데이터</p><p style={{color:'#9C9288',fontSize:12,lineHeight:1.7,margin:0}}>이 브라우저에 콘텐츠 {items.length}개, 컬렉션 {collections.length}개가 있어요.</p></div>
        <div className="dialog-footer" style={{justifyContent:'space-between'}}><button type="button" className="button" onClick={onReset} style={{color:'#B05B48'}}>샘플 상태로 초기화</button><button type="button" className="button primary" onClick={onClose}>닫기</button></div>
      </div>}
    </div>
  </div>;
}
