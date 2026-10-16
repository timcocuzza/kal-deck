'use strict'

const { app, BrowserWindow, dialog, Menu, session, shell } = require('electron')
const { spawn } = require('node:child_process')
const { randomBytes } = require('node:crypto')
const { existsSync, mkdirSync, appendFileSync, statSync, renameSync, unlinkSync } = require('node:fs')
const path = require('node:path')
const readline = require('node:readline')
const { safeExternal, localRequest, backendPort } = require('./policy.cjs')

app.setName('Deck')
app.setAppUserModelId('com.getwellsedge.deck')
if (process.platform === 'linux') app.setDesktopName('com.getwellsedge.deck.desktop')
app.enableSandbox()
const singleInstance = app.requestSingleInstanceLock()
let mainWindow, backend, quitting = false, stopping = false, updateReady = false
let updateTimer, quitAfterStop
const desktopToken = randomBytes(32).toString('hex')

function showFailure(message) {
  dialog.showErrorBox('Deck could not start', `${message}\n\nYour saved data has not been removed. Try opening Deck again.`)
}

function childEnvironment(database) {
  const env = { ...process.env }
  // A desktop build must not inherit development/hosted service configuration.
  for (const key of Object.keys(env)) {
    if (key.startsWith('DECK_') || key.startsWith('PYTHON') || key === 'ELECTRON_RUN_AS_NODE') delete env[key]
  }
  return { ...env, DECK_DESKTOP_TOKEN: desktopToken, DECK_DATABASE_PATH: database, DECK_DESKTOP_VERSION: app.getVersion(), PYTHONUNBUFFERED: '1' }
}

function log(message) {
  try {
    // Logs contain service errors only; never request bodies or session tokens.
    const file = path.join(app.getPath('userData'), 'desktop.log')
    if (existsSync(file) && statSync(file).size > 2 * 1024 * 1024) {
      if (existsSync(`${file}.old`)) unlinkSync(`${file}.old`)
      renameSync(file, `${file}.old`)
    }
    appendFileSync(file, `${new Date().toISOString()} ${String(message).replaceAll(desktopToken, '[redacted]')}\n`, { mode: 0o600 })
  } catch { /* A log failure must not prevent graceful shutdown. */ }
}

async function startBackend() {
  const root = path.resolve(__dirname, '..')
  const folder = path.join(app.getPath('userData'), 'data')
  mkdirSync(folder, { recursive: true, mode: 0o700 })
  const executable = app.isPackaged
    ? path.join(process.resourcesPath, 'backend', 'deck-service', process.platform === 'win32' ? 'deck-service.exe' : 'deck-service')
    : path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
  if (!existsSync(executable)) throw new Error('The bundled Deck service is missing. Reinstall Deck; your data stays in your user profile.')
  backend = spawn(executable, app.isPackaged ? [] : [path.join(root, 'desktop/backend_entry.py')], {
    env: childEnvironment(path.join(folder, 'deck.sqlite3')),
    stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
    cwd: app.isPackaged ? process.resourcesPath : root,
  })
  backend.stdin.on('error', () => {})
  backend.stderr.on('data', data => log(data.toString().slice(0, 8000)))
  backend.on('exit', () => {
    if (!quitting) {
      showFailure('The local data service stopped unexpectedly.')
      app.quit()
    }
  })
  const port = await new Promise((resolve, reject) => {
    const lines = readline.createInterface({ input: backend.stdout })
    const timeout = setTimeout(() => finish(new Error('The local data service took too long to start.')), 30000)
    const earlyExit = () => finish(new Error('The local data service exited during startup.'))
    const failed = () => finish(new Error('The local data service could not be launched.'))
    function finish(error, port) {
      clearTimeout(timeout); lines.close()
      backend.removeListener('exit', earlyExit); backend.removeListener('error', failed)
      if (error) reject(error); else resolve(port)
    }
    lines.on('line', line => { const port = backendPort(line); if (port) finish(null, port) })
    backend.once('exit', earlyExit); backend.once('error', failed)
  })
  const origin = `http://127.0.0.1:${port}`
  for (let attempt = 0; attempt < 100; attempt++) {
    if (backend.exitCode !== null) throw new Error('The local service stopped before it was ready.')
    try {
      const response = await fetch(`${origin}/api/health`, {
        headers: { 'X-Deck-Desktop-Token': desktopToken }, signal: AbortSignal.timeout(1000),
      })
      if (response.ok && (await response.json()).status === 'ok') return origin
    } catch { /* Retry while the schema and saved state initialize. */ }
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error('Deck could not open its local data. Check available disk space and try again.')
}

async function createWindow(origin) {
  // Ephemeral web session: database persists, browser credentials/caches do not.
  const browserSession = session.fromPartition(`deck-${randomBytes(8).toString('hex')}`)
  browserSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false))
  browserSession.setPermissionCheckHandler(() => false)
  browserSession.webRequest.onBeforeSendHeaders({ urls: [`${origin}/*`] }, (details, callback) => {
    callback({ requestHeaders: { ...details.requestHeaders, 'X-Deck-Desktop-Token': desktopToken } })
  })
  browserSession.webRequest.onHeadersReceived({ urls: [`${origin}/*`] }, (details, callback) => {
    callback({ responseHeaders: { ...details.responseHeaders,
      'Content-Security-Policy': ["default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' https://assets.kalshi.com data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-src 'none'; frame-ancestors 'none'; form-action 'self'"],
      'X-Content-Type-Options': ['nosniff'],
    } })
  })
  mainWindow = new BrowserWindow({
    width: 1440, height: 940, minWidth: 360, minHeight: 500, show: false,
    title: 'Deck', backgroundColor: '#101113',
    icon: path.join(__dirname, 'icons', 'deck.png'),
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), session: browserSession,
      nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true,
      webviewTag: false, devTools: !app.isPackaged, spellcheck: false },
  })
  const external = url => { if (safeExternal(url)) void shell.openExternal(url).catch(error => log(error.message)) }
  mainWindow.webContents.setWindowOpenHandler(({ url }) => { external(url); return { action: 'deny' } })
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!localRequest(url, origin)) { event.preventDefault(); external(url) }
  })
  mainWindow.webContents.on('will-attach-webview', event => event.preventDefault())
  mainWindow.on('closed', () => { mainWindow = null })
  mainWindow.once('ready-to-show', () => mainWindow.show())
  await mainWindow.loadURL(`${origin}/#games`)
}

