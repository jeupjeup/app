import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ContentCard } from './components/ContentCard';
import { Icon } from './components/Icon';
import { Modal, type DialogState, type EditItemInput, type NewItemInput } from './components/Modal';
import { SearchFeature } from './components/SearchFeature';
import { DashboardShell } from './components/DashboardShell';
import { usePersistentState } from './hooks/usePersistentState';
import { seedItems, seedCollections, namedType, type Collection, type ContentItem, type ContentType, type Display, type Sort, type View } from './data/demo';

const filters: Array<{value:ContentType|'all';label:string}> = [
  {value:'all',label:'전체'}, {value:'video',label:'영상'}, {value:'post',label:'게시물'}, {value:'web',label:'웹페이지'}, {value:'note',label:'메모'}
];
const collectionColors: Record<string,[string,string,string]> = {
  peach:['#EFB477','#FFF1DF','#AD7440'],purple:['#DDB8E5','#F6EAF9','#9562A1'],blue:['#B3D5F1','#EAF3FC','#608EB5'],green:['#B9D3BD','#E9F4EA','#6F9E78']
};

function FolderBadge({collection}: {collection:Collection}) {
  return <span className="folder-icon" style={{background:collection.bg,color:collection.ink}}><Icon name="folder"/></span>;
}

function CollectionRail({collections,items,onNavigate,onAddCollection,onAddItem}: {collections:Collection[];items:ContentItem[];onNavigate:(view:View,id?:string)=>void;onAddCollection:()=>void;onAddItem:()=>void}) {
  return <aside className="right-rail">
    <section className="rail-block"><div className="rail-title"><h3>나의 컬렉션</h3><button type="button" className="rail-add" aria-label="컬렉션 만들기" onClick={onAddCollection}><Icon name="plus" small /></button></div>
      <div className="collection-list">{collections.map(c=><button type="button" className="collection-tile" key={c.id} onClick={()=>onNavigate('collection',c.id)}><FolderBadge collection={c}/><span className="col-info"><span className="col-title">{c.name}</span><span className="col-count">콘텐츠 {items.filter(x=>x.collection===c.id).length}개</span></span><Icon name="chevron"/></button>)}</div>
    </section>
    <section className="rail-helper"><div className="small-icon"><Icon name="link"/></div><h3>마음에 드는 링크,<br/>여기에 모아두세요.</h3><p>영상이나 게시물, 웹페이지 주소를 입력해 콘텐츠를 저장할 수 있어요.</p><button type="button" onClick={onAddItem}>링크 저장하기 <Icon name="arrow" small /></button><div className="decoration"/></section>
    <div className="rail-caption">줍줍 저장소 · 개인 보관함 UI 데모</div>
  </aside>;
}

function CollectionsOverview({collections,items,onNavigate,onAdd}: {collections:Collection[];items:ContentItem[];onNavigate:(view:View,id?:string)=>void;onAdd:()=>void}) {
  return <div className="collections-overview">
    {collections.map(c=><button type="button" key={c.id} className="overview-card" onClick={()=>onNavigate('collection',c.id)}><FolderBadge collection={c}/><h3>{c.name}</h3><p>{items.filter(x=>x.collection===c.id).length}개의 저장된 콘텐츠</p></button>)}
    <button type="button" className="overview-card" onClick={onAdd} style={{borderStyle:'dashed',display:'flex',flexDirection:'column',alignItems:'flex-start',justifyContent:'center',color:'#97745B'}}><span className="folder-icon" style={{background:'#FFF1DE',color:'#BD7D41'}}><Icon name="plus"/></span><h3>새 컬렉션 만들기</h3><p>콘텐츠를 나만의 방식으로 묶어보세요</p></button>
  </div>;
}

function getPageHeading(view: View, collectionName?: string) {
  return {home:'내 저장소',all:'모든 콘텐츠',recent:'최근 저장',favorites:'즐겨찾기',collections:'나의 컬렉션',collection:collectionName||'컬렉션'}[view];
}
function getPageSubtitle(view: View) {
  return view==='home'?'발견했던 것들을 모아보고, 필요할 때 다시 찾아보세요.':view==='favorites'?'언제든 다시 꺼내 보고 싶은 콘텐츠들이에요.':view==='collections'?'저장한 콘텐츠를 주제별로 모아보세요.':view==='collection'?'이 컬렉션에 저장한 콘텐츠를 모아봤어요.':'내가 발견하고 저장한 콘텐츠를 관리해 보세요.';
}

