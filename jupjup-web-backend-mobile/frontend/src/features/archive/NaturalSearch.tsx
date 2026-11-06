import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { searchSuggestions } from './archiveSearch'
import { Icon } from '@/features/jupjup-dashboard/components/Icon'

export function NaturalSearch() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [suggestionsOpen, setSuggestionsOpen] = useState(true)
  const suggestions = suggestionsOpen && query.trim() ? searchSuggestions.filter((item) => item.includes(query.trim()) || query.trim().includes('오사카')).slice(0, 4) : []
  const search = (value = query) => { if (value.trim()) navigate(`/search?q=${encodeURIComponent(value.trim())}`) }
  const submit = (event: FormEvent) => { event.preventDefault(); search() }
  return <section className="natural-search" aria-labelledby="naturalSearchTitle">
      <div className="search-prompt"><span className="search-mark"><Icon name="search" /></span><div><h2 id="naturalSearchTitle">그때 저장한 거, 뭐였더라?</h2><p>제목이 생각나지 않아도 괜찮아요. 기억나는 내용으로 찾아보세요.</p></div></div>
      <form className="natural-search-form" onSubmit={submit}><Icon name="search" /><input value={query} onFocus={() => setSuggestionsOpen(true)} onChange={(event) => { setQuery(event.target.value); setSuggestionsOpen(true) }} onKeyDown={(event) => { if (event.key === 'ArrowDown' && suggestions.length) { event.preventDefault(); document.getElementById('search-suggestion-0')?.focus() } if (event.key === 'Escape') setSuggestionsOpen(false) }} placeholder="예전에 본 오사카 여행 영상..." aria-label="저장한 콘텐츠 검색" role="combobox" aria-autocomplete="list" aria-expanded={suggestions.length > 0} aria-controls="search-suggestion-list" /><button type="submit">찾기</button></form>
      {!!suggestions.length && <div id="search-suggestion-list" className="search-suggestions" role="listbox" aria-label="검색 자동완성">{suggestions.map((suggestion, index) => <button id={`search-suggestion-${index}`} key={suggestion} type="button" role="option" aria-selected="false" onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); setSuggestionsOpen(false); document.querySelector<HTMLInputElement>('.natural-search-form input')?.focus() } if (event.key === 'ArrowDown') { event.preventDefault(); document.getElementById(`search-suggestion-${Math.min(index + 1, suggestions.length - 1)}`)?.focus() } if (event.key === 'ArrowUp') { event.preventDefault(); if (index === 0) document.querySelector<HTMLInputElement>('.natural-search-form input')?.focus(); else document.getElementById(`search-suggestion-${index - 1}`)?.focus() } }} onClick={() => search(suggestion)}><Icon name="search" small /><span>{suggestion}</span><Icon name="arrow" small /></button>)}</div>}
      <div className="search-examples"><span>이런 식으로 찾아보세요</span><button type="button" onClick={() => search('오사카 지하철 타는 법 알려준 영상')}>오사카 지하철 타는 법 알려준 영상</button><button type="button" onClick={() => search('전에 저장한 공부 방법')}>전에 저장한 공부 방법</button><button type="button" onClick={() => search('책상 예쁘게 꾸민 사진')}>책상 예쁘게 꾸민 사진</button></div>
    </section>
}
