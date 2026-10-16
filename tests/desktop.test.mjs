import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
const require = createRequire(import.meta.url)
const { safeExternal, localRequest, backendPort } = require('../desktop/policy.cjs')

test('desktop opens only trusted HTTPS source links without credentials or custom handlers', () => {
  assert.equal(safeExternal('https://www.nfl.com/injuries/'), true)
  assert.equal(safeExternal('https://github.com/nflverse/nflverse-data'), true)
  for (const url of ['file:///etc/passwd', 'javascript:alert(1)', 'ms-settings:test',
    'https://www.nfl.com.evil.example/', 'https://evil.example', 'https://user:pass@www.nfl.com/',
    'http://www.nfl.com/', 'https://www.nfl.com:8080/', 'https://www.nfl.com@evil.example/']) {
    assert.equal(safeExternal(url), false, url)
  }
})

test('desktop token stays on the exact loopback origin and handshake validates ports', () => {
  const origin = 'http://127.0.0.1:48123'
  assert.equal(localRequest(`${origin}/api/tracker`, origin), true)
  for (const url of ['http://127.0.0.1:48124/api', 'http://localhost:48123/api', 'https://example.com', 'not a URL']) {
    assert.equal(localRequest(url, origin), false)
  }
  assert.equal(backendPort('{"type":"deck-backend","port":48123}'), 48123)
  for (const port of [0, -1, 65536, 1.1, '48123', null]) {
    assert.equal(backendPort(JSON.stringify({ type: 'deck-backend', port })), null)
  }
  assert.equal(backendPort('log output'), null)
})

const { sourceContext, trustedSender } = require('../desktop/source-updates.cjs')
test('source context requires an exact managed revision and a valid Python path', () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'deck-context-'))
  try {
    const revision = 'a'.repeat(40)
    const root = path.join(home, 'releases', revision)
    fs.writeFileSync(path.join(home, 'tools.json'), JSON.stringify({ python: process.execPath }))
    const env = { DECK_SOURCE_HOME: home, DECK_SOURCE_REVISION: revision }
    assert.equal(sourceContext(root, env).revision, revision)
    assert.equal(sourceContext(path.join(home, 'other'), env), null)
    assert.equal(sourceContext(root, { ...env, DECK_SOURCE_REVISION: '../../etc' }), null)
    fs.writeFileSync(path.join(home, 'tools.json'), JSON.stringify({ python: 'relative/python' }))
    assert.throws(() => sourceContext(root, env))
  } finally { fs.rmSync(home, { recursive: true, force: true }) }
})

test('update IPC accepts only the owning main frame on its private origin', () => {
  const origin = 'http://127.0.0.1:48123'
  const mainFrame = { url: origin + '/#games' }
  const webContents = { mainFrame }
  const window = { webContents }
  assert.equal(trustedSender({ sender: webContents, senderFrame: mainFrame }, window, origin), true)
  assert.equal(trustedSender({ sender: {}, senderFrame: mainFrame }, window, origin), false)
  assert.equal(trustedSender({ sender: webContents, senderFrame: { url: origin } }, window, origin), false)
  mainFrame.url = 'https://attacker.example'
  assert.equal(trustedSender({ sender: webContents, senderFrame: mainFrame }, window, origin), false)
  assert.equal(trustedSender({}, null, origin), false)
})
