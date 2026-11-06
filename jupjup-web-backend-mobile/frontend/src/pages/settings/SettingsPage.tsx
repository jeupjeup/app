import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArchivePageHeader } from '@/features/archive/ArchivePageHeader'
import { useArchiveUi } from '@/features/archive/ArchiveLayout'
import { useArchiveStore } from '@/features/archive/ArchiveStore'
import { defaultArchiveSettings } from '@/features/archive/archiveData'
import { getSession, logout } from '@/shared/auth/session'
import type { ArchiveSort } from '@/features/archive/archiveData'
import { Icon } from '@/features/jupjup-dashboard/components/Icon'
import { restartOnboarding } from '@/features/onboarding/onboardingData'
import styles from './SettingsPage.module.css'

function Switch({ checked, onChange, label }: { checked: boolean; onChange: () => void; label: string }) {
  return <button type="button" className={`${styles.switch} ${checked ? styles.switchOn : ''}`} role="switch" aria-checked={checked} aria-label={label} onClick={onChange}><span /></button>
}

const sortOptions: Array<{ value: ArchiveSort; label: string; description: string }> = [
  { value: 'new', label: '최신순', description: '최근에 저장한 콘텐츠부터' },
  { value: 'old', label: '오래된순', description: '먼저 저장한 콘텐츠부터' },
]

const settingSections = [
  { id: 'account', label: '계정', icon: 'user' },
  { id: 'organize', label: 'AI 정리 방식', icon: 'settings' },
  { id: 'notification', label: '알림', icon: 'bell' },
  { id: 'display', label: '보관함 보기', icon: 'grid' },
  { id: 'data', label: '브라우저 설정', icon: 'database' },
]

