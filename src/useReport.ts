import { useEffect, useSyncExternalStore } from 'react'

type Snapshot = { data: unknown; error: string; loading: boolean; revision: number }
const empty: Snapshot = { data: null, error: '', loading: true, revision: -1 }
const snapshots = new Map<string, Snapshot>()
const listeners = new Set<() => void>()
const pending = new Map<string, Promise<void>>()
export const reportSnapshot = (url: string) => snapshots.get(url) ?? empty
function publish(url: string, value: Snapshot) {
  snapshots.set(url, value)
  listeners.forEach(notify => notify())
}
export async function loadReport(url: string, revision: number): Promise<void> {
  if (pending.has(url)) {
    await pending.get(url)
    return loadReport(url, revision)
  }
  const previous = snapshots.get(url) ?? empty
  if (previous.revision >= revision) return
  publish(url, { ...previous, error: '', loading: true, revision })
  const request = (async () => {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 30000)
    try {
      const response = await fetch(url, { signal: controller.signal })
      const data = await response.json()
      if (!response.ok) {
        const message = typeof data.detail === 'string' ? data.detail : `Saved data unavailable (HTTP ${response.status}).`
        publish(url, { data: response.status === 422 || response.status === 404 ? null : previous.data, error: message, loading: false, revision })
      } else publish(url, { data, error: '', loading: false, revision })
    } catch (error) {
      publish(url, { data: previous.data, error: error instanceof Error && error.name !== 'AbortError' ? error.message : 'Reading saved data timed out.', loading: false, revision })
    } finally { clearTimeout(timeout) }
  })()
  pending.set(url, request)
  await request
  pending.delete(url)
}
export function useReport<T>(url: string, revision: number) {
  const snapshot = useSyncExternalStore(
    notify => { listeners.add(notify); return () => { listeners.delete(notify) } },
    () => reportSnapshot(url),
  )
  useEffect(() => { void loadReport(url, revision) }, [url, revision])
  return { ...snapshot, data: snapshot.data as T | null }
}
