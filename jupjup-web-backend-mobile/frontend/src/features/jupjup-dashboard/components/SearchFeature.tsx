import type { RefObject } from 'react';
import { Icon } from './Icon';

type Props = {value: string; onChange: (value:string)=>void; inputRef: RefObject<HTMLInputElement|null>};

export function SearchFeature({value,onChange,inputRef}: Props) {
  return <section className="search-feature" aria-label="콘텐츠 검색">
    <div className="search-copy">
      <h2>기억나는 말로<br/>다시 찾아보세요.</h2>
      <p>제목이 생각나지 않아도 괜찮아요. 떠오르는 단어부터 입력해 보세요.</p>
      <label className="big-search" htmlFor="mainSearch">
        <Icon name="search"/><input ref={inputRef} id="mainSearch" aria-label="저장한 콘텐츠 검색" autoComplete="off" type="search" placeholder="예: 전에 봤던 피그마 오토레이아웃 영상" value={value} onChange={e=>onChange(e.target.value)} />
        <span className="search-key">⌘ K</span>
      </label>
    </div>
    <div className="search-visual" aria-hidden="true">
      <div className="paper-a"><div className="paper-photo"><svg width="90" height="81" viewBox="0 0 90 81"><rect x="15" y="11" width="60" height="59" rx="9" fill="#FFF" opacity=".7"/><rect x="26" y="23" width="14" height="14" rx="4" fill="#EBA6A0"/><rect x="45" y="23" width="14" height="14" rx="4" fill="#AD9BDC"/><rect x="26" y="43" width="33" height="5" rx="2" fill="#D4C9E4"/><rect x="26" y="54" width="24" height="5" rx="2" fill="#D4C9E4"/></svg></div><div className="paper-txt"/><div className="paper-txt short"/></div>
      <div className="paper-b"><div className="paper-photo"><svg width="99" height="86" viewBox="0 0 99 86"><circle cx="49" cy="42" r="31" fill="#E5AA7E"/><circle cx="49" cy="42" r="24" fill="#F9E9D6"/><path d="M25 40c13-19 34-22 46 0s-10 34-23 25" fill="none" stroke="#BF7B53" strokeLinecap="round" strokeWidth="6"/></svg></div><div className="paper-txt"/><div className="paper-txt short"/></div>
      <div className="paper-c"><div className="paper-photo"><svg width="100" height="76" viewBox="0 0 100 76"><path d="M0 63 25 34l13 13 23-31 39 47z" fill="#7A9B82"/><circle cx="70" cy="21" r="13" fill="#FBE5AB"/><path d="M0 70 33 48l18 13 20-16 29 25" fill="#B5C9AC"/></svg></div><div className="paper-txt"/><div className="paper-txt short"/></div>
      <div className="visual-loop"><Icon name="search" large /></div>
    </div>
  </section>;
}
