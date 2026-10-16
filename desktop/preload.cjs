'use strict'
const { contextBridge, ipcRenderer } = require('electron')
// Fixed operations only. No filesystem, process, token, generic IPC or arguments.
contextBridge.exposeInMainWorld('deckDesktop', Object.freeze({ enabled: true,
  getUpdateState: () => ipcRenderer.invoke('deck:update-state'),
  update: () => ipcRenderer.invoke('deck:update'),
  restart: () => ipcRenderer.invoke('deck:restart'),
  onUpdate: callback => {
    const listener = (_event, value) => callback(value)
    ipcRenderer.on('deck:update-state', listener)
    return () => ipcRenderer.removeListener('deck:update-state', listener)
  },
}))
