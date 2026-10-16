'use strict'
const fs = require('node:fs')
const path = require('node:path')
const { execFileSync } = require('node:child_process')

function brandMacRuntime(root, platform = process.platform, execute = execFileSync) {
  if (platform !== 'darwin') return false
  const bundle = path.join(root, 'node_modules/electron/dist/Electron.app')
  if (!fs.existsSync(bundle)) return false // A web-only build need not install Electron.
  const contents = path.join(bundle, 'Contents')
  const info = path.join(contents, 'Info.plist')
  const options = { encoding: 'utf8', timeout: 120000 }
  const read = file => JSON.parse(execute('/usr/bin/plutil', ['-convert', 'json', '-o', '-', file], options))
  const metadata = read(info)
  const update = (file, original, values) => {
    for (const [key, value] of Object.entries(values)) {
      execute('/usr/bin/plutil', [key in original ? '-replace' : '-insert', key, '-string', value, file], options)
    }
  }
  // Keep the executable and bundle paths compatible with already-installed launchers.
  update(info, metadata, { CFBundleName: 'Deck', CFBundleDisplayName: 'Deck',
    CFBundleIdentifier: 'com.getwellsedge.deck.runtime', CFBundleIconFile: 'deck.icns' })
  const resources = path.join(contents, 'Resources')
  fs.copyFileSync(path.join(root, 'desktop/icons/deck.icns'), path.join(resources, 'deck.icns'))
  for (const entry of fs.readdirSync(resources, { withFileTypes: true })) {
    if (!entry.isDirectory() || !entry.name.endsWith('.lproj')) continue
    const localized = path.join(resources, entry.name, 'InfoPlist.strings')
    if (fs.existsSync(localized)) update(localized, read(localized), { CFBundleName: 'Deck', CFBundleDisplayName: 'Deck' })
  }
  // Editing a signed bundle invalidates its seal. Ad-hoc signing is local and needs
  // no account/certificate. Preserve Electron's runtime entitlements and leave its
  // nested binaries untouched; verify the entire bundle before accepting it.
  execute('/usr/bin/codesign', ['--force', '--sign', '-', '--preserve-metadata=entitlements,flags,runtime', bundle], options)
  execute('/usr/bin/codesign', ['--verify', '--deep', '--strict', bundle], options)
  const branded = read(info)
  if (branded.CFBundleName !== 'Deck' || branded.CFBundleDisplayName !== 'Deck') throw new Error('Mac runtime branding did not persist.')
  execute(path.join(contents, 'MacOS', metadata.CFBundleExecutable), ['-e', 'process.stdout.write(process.versions.electron)'],
    { ...options, env: { ...process.env, ELECTRON_RUN_AS_NODE: '1', NODE_OPTIONS: '' } })
  return true
}

if (require.main === module && brandMacRuntime(path.resolve(__dirname, '..'))) console.log('Mac runtime branded as Deck; signature and native startup verified.')
module.exports = { brandMacRuntime }
