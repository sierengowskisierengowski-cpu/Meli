// Meli Electron shell — borderless window pointing at the local FastAPI server.
// Launched by the `meli-web --native` Python CLI, which sets MELI_WEB_URL.

const { app, BrowserWindow, shell } = require("electron");

const URL = process.env.MELI_WEB_URL || "http://127.0.0.1:17655/";

function createWindow() {
  const win = new BrowserWindow({
    width: 1600,
    height: 1000,
    minWidth: 1200,
    minHeight: 800,
    backgroundColor: "#06060a",
    autoHideMenuBar: true,
    title: "Meli — Hive Command Center",
    icon: undefined,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  win.removeMenu();
  win.loadURL(URL);

  // External links open in the user's real browser, not inside Electron.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(URL)) {
      shell.openExternal(url);
      return { action: "deny" };
    }
    return { action: "allow" };
  });
}

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
