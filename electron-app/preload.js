'use strict';

const { contextBridge, ipcRenderer } = require('electron');

// Expose a narrow, typed API to the renderer (ANKAVM web UI).
// window.ankavmDesktop is available inside the BrowserWindow.
contextBridge.exposeInMainWorld('ankavmDesktop', {
  // ── Server management ───────────────────────────────────────────────────────
  getServers:    ()             => ipcRenderer.invoke('get-servers'),
  getActiveUrl:  ()             => ipcRenderer.invoke('get-active-url'),
  addServer:     (url, label)   => ipcRenderer.invoke('add-server',    { url, label }),
  removeServer:  (url)          => ipcRenderer.invoke('remove-server', url),
  switchServer:  (url)          => ipcRenderer.invoke('switch-server', url),

  // ── App info ─────────────────────────────────────────────────────────────────
  getVersion:    ()             => ipcRenderer.invoke('get-version'),

  // ── Native notifications ─────────────────────────────────────────────────────
  notify:        (title, body)  => ipcRenderer.send('show-notification', { title, body }),

  // ── Incoming events from main ─────────────────────────────────────────────────
  onAddServer:       (cb) => ipcRenderer.on('open-add-server',   (_e)       => cb()),
  onUpdateAvailable: (cb) => ipcRenderer.on('update-available',  (_e, info) => cb(info)),
});






