import { createPortal } from 'react-dom'
import { useEffect, useRef, type ReactNode } from 'react'

export function AccessibleDialog({ titleId, onClose, className = '', children }: { titleId: string; onClose: () => void; className?: string; children: ReactNode }) {
  const closeRef = useRef(onClose)
  useEffect(() => { closeRef.current = onClose }, [onClose])
  const dialogRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const shell = document.querySelector<HTMLElement>('.app-shell')
    const oldOverflow = document.body.style.overflow
    shell?.setAttribute('inert', '')
    document.body.style.overflow = 'hidden'
    const firstInput = dialogRef.current?.querySelector<HTMLElement>('input:not([disabled]), textarea:not([disabled]), select:not([disabled])')
    const firstButton = dialogRef.current?.querySelector<HTMLElement>('button:not([disabled]), a[href]')
    ;(firstInput || firstButton)?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current(); return }
      if (event.key !== 'Tab' || !dialogRef.current) return
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href]')).filter((node) => node.offsetParent !== null)
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey); shell?.removeAttribute('inert'); document.body.style.overflow = oldOverflow; previous?.focus() }
  }, [])
  return createPortal(<div className="dialog-backdrop open" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><div ref={dialogRef} className={`dialog ${className}`.trim()} role="dialog" aria-modal="true" aria-labelledby={titleId}>{children}</div></div>, document.body)
}