type DashboardAppProps = {
  onOpenSettings?: () => void;
};

export default function DashboardApp({onOpenSettings}: DashboardAppProps) {
  const [items,setItems]=usePersistentState<ContentItem[]>('jupjup_dashboard_items_v2',seedItems);
  const [collections,setCollections]=usePersistentState<Collection[]>('jupjup_dashboard_collections_v2',seedCollections);
  const [view,setView]=useState<View>('home');
  const [activeCollection,setActiveCollection]=useState<string|null>(null);
  const [activeType,setActiveType]=useState<ContentType|'all'>('all');
  const [display,setDisplay]=useState<Display>('grid');
  const [sort,setSort]=useState<Sort>('new');
  const [searchText,setSearchText]=useState('');
  const [dialog,setDialog]=useState<DialogState|null>(null);
  const [sidebarOpen,setSidebarOpen]=useState(false);
  const [notice,setNotice]=useState('');
  const searchRef=useRef<HTMLInputElement>(null);
  const toastTimer=useRef<number|null>(null);

  const onClose=useCallback(()=>setDialog(null),[]);
  const showToast=useCallback((message:string)=>{
    setNotice(message);
    if(toastTimer.current!==null)window.clearTimeout(toastTimer.current);
    toastTimer.current=window.setTimeout(()=>setNotice(''),2600);
  },[]);
  useEffect(()=>()=>{if(toastTimer.current!==null)window.clearTimeout(toastTimer.current)},[]);

  const navigate=useCallback((next:View,colId?:string)=>{
    setView(next);
    setActiveCollection(colId||null);
    setActiveType('all');
    setSearchText('');
    setSidebarOpen(false);
    if(next==='recent')setSort('new');
    window.scrollTo({top:0,behavior:'smooth'});
  },[]);

  const searchFocus=useCallback(()=>{
    if(view==='collections')navigate('all');
    requestAnimationFrame(()=>{searchRef.current?.focus();searchRef.current?.scrollIntoView({behavior:'smooth',block:'center'});});
  },[navigate,view]);

  useEffect(()=>{
    const onKey=(e:KeyboardEvent)=>{
      if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){
        e.preventDefault();if(!dialog)searchFocus();
      }
      if(e.key==='Escape')setSidebarOpen(false);
    };
    window.addEventListener('keydown',onKey);
    return ()=>window.removeEventListener('keydown',onKey);
  },[dialog,searchFocus]);

  const activeCol=collections.find(c=>c.id===activeCollection);
  const heading=getPageHeading(view,activeCol?.name);
  const filtered=useMemo(()=>{
    let data=[...items];
    if(view==='favorites')data=data.filter(x=>x.favorite);
    if(view==='collection')data=data.filter(x=>x.collection===activeCollection);
    if(activeType!=='all')data=data.filter(x=>x.type===activeType);
    if(searchText.trim()){
      const terms=searchText.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
      data=data.filter(x=>{
        const collection=collections.find(c=>c.id===x.collection);
        const hay=[x.title,x.platform,x.description,...x.tags,collection?.name||'',namedType[x.type]].join(' ').toLocaleLowerCase();
        const extra=(hay.includes('피그마')?' figma auto layout 오토 레이아웃 강의 동영상':'')+(hay.includes('리액트')?' react':'');
        return terms.every(term=>(hay+extra).includes(term));
      });
    }
    data.sort((a,b)=>sort==='title'?a.title.localeCompare(b.title,'ko'):sort==='old'?a.date.localeCompare(b.date)||String(a.id).localeCompare(String(b.id)):b.date.localeCompare(a.date)||String(b.id).localeCompare(String(a.id)));
    if(view==='home'&&!searchText.trim()&&activeType==='all')data=data.slice(0,9);
    return data;
  },[items,collections,view,activeCollection,activeType,searchText,sort]);

  const onFavorite=(id:ContentItem['id'])=>{
    const found=items.find(x=>String(x.id)===String(id));if(!found)return;
    setItems(prev=>prev.map(x=>String(x.id)===String(id)?{...x,favorite:!x.favorite}:x));
    showToast(found.favorite?'즐겨찾기에서 제외했어요.':'즐겨찾기에 추가했어요.');
  };

  const onAddItem=(value:NewItemInput)=>{
    let url:URL;
    try {url=new URL(value.url.trim());if(!['http:','https:'].includes(url.protocol))throw new Error('Invalid protocol');}
    catch {showToast('올바른 웹 주소를 입력해 주세요.');return;}
    const host=url.hostname.replace(/^www\./,'');
    const type:ContentType=/youtube\.com|youtu\.be/.test(host)?'video':/instagram\.com/.test(host)?'post':'web';
    const platform=type==='video'?'YouTube':type==='post'?'Instagram':'Web';
    const now=new Date();
    const tags=value.tags.split(',').map(t=>t.trim().replace(/^#/,'')).filter(Boolean).slice(0,4);
    const newItem:ContentItem={id:Date.now(),title:value.title.trim()||host,platform,type,collection:value.collection,date:[now.getFullYear(),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-'),tags,art:type==='video'?'motion':type==='post'?'editorial':'note',favorite:false,description:'직접 저장한 링크입니다. 내용을 분석하거나 썸네일을 가져오려면 API 연동이 필요해요.',url:url.href};
    setItems(prev=>[newItem,...prev]);onClose();navigate('all');showToast('콘텐츠를 저장했어요.');
  };
  const onAddCollection=(name:string,colorKey:string)=>{
    if(!name.trim())return;
    const [color,bg,ink]=collectionColors[colorKey]||collectionColors.peach;
    const next={id:`collection-${Date.now()}`,name:name.trim(),color,bg,ink};
    setCollections(prev=>[...prev,next]);onClose();navigate('collection',next.id);showToast('새 컬렉션을 만들었어요.');
  };
  const onEditItem=(id:ContentItem['id'],data:EditItemInput)=>{
    if(!data.title.trim())return;
    setItems(prev=>prev.map(x=>String(x.id)!==String(id)?x:{...x,title:data.title.trim(),collection:data.collection,tags:data.tags.split(',').map(s=>s.trim().replace(/^#/,'')).filter(Boolean).slice(0,5),description:data.description.trim()}));
    onClose();showToast('변경 내용을 저장했어요.');
  };
  const onDeleteItem=(id:ContentItem['id'])=>{
    if(!window.confirm('이 콘텐츠를 보관함에서 삭제할까요?'))return;
    setItems(prev=>prev.filter(x=>String(x.id)!==String(id)));onClose();showToast('콘텐츠를 삭제했어요.');
  };
  const onReset=()=>{
    if(!window.confirm('추가한 콘텐츠와 컬렉션을 포함해 시안 데이터를 처음 상태로 되돌릴까요?'))return;
    setItems(seedItems.map(x=>({...x,tags:[...x.tags]})));
    setCollections(seedCollections.map(c=>({...c})));onClose();navigate('home');showToast('처음 상태로 돌아왔어요.');
  };
  const onCopy=async(url:string)=>{
    try {await navigator.clipboard.writeText(url);showToast('링크를 복사했어요.');}
    catch {showToast('링크 복사 권한을 확인해 주세요.');}
  };
  const onSearchChange=(s:string)=>{if(view==='collections')setView('all');setSearchText(s)};
  const resetFilters=()=>{setSearchText('');setActiveType('all')};
  const openSettings=()=>onOpenSettings ? onOpenSettings() : setDialog({kind:'settings'});

  return <>
    <DashboardShell
      collections={collections}
      itemCount={items.length}
      view={view}
      activeCollection={activeCollection}
      sidebarOpen={sidebarOpen}
      breadcrumb={heading}
      topActions={<><button type="button" aria-label="콘텐츠 검색" className="top-search" onClick={searchFocus}><Icon name="search" small/><span>콘텐츠 검색</span><kbd>⌘ K</kbd></button><button type="button" aria-label="계정 및 설정" className="top-profile" onClick={openSettings}>내</button></>}
      onSidebarToggle={()=>setSidebarOpen(x=>!x)}
      onSidebarClose={()=>setSidebarOpen(false)}
      onNavigate={navigate}
      onAddCollection={()=>setDialog({kind:'collection'})}
      onSettings={openSettings}
    >
        <main className="content">
          <section className="intro"><div><h1>{heading}</h1><p>{getPageSubtitle(view)}</p></div><div className="intro-actions"><button type="button" className="button primary" aria-label="콘텐츠 추가" onClick={()=>setDialog({kind:'add'})}><Icon name="plus" small/><span>콘텐츠 추가</span></button></div></section>
          {view!=='collections'&&<SearchFeature value={searchText} onChange={onSearchChange} inputRef={searchRef}/>}
          <div className="dashboard-layout">
            <section className="items-section" aria-labelledby="itemsHeading">
              <div className="section-heading"><div><h2 id="itemsHeading">{view==='home'?'최근 저장한 콘텐츠':view==='collections'?'컬렉션 모아보기':view==='favorites'?'즐겨찾기한 콘텐츠':view==='collection'?`${activeCol?.name||'컬렉션'}의 콘텐츠`:'저장한 콘텐츠'}</h2><p>{view==='collections'?'클릭해서 해당 컬렉션의 콘텐츠를 확인하세요.':view==='home'?'최근에 저장한 것부터 보여드릴게요.':'원하는 콘텐츠를 골라 확인하거나 정리하세요.'}</p></div>{view==='home'&&<button type="button" className="inline-link" onClick={()=>navigate('all')}>모두 보기 <Icon name="arrow" small/></button>}</div>
              {view==='collections' ? <CollectionsOverview collections={collections} items={items} onNavigate={navigate} onAdd={()=>setDialog({kind:'collection'})} /> : <>
                <div className="content-toolbar"><div className="filters" role="group" aria-label="콘텐츠 유형">
                  {filters.map(f=><button key={f.value} type="button" className={`filter-button${activeType===f.value?' selected':''}`} onClick={()=>setActiveType(f.value)} aria-pressed={activeType===f.value}>{f.label}</button>)}
                </div><div className="content-tools"><label className="sr-only" htmlFor="sortBy">정렬</label><select id="sortBy" className="sort-select" value={sort} onChange={e=>setSort(e.target.value as Sort)}><option value="new">최신순</option><option value="old">오래된순</option><option value="title">이름순</option></select>
                  <div className="view-toggle" role="group" aria-label="보기 형식"><button type="button" aria-label="격자 보기" title="격자 보기" className={display==='grid'?'active':''} onClick={()=>setDisplay('grid')}><Icon name="grid"/></button><button type="button" aria-label="목록 보기" title="목록 보기" className={display==='list'?'active':''} onClick={()=>setDisplay('list')}><Icon name="list"/></button></div>
                </div></div>
                {searchText.trim()&&<div className="result-note"><strong>{filtered.length}개</strong>의 콘텐츠를 찾았어요.</div>}
                <div className={`content-grid${display==='list'?' is-list':''}`}>
                  {filtered.length ? filtered.map((item,i)=><ContentCard key={item.id} item={item} index={i} onFavorite={onFavorite} onEdit={id=>setDialog({kind:'edit',id})} onDetail={id=>setDialog({kind:'detail',id})}/>) :
                    <div className="empty-state" style={{gridColumn:'1/-1'}}><div className="empty-symbol"><Icon name="search" large/></div><h3>{searchText?'검색 결과가 없어요.':'아직 저장된 콘텐츠가 없어요.'}</h3><p>{searchText?'다른 단어로 검색하거나 필터를 변경해 보세요.':'콘텐츠를 추가해 나만의 저장소를 채워보세요.'}</p><button type="button" className={`button${searchText?'':' primary'}`} onClick={()=>searchText?resetFilters():setDialog({kind:'add'})}>{searchText?'필터 초기화':'콘텐츠 추가하기'}</button></div>}
                </div>
              </>}
            </section>
            <CollectionRail collections={collections} items={items} onNavigate={navigate} onAddCollection={()=>setDialog({kind:'collection'})} onAddItem={()=>setDialog({kind:'add'})}/>
          </div>
        </main>
    </DashboardShell>
    <Modal dialog={dialog} onClose={onClose} collections={collections} items={items} onAddItem={onAddItem} onAddCollection={onAddCollection} onEditItem={onEditItem} onDeleteItem={onDeleteItem} onFavorite={onFavorite} onReset={onReset} onEditOpen={id=>setDialog({kind:'edit',id})} onCopy={onCopy}/>
    <div className={`toast${notice?' show':''}`} aria-live="polite" role="status">{notice}</div>
  </>;
}
