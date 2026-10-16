'use strict'
const { contextBridge } = require('electron')
// A display-only flag. No filesystem, process, token or IPC access in the renderer.
contextBridge.exposeInMainWorld('deckDesktop', Object.freeze({ enabled: true }))
