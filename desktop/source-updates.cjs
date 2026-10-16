'use strict'
const fs = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')
const readline = require('node:readline')

function sourceContext(root, env = process.env) {
  if (!env.DECK_SOURCE_HOME || !/^[a-f0-9]{40}$/.test(env.DECK_SOURCE_REVISION || '')) return null
  const home = path.resolve(env.DECK_SOURCE_HOME)
  if (path.resolve(root) !== path.join(home, 'releases', env.DECK_SOURCE_REVISION)) return null
  const tools = JSON.parse(fs.readFileSync(path.join(home, 'tools.json'), 'utf8'))
  if (!path.isAbsolute(tools.python) || !fs.existsSync(tools.python)) throw new Error('Deck’s Python installation is missing. Run setup again.')
  return { home, revision: env.DECK_SOURCE_REVISION, python: tools.python, root }
}

function trustedSender(event, window, origin) {
  return Boolean(window && event.sender === window.webContents &&
    event.senderFrame === window.webContents.mainFrame &&
    (() => { try { return new URL(event.senderFrame.url).origin === origin } catch { return false } })())
}

function createSourceUpdater(context, changed) {
  let state = { status: context ? 'idle' : 'unavailable', message: context ? 'Updates are ready to check.' : 'Run the desktop setup to enable updates.' }
  let worker
  function update(value) { state = value; changed({ ...state }) }
  function readReady() {
    if (!context) return
    try {
      const ready = JSON.parse(fs.readFileSync(path.join(context.home, 'ready.json'), 'utf8'))
      if (ready.from === context.revision && /^[a-f0-9]{40}$/.test(ready.revision)) {
        update({ status: 'ready', message: 'Update ready. Save your edits, then restart Deck.', revision: ready.revision.slice(0, 12) })
      }
    } catch { /* No completed update yet. */ }
  }
  function prepare() {
    if (!context || worker) return { ...state }
    update({ status: 'checking', message: 'Checking for a newer Deck version…' })
    const env = { ...process.env }
    for (const key of Object.keys(env)) if (key.startsWith('DECK_') || key.startsWith('PYTHON') || key === 'NODE_OPTIONS' || key === 'ELECTRON_RUN_AS_NODE') delete env[key]
    env.PYTHONUTF8 = '1'
    worker = spawn(context.python, [path.join(context.root, 'scripts/manage_desktop.py'), 'prepare', '--home', context.home],
      { cwd: context.home, env, stdio: ['ignore', 'pipe', 'ignore'], windowsHide: true })
    const lines = readline.createInterface({ input: worker.stdout })
    let terminal = false
    lines.on('line', line => {
      try {
        const value = JSON.parse(line)
        if (!['checking', 'preparing', 'idle', 'ready', 'error'].includes(value.status) || typeof value.message !== 'string') return
        terminal = ['idle', 'ready', 'error'].includes(value.status)
        update({ status: value.status, message: value.message.slice(0, 500),
          ...(typeof value.revision === 'string' && /^[a-f0-9]{12}$/.test(value.revision) ? { revision: value.revision } : {}) })
      } catch { /* Tool output is not exposed to the renderer. */ }
    })
    const failure = () => update({ status: 'error', message: 'The update could not finish. Your current version still works. Use File → Open update log for details.' })
    worker.on('error', failure)
    worker.once('close', code => { worker = null; lines.close(); if (!terminal || code && state.status !== 'error') failure() })
    return { ...state }
  }
  function restartAfterExit() {
    if (!context || state.status !== 'ready') throw new Error('No checked update is ready.')
    // The helper waits for this Electron process to exit before changing the pointer.
    const helper = spawn(context.python, [path.join(context.root, 'scripts/manage_desktop.py'), 'activate',
      '--home', context.home, '--wait-pid', String(process.pid)],
    { detached: true, stdio: 'ignore', windowsHide: true })
    helper.on('error', () => {})
    helper.unref()
  }
  readReady()
  return { state: () => ({ ...state }), prepare, restartAfterExit }
}

module.exports = { sourceContext, trustedSender, createSourceUpdater }
