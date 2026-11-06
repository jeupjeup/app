import { beforeEach, describe, expect, it } from 'vitest'
import { isOnboardingComplete, readOnboarding, restartOnboarding, saveOnboarding, skipOnboarding } from './onboardingData'

describe('onboarding persistence', () => {
  beforeEach(() => localStorage.clear())

  it('persists valid answers and completion', () => {
    const answers = { content: 'reference', discovery: 'location', purpose: 'retrieve' } as const
    saveOnboarding(answers)
    expect(readOnboarding()).toEqual(answers)
    expect(isOnboardingComplete()).toBe(true)
  })

  it('supports skipping and restarting', () => {
    skipOnboarding()
    expect(isOnboardingComplete()).toBe(true)
    restartOnboarding()
    expect(isOnboardingComplete()).toBe(false)
  })
})
