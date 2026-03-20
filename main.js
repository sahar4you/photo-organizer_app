// Ready to use – PhotoOrganizer Electron Main Process
const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    title: 'Photo Organizer',
    backgroundColor: '#121212',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile('renderer/index.html');
  mainWindow.setMenuBarVisibility(false);
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });

// ---- IPC Handlers ----

// Pick folder
ipcMain.handle('pick-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'Select Photo Folder',
  });
  return result.canceled ? null : result.filePaths[0];
});

// Scan folder — runs Python scanner as child process
ipcMain.handle('scan-folder', async (event, folderPath) => {
  return new Promise((resolve, reject) => {
    const scriptPath = getScriptPath();
    const proc = spawn('python3', [scriptPath, folderPath, '--json'], {
      cwd: folderPath,
    });

    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', (data) => {
      stdout += data.toString();
      // Forward progress to renderer
      const lines = data.toString().split('\n');
      lines.forEach((line) => {
        if (line.includes('Scanning:')) {
          mainWindow.webContents.send('scan-progress', line.trim());
        }
      });
    });

    proc.stderr.on('data', (data) => { stderr += data.toString(); });

    proc.on('close', (code) => {
      if (code !== 0) {
        reject(new Error(`Scanner exited with code ${code}: ${stderr}`));
        return;
      }
      try {
        // Extract JSON from stdout (last JSON block)
        const jsonMatch = stdout.match(/\{[\s\S]*\}(?=[^}]*$)/);
        if (jsonMatch) {
          resolve(JSON.parse(jsonMatch[0]));
        } else {
          reject(new Error('No JSON output from scanner'));
        }
      } catch (e) {
        reject(new Error(`JSON parse error: ${e.message}`));
      }
    });
  });
});

// Save face_names.json directly to folder
ipcMain.handle('save-face-names', async (event, folderPath, nameMap) => {
  const filePath = path.join(folderPath, 'face_names.json');
  // MODIFIED: Merge with existing mappings if file exists
  let existing = {};
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    existing = JSON.parse(raw);
  } catch (_) {}
  const merged = { ...existing, ...nameMap };
  fs.writeFileSync(filePath, JSON.stringify(merged, null, 2), 'utf8');
  return filePath;
});

// Load face_names.json from folder
ipcMain.handle('load-face-names', async (event, folderPath) => {
  const filePath = path.join(folderPath, 'face_names.json');
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    return JSON.parse(raw);
  } catch (_) {
    return {};
  }
});

// Read image file as base64 (for lightbox)
ipcMain.handle('read-image', async (event, filePath) => {
  try {
    const buf = fs.readFileSync(filePath);
    const ext = path.extname(filePath).toLowerCase();
    const mime = ext === '.png' ? 'image/png' : ext === '.gif' ? 'image/gif' : 'image/jpeg';
    return `data:${mime};base64,${buf.toString('base64')}`;
  } catch (_) {
    return null;
  }
});

function getScriptPath() {
  // In dev: same directory; in packaged: extraResources
  const devPath = path.join(__dirname, 'python_scanner', 'scanner.py');
  const prodPath = path.join(process.resourcesPath, 'python_scanner', 'scanner.py');
  return fs.existsSync(devPath) ? devPath : prodPath;
}
