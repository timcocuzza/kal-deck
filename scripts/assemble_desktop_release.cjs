'use strict'
const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const yaml = require('js-yaml')

function mergeManifests(manifests, version) {
  if (!manifests.length) throw new Error('No update manifests')
  const files = new Map()
  for (const manifest of manifests) {
    if (manifest.version !== version || !Array.isArray(manifest.files) || !manifest.files.length) throw new Error('Release version or files mismatch')
    for (const file of manifest.files) {
      if (typeof file.url !== 'string' || !/^Deck-[A-Za-z0-9._-]+$/.test(file.url) || !file.sha512 || !Number.isSafeInteger(file.size) || file.size <= 0) throw new Error('Invalid release file')
      if (files.has(file.url) && files.get(file.url).sha512 !== file.sha512) throw new Error('Conflicting update files')
      files.set(file.url, file)
    }
  }
  // Current clients use files[]. Do not leave an architecture-specific legacy path.
  const merged = { ...manifests[0], files: [...files.values()] }
  delete merged.path; delete merged.sha512
  return merged
}

function walk(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    if (entry.isSymbolicLink()) throw new Error('Artifact symlinks are not allowed')
    const file = path.join(directory, entry.name)
    return entry.isDirectory() ? walk(file) : [file]
  })
}

function assemble(input, output, version) {
  fs.mkdirSync(output, { recursive: true })
  if (fs.readdirSync(output).length) throw new Error('Release output must start empty')
  const manifests = new Map()
  for (const file of walk(input)) {
    const name = path.basename(file)
    if (/^latest(?:-mac|-linux)?\.yml$/.test(name)) {
      const group = manifests.get(name) || []
      group.push(yaml.load(fs.readFileSync(file, 'utf8'))); manifests.set(name, group)
    } else if (/^Deck-[A-Za-z0-9._-]+\.(exe|dmg|zip|AppImage|blockmap)$/.test(name)) {
      const dest = path.join(output, name)
      if (fs.existsSync(dest)) throw new Error('Duplicate release artifact')
      fs.copyFileSync(file, dest)
    }
  }
  for (const name of ['latest.yml', 'latest-linux.yml', 'latest-mac.yml']) {
    const merged = mergeManifests(manifests.get(name) || [], version)
    for (const file of merged.files) {
      const body = fs.readFileSync(path.join(output, file.url))
      if (body.length !== file.size || crypto.createHash('sha512').update(body).digest('base64') !== file.sha512) throw new Error('Artifact checksum mismatch')
    }
    if (name === 'latest-mac.yml' && !['arm64', 'x64'].every(arch => merged.files.some(file => file.url.endsWith(`-${arch}.zip`)))) throw new Error('Both Mac architectures are required')
    fs.writeFileSync(path.join(output, name), yaml.dump(merged))
  }
  const sums = fs.readdirSync(output).sort().map(name => `${crypto.createHash('sha256').update(fs.readFileSync(path.join(output, name))).digest('hex')}  ${name}`)
  fs.writeFileSync(path.join(output, 'SHA256SUMS'), `${sums.join('\n')}\n`)
}

module.exports = { mergeManifests, assemble }
if (require.main === module) {
  const { version } = require('../package.json')
  assemble('release/incoming', 'release/publish', version)
}
