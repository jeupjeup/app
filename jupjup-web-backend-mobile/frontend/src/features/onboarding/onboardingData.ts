/** Lightweight, local-only initial survey model. Connect persistence to the backend when available. */
export const ONBOARDING_KEY = 'jupjup_onboarding_answers_v1';
export const ONBOARDING_STATUS_KEY = 'jupjup_onboarding_completed_v1';

export type OnboardingAnswers = {
  content: 'reference' | 'fun';
  discovery: 'location' | 'forgot';
  purpose: 'retrieve' | 'organize';
};

export const surveyQuestions = [
  {
    key: 'content',
    title: '평소 어떤 콘텐츠를 더 많이 저장하나요?',
    options: [
      { value: 'reference', label: '나중에 참고할 정보나 자료' },
      { value: 'fun', label: '취향에 맞는 재미있는 콘텐츠' },
    ],
  },
  {
    key: 'discovery',
    title: '저장한 콘텐츠를 다시 찾을 때 어떤 경험이 더 많나요?',
    options: [
      { value: 'location', label: '어디에 저장했는지 기억나지 않아요' },
      { value: 'forgot', label: '저장한 사실 자체를 잊어버려요' },
    ],
  },
  {
    key: 'purpose',
    title: '줍줍 저장소를 어떻게 활용하고 싶나요?',
    options: [
      { value: 'retrieve', label: '필요한 정보를 빠르게 다시 찾고 싶어요' },
      { value: 'organize', label: '모아둔 콘텐츠를 정리하고 활용하고 싶어요' },
    ],
  },
] as const;

export function readOnboarding(): OnboardingAnswers | null {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(ONBOARDING_KEY) || 'null');
    if (!parsed || typeof parsed !== 'object') return null;
    const v = parsed as Partial<OnboardingAnswers>;
    if (!['reference','fun'].includes(v.content || '') || !['location','forgot'].includes(v.discovery || '') || !['retrieve','organize'].includes(v.purpose || '')) return null;
    return v as OnboardingAnswers;
  } catch { return null; }
}

export function saveOnboarding(answers: OnboardingAnswers): void {
  try { localStorage.setItem(ONBOARDING_KEY, JSON.stringify(answers)); localStorage.setItem(ONBOARDING_STATUS_KEY, 'true'); }
  catch { /* A local-only preview can proceed without persisted storage. */ }
}

export function isOnboardingComplete(): boolean {
  try { return localStorage.getItem(ONBOARDING_STATUS_KEY) === 'true' || Boolean(readOnboarding()); }
  catch { return false; }
}

export function skipOnboarding(): void {
  try { localStorage.setItem(ONBOARDING_STATUS_KEY, 'true'); }
  catch { /* The preview can continue for the current navigation. */ }
}

export function restartOnboarding(): void {
  try { localStorage.removeItem(ONBOARDING_KEY); localStorage.removeItem(ONBOARDING_STATUS_KEY); }
  catch { /* The route still opens even when storage is blocked. */ }
}
