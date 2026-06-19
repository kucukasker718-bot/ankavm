'use strict';

const { contextBridge, ipcRenderer } = require('electron');

// Expose a narrow, typed API to the renderer (ANKAVM web UI).
// window.ankavmDesktop is available inside the BrowserWindow.
contextBridge.exposeInMainWorld('ankavmDesktop', {
  // â”€â”€ Server management â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  getServers:    ()             => ipcRenderer.invoke('get-servers'),
  getActiveUrl:  ()             => ipcRenderer.invoke('get-active-url'),
  addServer:     (url, label)   => ipcRenderer.invoke('add-server',    { url, label }),
  removeServer:  (url)          => ipcRenderer.invoke('remove-server', url),
  switchServer:  (url)          => ipcRenderer.invoke('switch-server', url),

  // â”€â”€ App info â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  getVersion:    ()             => ipcRenderer.invoke('get-version'),

  // â”€â”€ Native notifications â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  notify:        (title, body)  => ipcRenderer.send('show-notification', { title, body }),

  // â”€â”€ Incoming events from main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  onAddServer:       (cb) => ipcRenderer.on('open-add-server',   (_e)       => cb()),
  onUpdateAvailable: (cb) => ipcRenderer.on('update-available',  (_e, info) => cb(info)),
});