export function SettingsPage() {
  const navigate = useNavigate()
  const session = getSession()
  const { notify } = useArchiveUi()
  const { items, collections, settings, setSettings } = useArchiveStore()
  const [activeSection, setActiveSection] = useState('account')
  const resetData = () => { setSettings(defaultArchiveSettings); notify('이 브라우저의 보기 설정을 초기화했어요. 저장한 콘텐츠는 그대로 유지돼요.') }
  useEffect(() => {
    const updateActiveSection = () => {
      const sections = settingSections.map(({ id }) => document.getElementById(id)).filter((section): section is HTMLElement => Boolean(section))
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 24) { setActiveSection(sections.at(-1)?.id || 'account'); return }
      const passed = sections.filter((section) => section.getBoundingClientRect().top <= 150)
      const current = passed.at(-1) || sections[0]
      if (current?.id) setActiveSection(current.id)
    }
    window.addEventListener('scroll', updateActiveSection, { passive: true })
    window.addEventListener('hashchange', updateActiveSection)
    const frame = window.requestAnimationFrame(updateActiveSection)
    return () => { window.cancelAnimationFrame(frame); window.removeEventListener('scroll', updateActiveSection); window.removeEventListener('hashchange', updateActiveSection) }
  }, [])

  return <main className={`content archive-content ${styles.settingsContent}`}>
    <ArchivePageHeader title="설정" description="계정 정보와 콘텐츠 정리 방식, 보관함 설정을 확인하고 변경할 수 있어요." action={<button type="button" className="button" onClick={() => navigate('/dashboard')}>내 저장소로</button>} />
    <div className={styles.settingsLayout}>
      <nav className={styles.settingsNav} aria-label="설정 항목">{settingSections.map((section) => <a key={section.id} href={`#${section.id}`} className={activeSection === section.id ? styles.selected : undefined} aria-current={activeSection === section.id ? 'location' : undefined} onClick={() => setActiveSection(section.id)}><Icon name={section.icon} />{section.label}</a>)}</nav>

      <div className={styles.panels}>
        <section className={styles.panel} id="account">
          <div className={styles.panelHeading}><h2>계정</h2><p>{session ? '현재 로그인한 계정 정보를 확인할 수 있어요.' : '데모 데이터를 읽기 전용으로 이용 중이에요.'}</p></div>
          <div className={styles.profileRow}><span className={styles.profileImage} role="img" aria-label="내 저장소 프로필 이미지"><Icon name="user" /></span><div><strong>내 저장소</strong><small>{session?.user.email || '데모'}</small></div><button type="button" className="button" onClick={() => { void logout().catch(() => {}).finally(() => navigate('/login')) }}>{session ? '로그아웃' : '로그인'}</button></div>
          <div className={styles.socialRow}><span className={styles.socialIcon}><Icon name="link" /></span><span><strong>소셜 계정</strong><small>{session ? '연결된 계정으로 로그인했어요.' : '로그인 후 저장할 수 있어요.'}</small></span><b>{session ? '연결됨' : '데모'}</b></div>
          <div className={styles.onboardingRow}><span><strong>시작 안내 다시 보기</strong><small>처음 시작할 때의 세 가지 질문을 다시 진행할 수 있어요.</small></span><button type="button" className="button" onClick={() => { restartOnboarding(); navigate('/onboarding') }}>다시 보기</button></div>
        </section>

        <section className={styles.panel} id="organize">
          <div className={styles.panelHeading}><h2>AI 정리 방식</h2><p>이 브라우저에서 새로 저장하는 콘텐츠의 분석 결과를 어떻게 반영할지 선택해 보세요. 기존 콘텐츠와 컬렉션은 바뀌지 않아요.</p></div>
          <div className={styles.viewChoices}>
            <button type="button" className={settings.organizeMode === 'confirm' ? styles.choiceActive : styles.choice} aria-pressed={settings.organizeMode === 'confirm'} onClick={() => setSettings((value) => ({ ...value, organizeMode: 'confirm' }))}><span className={styles.modePreview}><Icon name="user" /></span><b>확인 후 정리</b><small>분석 결과를 확인한 뒤 적용해요. 기본 설정이에요.</small></button>
            <button type="button" className={settings.organizeMode === 'automatic' ? styles.choiceActive : styles.choice} aria-pressed={settings.organizeMode === 'automatic'} onClick={() => setSettings((value) => ({ ...value, organizeMode: 'automatic' }))}><span className={styles.modePreview}><Icon name="check" /></span><b>자동 정리</b><small>분석한 요약과 태그를 바로 반영해요.</small></button>
          </div>
        </section>

        <section className={styles.panel} id="notification">
          <div className={styles.panelHeading}><h2>알림</h2><p>서비스 화면에 표시되는 안내를 설정할 수 있어요. 푸시나 이메일 알림은 보내지 않아요.</p></div>
          <div className={styles.optionRow}><span><strong>분석 완료 알림</strong><small>콘텐츠 상세 화면에서 분석 상태를 확인할 수 있어요.</small></span><Switch checked={settings.analysisNotifications} onChange={() => setSettings((value) => ({ ...value, analysisNotifications: !value.analysisNotifications }))} label="분석 완료 알림" /></div>
          <div className={styles.optionRow}><span><strong>정리할 콘텐츠 안내</strong><small>컬렉션 관련 안내는 아직 사용할 수 없어요.</small></span><Switch checked={false} onChange={() => notify('컬렉션 관련 안내는 아직 사용할 수 없어요.')} label="정리할 콘텐츠 안내" /></div>
        </section>

        <section className={styles.panel} id="display">
          <div className={styles.panelHeading}><h2>보관함 보기</h2><p>모든 콘텐츠 화면에서 사용할 기본 보기와 정렬 방식을 선택해 보세요.</p></div>
          <div className={styles.settingGroup}><div className={styles.settingGroupTitle}><strong>기본 보기</strong><small>콘텐츠를 보여주는 기본 형태</small></div><div className={styles.viewChoicesCompact}><button type="button" className={settings.defaultDisplay === 'grid' ? styles.choiceActive : styles.choice} aria-pressed={settings.defaultDisplay === 'grid'} onClick={() => setSettings((value) => ({ ...value, defaultDisplay: 'grid' }))}><span className={styles.gridPreview}><i /><i /><i /><i /></span><b>격자 보기</b><small>썸네일을 중심으로 살펴봐요.</small></button><button type="button" className={settings.defaultDisplay === 'list' ? styles.choiceActive : styles.choice} aria-pressed={settings.defaultDisplay === 'list'} onClick={() => setSettings((value) => ({ ...value, defaultDisplay: 'list' }))}><span className={styles.listPreview}><i /><i /><i /></span><b>목록 보기</b><small>콘텐츠를 목록으로 살펴봐요.</small></button></div></div>
          <div className={styles.settingGroup}><div className={styles.settingGroupTitle}><strong>기본 정렬</strong><small>콘텐츠를 표시할 순서</small></div><div className={styles.sortChoices}>{sortOptions.map((option) => <button type="button" key={option.value} className={settings.defaultSort === option.value ? styles.sortChoiceActive : styles.sortChoice} aria-pressed={settings.defaultSort === option.value} onClick={() => setSettings((value) => ({ ...value, defaultSort: option.value }))}><span><Icon name={option.value === 'title' ? 'list' : 'clock'} /></span><b>{option.label}</b><small>{option.description}</small></button>)}</div></div>
        </section>

        <section className={styles.panel} id="data">
          <div className={styles.panelHeading}><h2>브라우저 설정 관리</h2><p>이 브라우저에 저장된 보기 설정만 초기화할 수 있어요. 콘텐츠는 삭제되지 않아요.</p></div>
          <div className={styles.dataSummary}><div><span>{items.length}</span><small>불러온 콘텐츠</small></div><div><span>{collections.length}</span><small>컬렉션</small></div><div><span>{items.filter((item) => item.analysisStatus === 'analyzing' || !item.collectionIds.length).length}</span><small>정리 중이거나 컬렉션에 없는 콘텐츠</small></div></div>
          <div className={styles.dataRow}><span><strong>브라우저 설정 초기화</strong><small>보기 설정만 초기화하고 콘텐츠는 그대로 유지해요.</small></span><button type="button" className={`button ${styles.danger}`} onClick={resetData}>초기화</button></div>
        </section>
      </div>
    </div>
  </main>
}
