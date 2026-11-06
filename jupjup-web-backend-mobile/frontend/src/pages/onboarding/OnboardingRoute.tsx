import { useLocation, useNavigate } from 'react-router-dom'
import { OnboardingPage } from '@/features/onboarding/OnboardingPage'
import type { OnboardingAnswers } from '@/features/onboarding/onboardingData'

export function OnboardingRoute() {
  const navigate = useNavigate()
  const location = useLocation()
  const destination = (location.state as { from?: string } | null)?.from || '/dashboard'
  const finish = (_answers?: OnboardingAnswers) => navigate(destination, { replace: true })
  return <OnboardingPage onComplete={finish} />
}
