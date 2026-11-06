import { render, screen } from '@testing-library/react'
import { App } from '@/app/App'

describe('App', () => {
  it('줍줍 저장소 랜딩페이지를 보여준다', () => {
    render(<App />)

    expect(
      screen.getByTitle('줍줍 저장소 랜딩페이지'),
    ).toHaveAttribute('src', '/jupjup-landing.html')
  })
})
