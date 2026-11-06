import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { startSocialLogin } from '@/shared/auth/session'
import { AuthPage } from './AuthPage'
vi.mock('@/shared/auth/session', () => ({ startSocialLogin: vi.fn() }))
afterEach(() => { cleanup(); vi.resetAllMocks() })
it.each(['login', 'signup'] as const)('offers only Google and Naver login options in %s mode', mode => {
  render(<MemoryRouter><AuthPage mode={mode} /></MemoryRouter>)
  expect(screen.getAllByRole('button')).toHaveLength(2)
  expect(screen.getByRole('button', { name: 'Google로 계속하기' })).toBeEnabled()
  expect(screen.getByRole('button', { name: '네이버로 계속하기' })).toBeEnabled()
  expect(screen.queryByRole('button', { name: /카카오|kakao/i })).not.toBeInTheDocument()
  expect(screen.queryByText(/카카오|kakao/i)).not.toBeInTheDocument()
  expect(screen.queryByTitle(/카카오|kakao/i)).not.toBeInTheDocument()
})
it.each(['google', 'naver'] as const)('enables %s and announces loading', async provider => {
  render(<MemoryRouter><AuthPage mode="login" /></MemoryRouter>)
  const button = screen.getByRole('button', { name: provider === 'google' ? 'Google로 계속하기' : '네이버로 계속하기' })
  expect(button).toBeEnabled()
  await userEvent.click(button)
  expect(startSocialLogin).toHaveBeenCalledWith(provider, false)
  expect(button).toHaveAttribute('aria-busy', 'true')
  expect(screen.getByRole('status')).toBeInTheDocument()
})
it.each(['google', 'naver'] as const)('requests onboarding from %s signup', async provider => {
  render(<MemoryRouter><AuthPage mode="signup" /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: provider === 'google' ? 'Google로 계속하기' : '네이버로 계속하기' }))
  expect(startSocialLogin).toHaveBeenCalledWith(provider, true)
})
it('announces redirect failure and allows retry', async () => {
  vi.mocked(startSocialLogin).mockImplementation(() => { throw new Error('navigation failed') })
  render(<MemoryRouter><AuthPage mode="login" /></MemoryRouter>)
  await userEvent.click(screen.getByRole('button', { name: 'Google로 계속하기' }))
  expect(screen.getByRole('alert')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Google로 계속하기' })).toBeEnabled()
})
