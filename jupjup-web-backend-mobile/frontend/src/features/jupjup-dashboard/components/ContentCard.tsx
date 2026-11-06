import { art } from '../assets/art';
import { typeIcon, namedType, formatDate, type ContentItem } from '../data/demo';
import { Icon } from './Icon';

type Props = {item: ContentItem;index: number;onDetail: (id:ContentItem['id'])=>void;onFavorite:(id:ContentItem['id'])=>void;onEdit:(id:ContentItem['id'])=>void};

export function ContentArt({kind}: {kind:string}) {
  // Local, pre-authored SVG illustrations; no external/user-supplied markup is interpolated.
  return <div className="svg-art" dangerouslySetInnerHTML={{__html:art(kind)}} />;
}
export function ContentCard({item,index,onDetail,onFavorite,onEdit}: Props) {
  return <article className="content-card" style={{animationDelay:`${Math.min(index,7)*35}ms`}}>
    <div className="card-art" role="button" tabIndex={0} aria-label={`${item.title} 상세 보기`} onClick={()=>onDetail(item.id)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onDetail(item.id)}}}>
      <ContentArt kind={item.art} /><span className="type-pill"><Icon name={typeIcon[item.type]}/>{namedType[item.type]}</span>
    </div>
    <button type="button" className={`favorite${item.favorite?' active':''}`} onClick={()=>onFavorite(item.id)} aria-label={item.favorite?'즐겨찾기 해제':'즐겨찾기 추가'} aria-pressed={item.favorite}><Icon name="star"/></button>
    <div className="card-body">
      <div className="card-source"><span className={`platform-mark ${item.platform.toLowerCase()}`}/>{item.platform}<span style={{color:'#D3CBC1'}}>·</span>{formatDate(item.date)}</div>
      <h3 className="card-title" onClick={()=>onDetail(item.id)}>{item.title}</h3>
      <div className="card-bottom"><div className="tags">{item.tags.slice(0,2).map(tag=><span key={tag} className="tag">#{tag}</span>)}</div><button type="button" className="card-more" onClick={()=>onEdit(item.id)} aria-label={`${item.title} 관리`}><Icon name="more"/></button></div>
    </div>
  </article>;
}
