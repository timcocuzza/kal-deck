import { useEffect, useState } from 'react'

interface InstallPrompt extends Event {
  prompt(): Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

export function InstallApp() {
  const [prompt, setPrompt] = useState<InstallPrompt | null>(null)
  const [installed, setInstalled] = useState(() => window.matchMedia('(display-mode: standalone)').matches)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const capture = (event: Event) => { event.preventDefault(); setPrompt(event as InstallPrompt) }
    const done = () => { setInstalled(true); setPrompt(null); setMessage('') }
    const mode = window.matchMedia('(display-mode: standalone)')
    const changed = () => { if (mode.matches) done() }
    window.addEventListener('beforeinstallprompt', capture)
    window.addEventListener('appinstalled', done)
    mode.addEventListener('change', changed)
    return () => {
      window.removeEventListener('beforeinstallprompt', capture)
      window.removeEventListener('appinstalled', done)
      mode.removeEventListener('change', changed)
    }
  }, [])

  async function install() {
    if (!prompt || busy) return
    setBusy(true)
    setMessage('')
    try {
      await prompt.prompt()
      const choice = await prompt.userChoice
      setMessage(choice.outcome === 'accepted' ? 'Installation requested. Finish in your browser.' : 'Installation dismissed. You can install later from your browser menu.')
    } catch {
      setMessage('The install prompt could not open. Use your browser’s install option instead.')
    } finally {
      setPrompt(null)
      setBusy(false)
    }
  }

  return <section className="install-card" aria-labelledby="install-title">
    <div><h2 id="install-title">{installed ? 'Kalshi Deck is installed' : 'Keep Kalshi Deck close'}</h2>
      <p>Open it in its own app window. Start the local service with <code>bash scripts/start.sh</code> and keep that terminal open while you use it.</p>
      {!installed && !prompt && <p className="source-note">In Chrome or Edge, use the address bar’s install icon or the browser menu’s install option when available.</p>}
      {message && !installed && <p role="status">{message}</p>}
    </div>
    {!installed && prompt && <button disabled={busy} onClick={() => void install()}>{busy ? 'Opening…' : 'Install app'}</button>}
  </section>
}
