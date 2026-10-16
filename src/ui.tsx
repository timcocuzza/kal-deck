import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

export function useHash() {
  const [hash, setHash] = useState(() => window.location.hash.slice(1) || 'games')
  useEffect(() => {
    const update = () => setHash(window.location.hash.slice(1) || 'games')
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
  return hash
}
export function navigate(hash: string, replace = false) {
  if (replace) { history.replaceState(history.state, '', `#${hash}`); window.dispatchEvent(new HashChangeEvent('hashchange')) }
  else window.location.hash = hash
}

export function askPrice(value: string | null | undefined) {
  return value == null || !Number.isFinite(Number(value)) ? 'Unavailable' : `${(Number(value) * 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}¢`
}

export function Dropdown({ label, value, options, onChange, disabled = false }: {
  label: string; value: string; options: { value: string; label: string }[]
  onChange: (value: string) => void; disabled?: boolean
}) {
  const ref = useRef<HTMLDetailsElement>(null)
  const [open, setOpen] = useState(false)
  const id = useId()
  const selected = options.find(option => option.value === value)
  const close = () => { if (ref.current) ref.current.open = false; setOpen(false) }
  useLayoutEffect(() => {
    if (!open) return
    const menu = ref.current!, panel = menu.querySelector<HTMLElement>('.dropdown-panel')!
    const viewport = window.visualViewport
    const position = () => {
      panel.style.left = '0px'
      const bounds = menu.getBoundingClientRect()
      const left = (viewport?.offsetLeft ?? 0) + 12
      const right = (viewport?.offsetLeft ?? 0) + (viewport?.width ?? document.documentElement.clientWidth) - 12
      panel.style.maxWidth = `${Math.max(0, right - left)}px`
      panel.style.minWidth = `${Math.min(Math.max(160, bounds.width), Math.max(0, right - left))}px`
      panel.style.left = `${Math.max(left, Math.min(bounds.left, right - panel.offsetWidth)) - bounds.left}px`
      const top = (viewport?.offsetTop ?? 0) + 12, bottom = (viewport?.offsetTop ?? 0) + (viewport?.height ?? window.innerHeight) - 12
      const above = Math.max(0, bounds.top - top - 6), below = Math.max(0, bottom - bounds.bottom - 6)
      const up = panel.scrollHeight > below && above > below
      menu.classList.toggle('dropdown-up', up)
      panel.style.maxHeight = `${up ? above : below}px`
    }
    const outside = (event: PointerEvent) => { if (!menu.contains(event.target as Node)) close() }
    const other = (event: Event) => { if (event.target !== menu) close() }
    document.querySelectorAll<HTMLDetailsElement>('.dropdown[open]').forEach(item => { if (item !== menu) item.open = false })
    menu.dispatchEvent(new Event('deck-menu-open', { bubbles: true }))
    position()
    document.addEventListener('pointerdown', outside)
    document.addEventListener('deck-menu-open', other)
    window.addEventListener('resize', position)
    window.addEventListener('scroll', position, true)
    viewport?.addEventListener('resize', position)
    return () => {
      document.removeEventListener('pointerdown', outside); document.removeEventListener('deck-menu-open', other)
      window.removeEventListener('resize', position); window.removeEventListener('scroll', position, true)
      viewport?.removeEventListener('resize', position)
    }
  }, [open])
  return <details ref={ref} className="dropdown" onToggle={event => setOpen(event.currentTarget.open)}
    onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); ref.current?.querySelector('summary')?.focus() }
      if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) && !disabled) {
        event.preventDefault()
        ref.current!.open = true; setOpen(true)
        const buttons = [...ref.current!.querySelectorAll<HTMLButtonElement>('.dropdown-panel button')]
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : index < 0 ? (event.key === 'ArrowUp' ? buttons.length - 1 : 0) : (index + (event.key === 'ArrowUp' ? -1 : 1) + buttons.length) % buttons.length
        buttons[next]?.focus()
      }
    }}>
    <summary aria-label={`${label}: ${selected?.label ?? 'Unavailable'}`} aria-controls={id} aria-haspopup="menu" aria-disabled={disabled}
      onClick={event => { if (disabled) event.preventDefault() }}>{selected?.label ?? 'Unavailable'}<span aria-hidden="true">⌄</span></summary>
    <div id={id} className="dropdown-panel" role="menu" aria-label={label}>{options.map(option => <button type="button" key={option.value}
      role="menuitemradio" aria-checked={option.value === value}
      onClick={() => { onChange(option.value); close(); ref.current?.querySelector('summary')?.focus() }}>
      {option.label}{option.value === value && <span aria-hidden="true">✓</span>}
    </button>)}</div>
  </details>
}

export function Modal({ title, children, onClose, className = '', closeLabel = 'Close game log' }: {
  title: string; children: ReactNode; onClose: () => void; className?: string; closeLabel?: string
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const id = useId()
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const dialog = ref.current!
    dialog.showModal()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { dialog.close(); document.body.style.overflow = overflow; if (previous?.isConnected) previous.focus({ preventScroll: true }) }
  }, [])
  useEffect(() => { ref.current?.querySelector('button')?.focus({ preventScroll: true }) }, [title])
  return <dialog ref={ref} className={`log-dialog ${className}`} aria-labelledby={id} onCancel={event => { event.preventDefault(); onClose() }}
    onClick={event => {
      if (event.target !== event.currentTarget) return
      const bounds = event.currentTarget.getBoundingClientRect()
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose()
    }}>
    <header className="dialog-heading"><h2 id={id}>{title}</h2><button autoFocus onClick={onClose} aria-label={closeLabel}>Close <span aria-hidden="true">×</span></button></header>
    {children}
  </dialog>
}
