/// <reference types="vite/client" />

interface Window {
  deckDesktop?: Readonly<{
    enabled: true
    getUpdateState: () => Promise<DeckUpdateState>
    update: () => Promise<DeckUpdateState>
    restart: () => Promise<void>
    onUpdate: (callback: (value: DeckUpdateState) => void) => () => void
  }>
}

interface DeckUpdateState {
  status: 'unavailable' | 'idle' | 'checking' | 'preparing' | 'ready' | 'error'
  message: string
  revision?: string
}
