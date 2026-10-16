import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
const { signingOrder, brandMacRuntime } = createRequire(import.meta.url)('../scripts/brand_desktop.cjs')

test('Mac signing seals nested Mach-O code and frameworks before their containing app', () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'deck-signing-'))
  try {
    const bundle = path.join(temporary, 'Electron.app')
    const framework = path.join(bundle, 'Contents/Frameworks/Electron Framework.framework')
    const binary = path.join(framework, 'Versions/A/Electron Framework')
    fs.mkdirSync(path.dirname(binary), { recursive: true })
    fs.writeFileSync(binary, Buffer.from('cffaedfe00000000', 'hex'))
    fs.writeFileSync(path.join(framework, 'Info.plist'), '<plist>resources are not executable code</plist>')
    if (process.platform !== 'win32') fs.symlinkSync('A', path.join(framework, 'Versions/Current'))
    assert.deepEqual(signingOrder(bundle), [binary, framework, bundle])
    assert.equal(brandMacRuntime(temporary, 'linux'), false)
    assert.equal(brandMacRuntime(temporary, 'win32'), false)
  } finally { fs.rmSync(temporary, { recursive: true, force: true }) }
})