async function stopBackend() {
  if (!backend || backend.exitCode !== null || backend.signalCode !== null) return
  await new Promise(resolve => {
    const timer = setTimeout(() => { backend.kill('SIGKILL'); resolve() }, 12000)
    backend.once('exit', () => { clearTimeout(timer); resolve() })
    backend.stdin.end()
  })
}

function installUpdate() {
  if (!updateReady || quitting) return
  quitAfterStop = () => require('electron-updater').autoUpdater.quitAndInstall(false, true)
  app.quit()
}

function configureUpdates() {
  const { autoUpdater } = require('electron-updater')
  // Local builds have no update configuration. AppImage is the supported Linux channel.
  const enabled = app.isPackaged && existsSync(path.join(process.resourcesPath, 'app-update.yml')) &&
    (process.platform !== 'linux' || Boolean(process.env.APPIMAGE))
  autoUpdater.autoDownload = true
  autoUpdater.autoInstallOnAppQuit = false
  autoUpdater.allowDowngrade = false
  autoUpdater.logger = { info: log, warn: log, error: log, debug: () => {} }
  autoUpdater.on('error', () => log('Update check failed; the installed version remains usable.'))
  async function offerInstall() {
    if (!mainWindow || quitting) return
    const result = await dialog.showMessageBox(mainWindow, { type: 'info', title: 'Deck update ready',
      message: 'A new version of Deck is ready.', detail: 'Save any edits before restarting. Your saved records will be kept.',
      buttons: ['Later', 'Restart and install'], defaultId: 0, cancelId: 0 })
    if (result.response === 1) installUpdate()
  }
  autoUpdater.on('update-downloaded', () => { updateReady = true; void offerInstall() })
  async function check(manual = false) {
    if (!enabled) {
      if (manual) await dialog.showMessageBox({ message: 'Updates are available in release installations.',
        detail: 'This build is for local testing. Install a released Windows, Mac, or Linux AppImage build to receive updates.' })
      return
    }
    if (updateReady && manual) { await offerInstall(); return }
    try {
      const result = await autoUpdater.checkForUpdates()
      if (manual && result && !result.isUpdateAvailable) await dialog.showMessageBox({ message: 'Deck is up to date.' })
    } catch {
      if (manual) await dialog.showMessageBox({ type: 'warning', message: 'Deck could not check for updates.',
        detail: 'Check your connection and try again later. Your installed app remains available.' })
    }
  }
  const template = [
    ...(process.platform === 'darwin' ? [{ label: 'Deck', submenu: [{ role: 'about' }, { type: 'separator' }, { role: 'quit' }] }] : []),
    { label: 'File', submenu: [{ label: 'Open data folder', click: () => { void shell.openPath(path.join(app.getPath('userData'), 'data')) } }, { type: 'separator' }, { role: 'quit' }] },
    { role: 'editMenu' },
    { label: 'View', submenu: [{ role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'togglefullscreen' }] },
    { label: 'Help', submenu: [{ label: 'Check for updates…', click: () => { void check(true) } },
      { label: 'About Deck', click: () => { void dialog.showMessageBox({ message: `Deck ${app.getVersion()}`, detail: 'Your NFL research, watchlist, and tracker. Saved locally on this computer.' }) } }] },
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
  if (enabled) {
    setTimeout(() => { void check() }, 15000).unref()
    updateTimer = setInterval(() => { void check() }, 4 * 60 * 60 * 1000)
    updateTimer.unref()
  }
}

if (!singleInstance) {
  app.quit()
} else {
  app.on('second-instance', () => { if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus() } })
  app.on('window-all-closed', () => app.quit())
  app.on('before-quit', event => {
    if (stopping) return
    event.preventDefault()
    if (quitting) return
    quitting = true
    clearInterval(updateTimer)
    void stopBackend().finally(() => {
      stopping = true
      if (quitAfterStop) {
        quitAfterStop()
        // If the installer cannot launch, do not leave an app with a stopped service.
        setTimeout(() => app.quit(), 3000).unref()
      } else app.quit()
    })
  })
  void app.whenReady().then(async () => {
    const origin = await startBackend()
    if (quitting) return
    await createWindow(origin)
    configureUpdates()
  }).catch(error => { log(error.message); if (!quitting) showFailure(error.message); app.quit() })
}
