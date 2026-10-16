import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'
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

const { mergeManifests } = require('../scripts/assemble_desktop_release.cjs')
test('release feed keeps both Mac architectures and rejects conflicting versions and unsafe paths', () => {
  const manifest = (arch, version = '0.2.0') => ({ version, path: 'legacy.zip', sha512: 'legacy',
    files: [{ url: `Deck-${version}-mac-${arch}.zip`, sha512: `hash-${arch}`, size: 123 }] })
  const merged = mergeManifests([manifest('arm64'), manifest('x64')], '0.2.0')
  assert.equal(merged.files.length, 2)
  assert.equal(merged.path, undefined)
  assert.equal(merged.sha512, undefined)
  assert.throws(() => mergeManifests([manifest('arm64'), manifest('x64', '0.1.0')], '0.2.0'))
  const unsafe = manifest('x64'); unsafe.files[0].url = '../../private.txt'
  assert.throws(() => mergeManifests([unsafe], '0.2.0'))
  const conflict = manifest('x64'); conflict.files[0].sha512 = 'different'
  assert.throws(() => mergeManifests([manifest('x64'), conflict], '0.2.0'))
})

test('release assembly verifies the actual installers before publishing update manifests', () => {
  const { assemble } = require('../scripts/assemble_desktop_release.cjs')
  const yaml = require('js-yaml')
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'deck-release-'))
  try {
    const input = path.join(root, 'incoming')
    const targets = [
      ['win', 'latest.yml', 'Deck-0.2.0-win-x64.exe'],
      ['linux', 'latest-linux.yml', 'Deck-0.2.0-linux-x86_64.AppImage'],
      ['mac-arm64', 'latest-mac.yml', 'Deck-0.2.0-mac-arm64.zip'],
      ['mac-x64', 'latest-mac.yml', 'Deck-0.2.0-mac-x64.zip'],
    ]
    for (const [platform, feed, name] of targets) {
      const folder = path.join(input, platform)
      fs.mkdirSync(folder, { recursive: true })
      const body = Buffer.from(`test installer for ${platform}`)
      fs.writeFileSync(path.join(folder, name), body)
      fs.writeFileSync(path.join(folder, feed), yaml.dump({ version: '0.2.0', files: [
        { url: name, size: body.length, sha512: crypto.createHash('sha512').update(body).digest('base64') },
      ] }))
    }
    const output = path.join(root, 'publish')
    assemble(input, output, '0.2.0')
    assert.equal(yaml.load(fs.readFileSync(path.join(output, 'latest-mac.yml'), 'utf8')).files.length, 2)
    assert.equal(fs.readFileSync(path.join(output, 'SHA256SUMS'), 'utf8').trim().split('\n').length, 7)
    fs.appendFileSync(path.join(input, 'win', targets[0][2]), 'tampered')
    assert.throws(() => assemble(input, path.join(root, 'tampered'), '0.2.0'), /checksum mismatch/)
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})
