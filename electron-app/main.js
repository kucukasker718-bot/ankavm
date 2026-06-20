'use strict';

const {
  app, BrowserWindow, Tray, Menu, ipcMain,
  nativeImage, shell, dialog, Notification,
} = require('electron');
const { autoUpdater } = require('electron-updater');
const path = require('path');
const fs   = require('fs');

// ─── Constants ────────────────────────────────────────────────────────────────
const APP_NAME    = 'ANKAVM';
const CONFIG_FILE = path.join(app.getPath('userData'), 'servers.json');
const CONNECT_URL = `file://${path.join(__dirname, 'connect.html')}`;

// ─── State ────────────────────────────────────────────────────────────────────
let mainWindow    = null;
let tray          = null;
let servers       = [];          // [{ url, label }]
let activeUrl     = null;        // null = no server configured yet

// ─── Config ───────────────────────────────────────────────────────────────────
function loadConfig() {
  try {
    if (fs.existsSync(CONFIG_FILE)) {
      const d = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));
      servers   = Array.isArray(d.servers) ? d.servers : [];
      activeUrl = d.activeUrl && servers.find((s) => s.url === d.activeUrl)
        ? d.activeUrl
        : (servers[0]?.url || null);
    }
  } catch (_) {
    servers   = [];
    activeUrl = null;
  }
}

function saveConfig() {
  try {
    fs.writeFileSync(CONFIG_FILE, JSON.stringify({ servers, activeUrl }, null, 2), 'utf8');
  } catch (_) { /* ignore */ }
}

// ─── Icons ────────────────────────────────────────────────────────────────────
function getAppIcon() {
  const base = path.join(__dirname, 'build', 'icons');
  if (process.platform === 'win32')  return path.join(base, 'icon.ico');
  if (process.platform === 'darwin') return path.join(base, 'icon.icns');
  return path.join(base, 'icon.png');
}

function getTrayIcon() {
  const base = path.join(__dirname, 'build', 'icons');
  const file = process.platform === 'darwin'
    ? path.join(base, 'trayTemplate.png')   // 16x16@2x black template image
    : process.platform === 'win32'
      ? path.join(base, 'tray.ico')
      : path.join(base, 'tray.png');
  try {
    const img = nativeImage.createFromPath(file);
    return img.isEmpty() ? nativeImage.createEmpty() : img;
  } catch (_) {
    return nativeImage.createEmpty();
  }
}

// ─── Window ───────────────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width:           1280,
    height:          820,
    minWidth:        900,
    minHeight:       600,
    title:           APP_NAME,
    backgroundColor: '#0d1117',
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
      // Allow self-signed TLS — ANKAVM uses a self-signed cert by default
      webSecurity:      false,
    },
    icon:  getAppIcon(),
    show:  false,
  });

  // Load connection screen if no server is configured yet; otherwise load the active server
  mainWindow.loadURL(activeUrl || CONNECT_URL);

  mainWindow.once('ready-to-show', () => mainWindow.show());

  // If server URL fails to load (unreachable / wrong address), fall back to connect screen
  mainWindow.webContents.on('did-fail-load', (_e, errCode, _errDesc, failedUrl) => {
    // Ignore in-page navigation failures and the connect page itself
    if (!failedUrl || failedUrl === CONNECT_URL || failedUrl.startsWith('file://')) return;
    // -3 = ABORTED (user navigation / reload) — ignore
    if (errCode === -3) return;
    mainWindow.loadURL(CONNECT_URL);
  });

  // Intercept certificate errors from self-signed ANKAVM TLS
  mainWindow.webContents.on('certificate-error', (event, _url, _err, _cert, callback) => {
    event.preventDefault();
    callback(true);   // trust self-signed cert
  });

  // Open external links (GitHub, Discord, etc.) in system browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  // Minimise to tray on close
  mainWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ─── Tray ─────────────────────────────────────────────────────────────────────
function createTray() {
  tray = new Tray(getTrayIcon());
  tray.setToolTip(APP_NAME);
  rebuildTrayMenu();
  tray.on('double-click', showWindow);
}

function rebuildTrayMenu() {
  const serverItems = servers.length
    ? servers.map((s) => ({
        label:   s.label || s.url,
        type:    'radio',
        checked: s.url === activeUrl,
        click:   () => switchServer(s.url),
      }))
    : [{ label: 'No servers configured', enabled: false }];

  const menu = Menu.buildFromTemplate([
    { label: `${APP_NAME} Desktop  v${app.getVersion()}`, enabled: false },
    { type: 'separator' },
    { label: 'Show Panel',  click: showWindow },
    { label: 'Reload',      click: () => mainWindow && mainWindow.webContents.reload() },
    { type: 'separator' },
    {
      label: 'Servers',
      submenu: [
        ...serverItems,
        { type: 'separator' },
        { label: 'Add Server…',          click: promptAddServer   },
        { label: 'Remove Active Server', click: removeActiveServer },
      ],
    },
    { type: 'separator' },
    { label: 'Check for Updates', click: () => autoUpdater.checkForUpdatesAndNotify().catch(() => {}) },
    { label: 'Open Config Folder', click: () => shell.openPath(app.getPath('userData')) },
    { type: 'separator' },
    { label: `Quit ${APP_NAME}`, click: () => { app.isQuitting = true; app.quit(); } },
  ]);

  tray.setContextMenu(menu);
}

