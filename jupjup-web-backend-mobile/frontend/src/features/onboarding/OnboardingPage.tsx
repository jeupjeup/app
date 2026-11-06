import { useEffect, useState } from 'react';
import { BrandMark } from '@/features/jupjup-dashboard/components/Sidebar';
import { saveOnboarding, skipOnboarding, surveyQuestions, type OnboardingAnswers } from './onboardingData';
import './onboarding.css';

type AnswersDraft = Partial<OnboardingAnswers>;
type QuestionKey = keyof OnboardingAnswers;

function BrandIntro({ step }: { step: number }) {
  return <aside className="onb-story" aria-label="줍줍 저장소 소개">
    <div className="onb-story-inner">
      <div className="onb-story-heading" key={step}>
        {step === 0 ? <><h2>여기저기 저장했던 것들,<br /><em>이제 한곳에.</em></h2></> :
         step === 1 ? <><h2>그때 봤던 그거,<br /><em>다시 쉽게 찾아요.</em></h2></> :
         <><h2>모으는 것부터<br /><em>다시 발견하는 순간까지.</em></h2></>}
      </div>
      <div key={step} className={`onb-art onb-art-stage-${step}`} aria-hidden="true">
        <div className="onb-graphic-shadow" />
        <div className="onb-note onb-note-ig">
          <span className="onb-note-kicker"><span className="onb-source-dot peach" /> 게시물</span>
          <span className="onb-note-img onb-art-instagram"><span className="onb-mini-circle" /><span className="onb-mini-hill" /></span>
          <span className="onb-note-lines"><i /><i /></span>
        </div>
        <div className="onb-note onb-note-web">
          <span className="onb-note-kicker"><span className="onb-source-dot green" /> 웹페이지</span>
          <span className="onb-note-img onb-art-web"><span className="onb-web-window"><i /><i /><i /></span></span>
          <span className="onb-note-lines"><i /><i /></span>
        </div>
        <div className="onb-note onb-note-yt">
          <span className="onb-note-kicker"><span className="onb-source-dot red" /> YouTube</span>
          <span className="onb-note-img onb-art-video"><span className="onb-video-play" /></span>
          <span className="onb-note-lines"><i /><i /></span>
        </div>
        <div className="onb-art-dash">
          <div className="onb-art-dash-head"><span className="onb-art-brandmark"><BrandMark /></span><b>내 저장소</b><span className="onb-dash-dots"><i/><i/><i/></span></div>
          <div className="onb-art-search"><svg viewBox="0 0 24 24" fill="none"><circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.8"/><path d="m16 16 5 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg><span>{step === 1 ? '전에 저장했던 그거' : '콘텐츠를 검색해 보세요'}</span></div>
          <div className="onb-art-tabrow"><span className="selected">전체</span><span>영상</span><span>게시물</span><span>웹페이지</span></div>
          <div className="onb-art-cardrow">
            <div className={`onb-art-mini-card ${step === 1 ? 'onb-art-found' : ''}`}><span className="onb-art-mini-preview c1"><i /></span><b>피그마 디자인 팁</b><small>웹페이지 · 디자인</small></div>
            <div className="onb-art-mini-card"><span className="onb-art-mini-preview c2"><i /></span><b>주말의 작은 기록</b><small>게시물 · 일상</small></div>
            <div className="onb-art-mini-card"><span className="onb-art-mini-preview c3"><i /></span><b>만들어 보고 싶은 것</b><small>영상 · 취미</small></div>
          </div>
          <div className="onb-art-dash-bottom"><span /><span /></div>
        </div>
      </div>
    </div>
  </aside>;
}

export function OnboardingPage({ onComplete }: { onComplete: (answers?: OnboardingAnswers) => void }) {
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<AnswersDraft>({});
  const question = surveyQuestions[step];
  const key = question.key as QuestionKey;
  const selected = answers[key];
  const isLast = step === surveyQuestions.length - 1;

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, [contenteditable="true"]')) return;
      const pressed = event.key.toLowerCase();
      if (pressed === 'a' || pressed === '1') setAnswers(current => ({ ...current, [key]: question.options[0].value }));
      if (pressed === 'b' || pressed === '2') setAnswers(current => ({ ...current, [key]: question.options[1].value }));
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [key, question]);

  function next() {
    if (!selected) return;
    if (!isLast) { setStep(value => value + 1); return; }
    if (!answers.content || !answers.discovery || !answers.purpose) return;
    const complete = answers as OnboardingAnswers;
    saveOnboarding(complete);
    onComplete(complete);
  }

  return <main className="onb-layout">
    <section className="onb-form-side" aria-label="초기 설문">
      <div className="onb-form-inner">
        <header className="onb-form-header">
          <div className="onb-logo"><BrandMark /><span>줍줍<span className="onb-logo-dot">.</span>저장소</span></div>
          <button type="button" className="onb-skip" onClick={() => { skipOnboarding(); onComplete(); }}>건너뛰기</button>
        </header>
        <div className="onb-content">
          <div className="onb-progress-row">
            <div className="onb-progress" aria-label={`${step+1}번째 질문, 총 3개`}>
              {surveyQuestions.map((q, index) => <span key={q.key} className={`onb-progress-segment${index <= step ? ' active' : ''}`} />)}
            </div>
            <span className="onb-counter">0{step+1} / 03</span>
          </div>
          <div className="onb-question" key={question.key}>
            <h1>{question.title}</h1>
            <div className="onb-choices" role="radiogroup" aria-label={question.title}>
              {question.options.map((option) => <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={selected === option.value}
                className={`onb-choice${selected === option.value ? ' selected' : ''}`}
                onClick={() => setAnswers(current => ({ ...current, [key]: option.value }))}
              ><span className="onb-radio" aria-hidden="true" /><span>{option.label}</span></button>)}
            </div>
          </div>
          <div className="onb-actions">
            {step > 0 && <button className="onb-prev" type="button" onClick={() => setStep(value => value - 1)}><span aria-hidden="true">←</span> 이전</button>}
            <button className="onb-next" type="button" disabled={!selected} onClick={next}>{isLast ? '시작하기' : '다음'} <span aria-hidden="true">→</span></button>
          </div>
        </div>
      </div>
    </section>
    <BrandIntro step={step} />
  </main>;
}
