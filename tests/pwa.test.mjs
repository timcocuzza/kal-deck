import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import test from 'node:test'

const worker = await readFile(new URL('../public/sw.js', import.meta.url), 'utf8')

function harness({ offline = false, missingFallback = false } = {}) {
  const handlers = {}
  const saved = new Response('recovery page')
  const cached = [], removed = []
  const cache = { add: async request => cached.push(request), match: async () => missingFallback ? undefined : saved }
  const context = {
    URL, Request, Response,
    self: { location: { origin: 'http://127.0.0.1:8000' }, clients: { claim: async () => {} }, addEventListener: (name, handler) => { handlers[name] = handler } },
    caches: { open: async () => cache, keys: async () => ['kalshi-deck-recovery-v0', 'kalshi-deck-recovery-v1', 'deck-recovery-v2', 'another-app'], delete: async name => removed.push(name) },
    fetch: async () => { if (offline) throw new TypeError('Disconnected'); return new Response('current response') },
  }
  // Node requires absolute Request URLs; browser workers resolve against origin.
  context.Request = class extends Request { constructor(url, init) { super(new URL(url, context.self.location.origin), init) } }
  vm.runInNewContext(worker, context)
  return { handlers, cached, removed }
}

function request(h, path = '/', overrides = {}) {
  let response
  h.handlers.fetch({ request: { url: `http://127.0.0.1:8000${path}`, method: 'GET', mode: 'navigate', ...overrides }, respondWith: promise => { response = promise } })
  return response
}

test('only recovery HTML is stored; activation leaves other app caches alone', async () => {
  const h = harness()
  let pending
  h.handlers.install({ waitUntil: promise => { pending = promise } })
  await pending
  assert.deepEqual(h.cached.map(r => new URL(r.url).pathname), ['/offline.html'])
  assert.equal(h.cached[0].cache, 'reload')
  h.handlers.activate({ waitUntil: promise => { pending = promise } })
  await pending
  assert.deepEqual(h.removed, ['kalshi-deck-recovery-v0', 'kalshi-deck-recovery-v1'])
})

test('online navigation uses the service; offline navigation has a useful recovery', async () => {
  assert.equal(await (await request(harness())).text(), 'current response')
  assert.equal(await (await request(harness({ offline: true }))).text(), 'recovery page')
  const emergency = await request(harness({ offline: true, missingFallback: true }))
  assert.equal(emergency.status, 503)
  assert.match(await emergency.text(), /bash scripts\/start.sh/)
})

test('API reads, writes, assets and external URLs are never intercepted or replayed', () => {
  const h = harness({ offline: true })
  assert.equal(request(h, '/api/matchups?season=2026'), undefined)
  assert.equal(request(h, '/api/tracker', { method: 'POST' }), undefined)
  assert.equal(request(h, '/api/sources/spreads/refresh', { method: 'POST' }), undefined)
  assert.equal(request(h, '/assets/app.js', { mode: 'cors' }), undefined)
  assert.equal(request(h, '/', { url: 'https://example.com/' }), undefined)
})

test('install manifest points to real correctly sized PNG icons', async () => {
  const manifest = JSON.parse(await readFile(new URL('../public/manifest.webmanifest', import.meta.url)))
  assert.equal(manifest.start_url, '/#games')
  assert.equal(manifest.display, 'standalone')
  for (const icon of manifest.icons) {
    const png = await readFile(new URL(`../public${icon.src}`, import.meta.url))
    assert.equal(png.subarray(1, 4).toString(), 'PNG')
    assert.equal(`${png.readUInt32BE(16)}x${png.readUInt32BE(20)}`, icon.sizes)
  }
})
