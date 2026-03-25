// Ready to use – PhotoOrganizer Electron Main Process
const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
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

// ---- Dev vs Production detection ----

function isDev() {
  return !app.isPackaged;
}

function getScannerCommand(folderPath, extraArgs) {
  const args = [folderPath, '--json', ...extraArgs];

  if (isDev()) {
    // Dev mode: use system Python + script
    const scriptPath = path.join(__dirname, 'python_scanner', 'scanner.py');
    const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';
    return { cmd: pythonCmd, args: [scriptPath, ...args], cwd: path.join(__dirname, 'python_scanner') };
  }

  // Production: use bundled scanner executable
  const exeName = process.platform === 'win32' ? 'scanner.exe' : 'scanner';
  const exePath = path.join(process.resourcesPath, 'python_bin', exeName);

  if (!fs.existsSync(exePath)) {
    throw new Error(
      `Scanner executable not found at: ${exePath}\n` +
      'The portable build may be incomplete. Please rebuild with BUILD-PORTABLE.bat.'
    );
  }

  return { cmd: exePath, args, cwd: path.dirname(exePath) };
}

function spawnScanner(folderPath, extraArgs, progressFilter) {
  return new Promise((resolve, reject) => {
    let scannerInfo;
    try {
      scannerInfo = getScannerCommand(folderPath, extraArgs);
    } catch (e) {
      reject(e);
      return;
    }

    const proc = spawn(scannerInfo.cmd, scannerInfo.args, { cwd: scannerInfo.cwd });

    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', (data) => {
      stdout += data.toString();
      const lines = data.toString().split('\n');
      lines.forEach((line) => {
        if (progressFilter(line)) {
          mainWindow.webContents.send('scan-progress', line.trim());
        }
      });
    });

    proc.stderr.on('data', (data) => { stderr += data.toString(); });

    proc.on('error', (err) => {
      if (err.code === 'ENOENT') {
        const hint = isDev()
          ? 'Python not found. Install Python 3.8+ and ensure it is on your PATH.'
          : 'Scanner executable not found. Please rebuild with BUILD-PORTABLE.bat.';
        reject(new Error(hint));
      } else {
        reject(err);
      }
    });

    proc.on('close', (code) => {
      if (code !== 0) {
        reject(new Error(`Scanner exited with code ${code}: ${stderr}`));
        return;
      }
      try {
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
}

// ---- IPC Handlers ----

// Pick folder
ipcMain.handle('pick-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'Select Photo Folder',
  });
  return result.canceled ? null : result.filePaths[0];
});

// Scan folder — uses bundled EXE in production, Python in dev
ipcMain.handle('scan-folder', async (event, folderPath) => {
  return spawnScanner(folderPath, [], (line) => line.includes('Scanning:'));
});

// Move duplicates — re-runs scanner with --move-duplicates flag
ipcMain.handle('move-duplicates', async (event, folderPath) => {
  return spawnScanner(folderPath, ['--move-duplicates'], (line) =>
    line.includes('Scanning:') || line.includes('Detecting') || line.includes('Moving')
  );
});

// Save face_names.json directly to folder
ipcMain.handle('save-face-names', async (event, folderPath, nameMap) => {
  const filePath = path.join(folderPath, 'face_names.json');
  // Merge with existing mappings if file exists
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

// Trash duplicate files (send to recycle bin)
ipcMain.handle('trash-files', async (event, filePaths) => {
  const results = [];
  for (const fp of filePaths) {
    try {
      await shell.trashItem(fp);
      results.push({ path: fp, status: 'trashed' });
    } catch (e) {
      results.push({ path: fp, status: 'error', message: e.message });
    }
  }
  return results;
});

// Save ignored duplicate groups to folder
ipcMain.handle('save-ignored-groups', async (event, folderPath, ignoredGroups) => {
  const filePath = path.join(folderPath, 'ignored_duplicates.json');
  fs.writeFileSync(filePath, JSON.stringify(ignoredGroups, null, 2), 'utf8');
  return filePath;
});

// Load ignored duplicate groups from folder
ipcMain.handle('load-ignored-groups', async (event, folderPath) => {
  const filePath = path.join(folderPath, 'ignored_duplicates.json');
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    return JSON.parse(raw);
  } catch (_) {
    return [];
  }
});

// Save photo tags to folder
ipcMain.handle('save-tags', async (event, folderPath, tagsMap) => {
  const filePath = path.join(folderPath, 'photo_tags.json');
  fs.writeFileSync(filePath, JSON.stringify(tagsMap, null, 2), 'utf8');
  return filePath;
});

// Load photo tags from folder
ipcMain.handle('load-tags', async (event, folderPath) => {
  const filePath = path.join(folderPath, 'photo_tags.json');
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    return JSON.parse(raw);
  } catch (_) {
    return {};
  }
});

// Move files by tag to a subfolder
ipcMain.handle('move-tagged-files', async (event, folderPath, relPaths, targetSubfolder) => {
  const results = [];
  const targetDir = path.join(folderPath, targetSubfolder);
  if (!fs.existsSync(targetDir)) {
    fs.mkdirSync(targetDir, { recursive: true });
  }
  for (const rel of relPaths) {
    const src = path.join(folderPath, rel);
    const destDir = path.join(targetDir, path.dirname(rel));
    if (!fs.existsSync(destDir)) {
      fs.mkdirSync(destDir, { recursive: true });
    }
    let dest = path.join(destDir, path.basename(rel));
    // Handle name collisions
    if (fs.existsSync(dest)) {
      const ext = path.extname(rel);
      const stem = path.basename(rel, ext);
      let counter = 2;
      while (fs.existsSync(dest)) {
        dest = path.join(destDir, `${stem}_${counter}${ext}`);
        counter++;
      }
    }
    try {
      fs.renameSync(src, dest);
      results.push({ source: rel, destination: path.relative(folderPath, dest), status: 'moved' });
    } catch (e) {
      results.push({ source: rel, destination: '', status: 'error', message: e.message });
    }
  }
  return results;
});
