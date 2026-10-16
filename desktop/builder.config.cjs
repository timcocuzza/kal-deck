'use strict'
const path = require('node:path')

const production = process.env.DECK_RELEASE === '1'
const owner = process.env.DECK_RELEASE_OWNER
const repo = process.env.DECK_RELEASE_REPO
if (production && (!/^[A-Za-z0-9][A-Za-z0-9-]*$/.test(owner || '') || !/^[A-Za-z0-9_.-]+$/.test(repo || ''))) {
  throw new Error('A production release requires DECK_RELEASE_OWNER and DECK_RELEASE_REPO.')
}
if (production && process.platform === 'win32' && !process.env.DECK_WINDOWS_PUBLISHER) {
  throw new Error('Set DECK_WINDOWS_PUBLISHER to the exact signing certificate publisher.')
}
const azureSigning = Boolean(process.env.DECK_AZURE_SIGNING_ACCOUNT)
if (production && process.platform === 'win32' && azureSigning &&
    (!process.env.DECK_AZURE_SIGNING_ENDPOINT || !process.env.DECK_AZURE_SIGNING_PROFILE)) {
  throw new Error('Azure signing requires an endpoint and certificate profile.')
}
const windowsSigning = !production ? {} : azureSigning ? {
  azureSignOptions: {
    publisherName: process.env.DECK_WINDOWS_PUBLISHER,
    endpoint: process.env.DECK_AZURE_SIGNING_ENDPOINT,
    certificateProfileName: process.env.DECK_AZURE_SIGNING_PROFILE,
    codeSigningAccountName: process.env.DECK_AZURE_SIGNING_ACCOUNT,
  },
} : { signtoolOptions: { publisherName: process.env.DECK_WINDOWS_PUBLISHER } }
module.exports = {
  appId: 'com.getwellsedge.deck', productName: 'Deck',
  directories: { output: 'release/desktop', buildResources: 'desktop/icons' },
  artifactName: 'Deck-${version}-${os}-${arch}.${ext}',
  files: ['desktop/*.cjs', 'desktop/icons/deck.png', 'package.json', '!desktop/builder.config.cjs'],
  extraResources: [{ from: 'build/desktop/backend/deck-service', to: 'backend/deck-service' }],
  asar: true, npmRebuild: false,
  // Extra resources are outside builder's normal Windows executable-signing walk.
  afterSign: async context => {
    if (production && context.electronPlatformName === 'win32') {
      await context.packager.signIf(path.join(context.appOutDir, 'resources', 'backend', 'deck-service', 'deck-service.exe'))
    }
  },
  electronFuses: { runAsNode: false, enableNodeOptionsEnvironmentVariable: false,
    enableNodeCliInspectArguments: false, onlyLoadAppFromAsar: true,
    enableEmbeddedAsarIntegrityValidation: process.platform !== 'linux',
    grantFileProtocolExtraPrivileges: false },
  forceCodeSigning: production && process.platform !== 'linux',
  publish: production ? [{ provider: 'github', owner, repo, releaseType: 'draft' }] : null,
  win: { target: ['nsis'], icon: 'desktop/icons/deck.ico',
    verifyUpdateCodeSignature: true,
    ...windowsSigning },
  nsis: { oneClick: false, perMachine: false, allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true, createStartMenuShortcut: true, deleteAppDataOnUninstall: false },
  mac: { target: ['dmg', 'zip'], icon: 'desktop/icons/deck.icns', category: 'public.app-category.sports',
    hardenedRuntime: true, notarize: production,
    entitlements: 'desktop/entitlements.mac.plist', entitlementsInherit: 'desktop/entitlements.mac.plist' },
  linux: { target: ['AppImage'], icon: 'desktop/icons/deck.png', category: 'Office', syncDesktopName: true,
    desktop: { entry: { Name: 'Deck', Comment: 'Your personal NFL research workspace', StartupWMClass: 'Deck' } } },
}
