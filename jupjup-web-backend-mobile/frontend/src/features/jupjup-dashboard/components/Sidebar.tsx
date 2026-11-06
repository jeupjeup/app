import type { Collection, View } from '../data/demo';
import { Icon } from './Icon';
import './sidebar-rail.css';

type Props = {
  collections: Collection[];
  itemCount: number;
  view: View;
  activeCollection: string | null;
  settingsActive?: boolean;
  navigationActive?: boolean;
  open: boolean;
  onNavigate: (view: View, collectionId?: string) => void;
  onAddCollection: () => void;
  onSettings: () => void;
  onClose: () => void;
};

export function BrandMark() {
  return <svg aria-hidden="true" className="brand-icon" viewBox="0 0 40 40">
    <rect fill="#FFB466" height="25" rx="9" width="25" x="5" y="10" />
    <path d="M12 7h16a5 5 0 0 1 5 5v16a5 5 0 0 1-5 5H12a5 5 0 0 1-5-5V12a5 5 0 0 1 5-5Z" fill="#FFF8EE" stroke="#8B5A2B" strokeWidth="2.8" />
    <path d="m15 20 4 4 7-8" fill="none" stroke="#8B5A2B" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.8" />
    <circle cx="30.5" cy="9.5" fill="#FF9F43" r="4.7" />
  </svg>;
}

const links: Array<{view: View; name: string; icon: string}> = [
  {view:'home', name:'홈', icon:'home'},
  {view:'all', name:'모든 콘텐츠', icon:'grid'},
  {view:'recent', name:'최근 저장', icon:'clock'},
  {view:'favorites', name:'즐겨찾기', icon:'star'},
];

export function Sidebar({view,settingsActive=false,navigationActive=true,open,onNavigate,onSettings,onClose}: Props) {
  return <>
    <div className={`sidebar-scrim${open?' open':''}`} onClick={onClose} aria-hidden="true" />
    <aside className={`sidebar sidebar-rail${open?' open':''}`} aria-label="사이드 메뉴">
      <a className="logo" href="#" aria-label="줍줍 저장소 홈" onClick={(e)=>{e.preventDefault();onNavigate('home');}}>
        <BrandMark />
      </a>
      <nav className="nav-items" aria-label="보관함 탐색">
        {links.map((link)=><button key={link.view} type="button" onClick={()=>onNavigate(link.view)} aria-current={navigationActive&&!settingsActive&&view===link.view ? 'page' : undefined} className={`nav-item${navigationActive&&!settingsActive&&view===link.view?' active':''}`}>
          <Icon name={link.icon}/><span className="nav-text">{link.view === 'all' ? '콘텐츠' : link.name}</span>
        </button>)}
        <button type="button" aria-current={navigationActive&&!settingsActive&&(view==='collections'||view==='collection') ? 'page' : undefined} className={`nav-item${navigationActive&&!settingsActive&&(view==='collections'||view==='collection')?' active':''}`} onClick={()=>onNavigate('collections')}><Icon name="folder"/><span className="nav-text">컬렉션</span></button>
        <button type="button" aria-current={settingsActive ? 'page' : undefined} className={`nav-item${settingsActive?' active':''}`} onClick={onSettings}><Icon name="settings"/><span className="nav-text">설정</span></button>
      </nav>
    </aside>
  </>;
}