function showWindow() {
  if (!mainWindow) {
    createWindow();
  } else {
    mainWindow.show();
    mainWindow.focus();
  }
}

// ─── Server management ────────────────────────────────────────────────────────
function switchServer(url) {
  activeUrl = url;
  saveConfig();
  rebuildTrayMenu();
  if (mainWindow) mainWindow.loadURL(url);
}

function promptAddServer() {
  showWindow();
  if (mainWindow) mainWindow.loadURL(CONNECT_URL);
}

function removeActiveServer() {
  servers = servers.filter((s) => s.url !== activeUrl);
  if (servers.length > 0) {
    activeUrl = servers[0].url;
    if (mainWindow) mainWindow.loadURL(activeUrl);
  } else {
    activeUrl = null;
    if (mainWindow) mainWindow.loadURL(CONNECT_URL);
  }
  saveConfig();
  rebuildTrayMenu();
}

// ─── IPC handlers ─────────────────────────────────────────────────────────────
ipcMain.handle('get-servers',    ()           => servers);
ipcMain.handle('get-active-url', ()           => activeUrl);
ipcMain.handle('get-version',    ()           => app.getVersion());

ipcMain.handle('add-server', (_e, { url, label }) => {
  if (!url)                                   return { ok: false, reason: 'no url' };
  if (servers.find((s) => s.url === url))     return { ok: false, reason: 'duplicate' };
  servers.push({ url, label: label || url });
  activeUrl = url;
  saveConfig();
  rebuildTrayMenu();
  if (mainWindow) mainWindow.loadURL(url);
  return { ok: true };
});

ipcMain.handle('remove-server', (_e, url) => {
  servers = servers.filter((s) => s.url !== url);
  if (activeUrl === url) {
    activeUrl = servers[0]?.url || null;
    if (mainWindow) mainWindow.loadURL(activeUrl || CONNECT_URL);
  }
  saveConfig();
  rebuildTrayMenu();
  return { ok: true };
});

ipcMain.handle('switch-server', (_e, url) => {
  switchServer(url);
  return { ok: true };
});

ipcMain.on('show-notification', (_e, { title, body }) => {
  if (Notification.isSupported()) {
    new Notification({ title: title || APP_NAME, body, icon: getAppIcon() }).show();
  }
});

// ─── Auto-updater ─────────────────────────────────────────────────────────────
function setupAutoUpdater() {
  autoUpdater.autoDownload  = false;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.logger = { info: () => {}, warn: () => {}, error: console.error };

  autoUpdater.on('update-available', (info) => {
    if (mainWindow) mainWindow.webContents.send('update-available', info);

    dialog.showMessageBox(mainWindow || undefined, {
      type:    'info',
      title:   'Update Available',
      message: `ANKAVM Desktop ${info.version} is ready to download.`,
      detail:  'The update will be installed on next restart.',
      buttons: ['Download & Install', 'Later'],
    }).then(({ response }) => {
      if (response === 0) autoUpdater.downloadUpdate();
    }).catch(() => {});
  });

  autoUpdater.on('update-downloaded', () => {
    dialog.showMessageBox(mainWindow || undefined, {
      type:    'info',
      title:   'Ready to Update',
      message: 'ANKAVM Desktop will restart to apply the update.',
      buttons: ['Restart Now', 'Later'],
    }).then(({ response }) => {
      if (response === 0) { app.isQuitting = true; autoUpdater.quitAndInstall(); }
    }).catch(() => {});
  });

  autoUpdater.on('error', () => { /* silent — dev builds have no update server */ });

  // Check 5 s after launch
  setTimeout(() => {
    autoUpdater.checkForUpdatesAndNotify().catch(() => {});
  }, 5000);
}

// ─── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(() => {
  loadConfig();
  // Do NOT push a default URL — if servers is empty, connect.html will show.

  createWindow();
  createTray();
  setupAutoUpdater();

  app.on('activate', () => {
    // macOS: re-open window when dock icon is clicked
    if (!mainWindow) createWindow();
    else mainWindow.show();
  });
});

app.on('window-all-closed', () => {
  // Keep running in tray on all platforms — don't quit on window close
});

app.on('before-quit', () => {
  app.isQuitting = true;
});






