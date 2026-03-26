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

function spawnScanner(folderPath, extraArgs) {
  return new Promise((resolve, reject) => {
    let scannerInfo;
    try {
      scannerInfo = getScannerCommand(folderPath, extraArgs);
    } catch (e) {
      reject(e);
      return;
    }

    const proc = spawn(scannerInfo.cmd, scannerInfo.args, { cwd: scannerInfo.cwd });

    let buffer = '';
    let resultData = null;
    let stderr = '';

    // Line-delimited JSON parser — every stdout line is valid JSON
    proc.stdout.on('data', (data) => {
      buffer += data.toString();
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete last line in buffer
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          const msg = JSON.parse(trimmed);
          if (msg.type === 'progress') {
            mainWindow.webContents.send('scan-progress-json', msg);
          } else if (msg.type === 'result') {
            resultData = msg.data;
          } else if (msg.type === 'error') {
            reject(new Error(msg.message));
          }
        } catch (_) {
          // Ignore non-JSON lines (shouldn't happen but safe fallback)
        }
      }
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
      // Process any remaining buffer
      if (buffer.trim()) {
        try {
          const msg = JSON.parse(buffer.trim());
          if (msg.type === 'result') resultData = msg.data;
          else if (msg.type === 'error') { reject(new Error(msg.message)); return; }
        } catch (_) {}
      }
      if (code !== 0) {
        reject(new Error(`Scanner exited with code ${code}: ${stderr}`));
        return;
      }
      if (resultData) {
        resolve(resultData);
      } else {
        reject(new Error('No result received from scanner'));
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
  const result = await spawnScanner(folderPath, []);
  // Set .cache folder as hidden on Windows
  hideCacheFolder(folderPath);
  return result;
});

function hideCacheFolder(folderPath) {
  if (process.platform !== 'win32') return;
  const cacheDir = path.join(folderPath, '.cache');
  if (fs.existsSync(cacheDir)) {
    try {
      const { execSync } = require('child_process');
      execSync(`attrib +h "${cacheDir}"`, { stdio: 'ignore' });
    } catch (_) {}
  }
}

// ---- JSON storage in .cache/data/ ----
function getDataPath(folderPath, filename) {
  const dataDir = path.join(folderPath, '.cache', 'data');
  if (!fs.existsSync(dataDir)) fs.mkdirSync(dataDir, { recursive: true });
  const newPath = path.join(dataDir, filename);
  // Auto-migrate from root if old file exists and new doesn't
  const oldPath = path.join(folderPath, filename);
  if (!fs.existsSync(newPath) && fs.existsSync(oldPath)) {
    try {
      fs.renameSync(oldPath, newPath);
    } catch (_) {
      // If rename fails (cross-device), copy + delete
      try { fs.copyFileSync(oldPath, newPath); fs.unlinkSync(oldPath); } catch (_2) {}
    }
  }
  return newPath;
}

// Validate folder exists
ipcMain.handle('validate-folder', async (event, folderPath) => {
  return fs.existsSync(folderPath) && fs.statSync(folderPath).isDirectory();
});

// Move duplicates — re-runs scanner with --move-duplicates flag
ipcMain.handle('move-duplicates', async (event, folderPath) => {
  return spawnScanner(folderPath, ['--move-duplicates']);
});

// Save face_names.json
ipcMain.handle('save-face-names', async (event, folderPath, nameMap) => {
  const filePath = getDataPath(folderPath, 'face_names.json');
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
  const filePath = getDataPath(folderPath, 'face_names.json');
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
    // Normalize and ensure absolute path
    const absPath = path.resolve(fp);
    // Verify file exists before trashing
    if (!fs.existsSync(absPath)) {
      results.push({ path: fp, status: 'error', message: 'File not found' });
      continue;
    }
    try {
      await shell.trashItem(absPath);
      results.push({ path: fp, status: 'trashed' });
    } catch (e) {
      results.push({ path: fp, status: 'error', message: e.message });
    }
  }
  return results;
});

// Save ignored duplicate groups to folder
ipcMain.handle('save-ignored-groups', async (event, folderPath, ignoredGroups) => {
  const filePath = getDataPath(folderPath, 'ignored_duplicates.json');
  fs.writeFileSync(filePath, JSON.stringify(ignoredGroups, null, 2), 'utf8');
  return filePath;
});

// Load ignored duplicate groups from folder
ipcMain.handle('load-ignored-groups', async (event, folderPath) => {
  const filePath = getDataPath(folderPath, 'ignored_duplicates.json');
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    return JSON.parse(raw);
  } catch (_) {
    return [];
  }
});

// Save photo tags to folder
ipcMain.handle('save-tags', async (event, folderPath, tagsMap) => {
  const filePath = getDataPath(folderPath, 'photo_tags.json');
  fs.writeFileSync(filePath, JSON.stringify(tagsMap, null, 2), 'utf8');
  return filePath;
});

// Load photo tags from folder
ipcMain.handle('load-tags', async (event, folderPath) => {
  const filePath = getDataPath(folderPath, 'photo_tags.json');
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

// Export selected files to Exported/<subfolder>/
ipcMain.handle('export-files', async (event, folderPath, relPaths, subfolder, preserveStructure) => {
  const results = [];
  const exportDir = path.join(folderPath, 'Exported', subfolder);
  for (const rel of relPaths) {
    const src = path.join(folderPath, rel);
    const destDir = preserveStructure
      ? path.join(exportDir, path.dirname(rel))
      : exportDir;
    if (!fs.existsSync(destDir)) {
      fs.mkdirSync(destDir, { recursive: true });
    }
    let dest = path.join(destDir, path.basename(rel));
    if (fs.existsSync(dest)) {
      const ext = path.extname(rel);
      const stem = path.basename(rel, ext);
      let counter = 1;
      while (fs.existsSync(dest)) {
        dest = path.join(destDir, `${stem}_${counter}${ext}`);
        counter++;
      }
    }
    try {
      fs.copyFileSync(src, dest);
      results.push({ source: rel, destination: path.relative(folderPath, dest), status: 'exported' });
    } catch (e) {
      results.push({ source: rel, destination: '', status: 'error', message: e.message });
    }
  }
  return { results, exportPath: exportDir };
});

// Clear cache (hash_cache.json + .cache/thumbnails/)
ipcMain.handle('clear-cache', async (event, folderPath) => {
  const removed = [];
  // Clear hash_cache from both old and new locations
  for (const loc of [path.join(folderPath, 'hash_cache.json'), path.join(folderPath, '.cache', 'data', 'hash_cache.json')]) {
    if (fs.existsSync(loc)) {
      try { fs.unlinkSync(loc); removed.push('hash_cache.json'); } catch (_) {}
    }
  }
  const thumbDir = path.join(folderPath, '.cache', 'thumbnails');
  if (fs.existsSync(thumbDir)) {
    try { fs.rmSync(thumbDir, { recursive: true, force: true }); removed.push('.cache/thumbnails/'); } catch (_) {}
  }
  return removed;
});

// ---- Thumbnail generation with concurrency control + LRU cache ----

const CACHE_MAX_BYTES = 500 * 1024 * 1024; // 500MB
const THUMB_MAX_CONCURRENT = 4;
const THUMB_SIZES = [150, 200, 300]; // known thumbnail widths

// Concurrency queue state
let thumbActive = 0;
const thumbQueue = [];             // FIFO queue of { resolve, reject, args }
const thumbInProgress = new Map(); // key -> Promise (dedup in-flight requests)

function thumbCacheKey(folderPath, relPath, size) {
  return `${folderPath}|${relPath}|${size}`;
}

function processThumbQueue() {
  while (thumbActive < THUMB_MAX_CONCURRENT && thumbQueue.length > 0) {
    const task = thumbQueue.shift();
    thumbActive++;
    doGenerateThumbnail(...task.args)
      .then(task.resolve)
      .catch(task.reject)
      .finally(() => {
        thumbActive--;
        const key = thumbCacheKey(...task.args);
        thumbInProgress.delete(key);
        processThumbQueue();
      });
  }
}

ipcMain.handle('generate-thumbnail', async (event, folderPath, relPath, size) => {
  const key = thumbCacheKey(folderPath, relPath, size);
  // Dedup: reuse in-flight promise for same request
  if (thumbInProgress.has(key)) {
    return thumbInProgress.get(key);
  }
  const promise = new Promise((resolve, reject) => {
    thumbQueue.push({ resolve, reject, args: [folderPath, relPath, size] });
    processThumbQueue();
  });
  thumbInProgress.set(key, promise);
  return promise;
});

async function doGenerateThumbnail(folderPath, relPath, size) {
  const thumbWidth = size || 200;
  const thumbsDir = path.join(folderPath, '.cache', 'thumbnails', String(thumbWidth));
  const thumbRel = relPath.replace(/\.[^.]+$/, '.jpg');
  const thumbPath = path.join(thumbsDir, thumbRel);
  const srcPath = path.join(folderPath, relPath);

  // Part 2: Check if source file still exists
  if (!fs.existsSync(srcPath)) {
    // Delete stale thumbnail if it exists
    if (fs.existsSync(thumbPath)) {
      try { fs.unlinkSync(thumbPath); } catch (_) {}
    }
    return null;
  }

  // Check if cached thumbnail is still valid
  if (fs.existsSync(thumbPath)) {
    try {
      const srcStat = fs.statSync(srcPath);
      const thumbStat = fs.statSync(thumbPath);
      if (thumbStat.mtimeMs >= srcStat.mtimeMs) {
        const buf = fs.readFileSync(thumbPath);
        return `data:image/jpeg;base64,${buf.toString('base64')}`;
      }
    } catch (_) {}
  }

  // Part 3: Reuse a larger cached thumbnail if available
  const largerDataUrl = tryReuseLargerThumb(folderPath, relPath, thumbWidth);
  if (largerDataUrl) {
    // Write the resized version to disk for next time
    try {
      const thumbDir = path.dirname(thumbPath);
      if (!fs.existsSync(thumbDir)) fs.mkdirSync(thumbDir, { recursive: true });
      const base64Data = largerDataUrl.replace(/^data:image\/jpeg;base64,/, '');
      fs.writeFileSync(thumbPath, Buffer.from(base64Data, 'base64'));
    } catch (_) {}
    return largerDataUrl;
  }

  // Generate from original using Electron nativeImage
  try {
    const { nativeImage } = require('electron');
    const img = nativeImage.createFromPath(srcPath);
    if (img.isEmpty()) return null;
    const origSize = img.getSize();
    if (origSize.width <= 0) return null;
    const ratio = thumbWidth / origSize.width;
    const newW = Math.round(origSize.width * Math.min(ratio, 1));
    const newH = Math.round(origSize.height * Math.min(ratio, 1));
    const resized = img.resize({ width: newW, height: newH, quality: 'good' });
    const jpegBuf = resized.toJPEG(75);

    // Write to disk cache
    const thumbDir = path.dirname(thumbPath);
    if (!fs.existsSync(thumbDir)) fs.mkdirSync(thumbDir, { recursive: true });
    fs.writeFileSync(thumbPath, jpegBuf);

    // LRU cache cleanup (non-blocking)
    setImmediate(() => enforceCacheLimit(path.join(folderPath, '.cache', 'thumbnails')));

    return `data:image/jpeg;base64,${jpegBuf.toString('base64')}`;
  } catch (_) {
    return null;
  }
}

// Part 3: Try to find and resize a larger cached thumbnail
function tryReuseLargerThumb(folderPath, relPath, targetWidth) {
  const thumbRel = relPath.replace(/\.[^.]+$/, '.jpg');
  // Check larger sizes in descending order
  const larger = THUMB_SIZES.filter(s => s > targetWidth).sort((a, b) => a - b);
  for (const bigSize of larger) {
    const bigPath = path.join(folderPath, '.cache', 'thumbnails', String(bigSize), thumbRel);
    if (fs.existsSync(bigPath)) {
      try {
        const { nativeImage } = require('electron');
        const img = nativeImage.createFromPath(bigPath);
        if (img.isEmpty()) continue;
        const origSize = img.getSize();
        const ratio = targetWidth / origSize.width;
        const newW = Math.round(origSize.width * Math.min(ratio, 1));
        const newH = Math.round(origSize.height * Math.min(ratio, 1));
        const resized = img.resize({ width: newW, height: newH, quality: 'good' });
        return `data:image/jpeg;base64,${resized.toJPEG(75).toString('base64')}`;
      } catch (_) { continue; }
    }
  }
  return null;
}

// Part 2: Clean stale thumbnails (orphans whose source no longer exists)
ipcMain.handle('cleanup-stale-thumbnails', async (event, folderPath, validRelPaths) => {
  const thumbsRoot = path.join(folderPath, '.cache', 'thumbnails');
  if (!fs.existsSync(thumbsRoot)) return 0;
  const validSet = new Set(validRelPaths.map(r => r.replace(/\.[^.]+$/, '.jpg')));
  let removed = 0;
  const walkAndClean = (dir, baseDir) => {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walkAndClean(full, baseDir);
        // Remove empty dirs
        try { if (fs.readdirSync(full).length === 0) fs.rmdirSync(full); } catch (_) {}
      } else {
        const rel = path.relative(baseDir, full).replace(/\\/g, '/');
        if (!validSet.has(rel)) {
          try { fs.unlinkSync(full); removed++; } catch (_) {}
        }
      }
    }
  };
  // Clean each size directory
  for (const entry of fs.readdirSync(thumbsRoot, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      walkAndClean(path.join(thumbsRoot, entry.name), path.join(thumbsRoot, entry.name));
    }
  }
  return removed;
});

function enforceCacheLimit(cacheDir) {
  try {
    if (!fs.existsSync(cacheDir)) return;
    const files = [];
    const walkDir = (dir) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walkDir(full);
        else {
          const stat = fs.statSync(full);
          files.push({ path: full, size: stat.size, atime: stat.atimeMs });
        }
      }
    };
    walkDir(cacheDir);
    const totalSize = files.reduce((sum, f) => sum + f.size, 0);
    if (totalSize <= CACHE_MAX_BYTES) return;
    // Sort oldest-accessed first
    files.sort((a, b) => a.atime - b.atime);
    let freed = 0;
    const target = totalSize - CACHE_MAX_BYTES;
    for (const f of files) {
      if (freed >= target) break;
      try { fs.unlinkSync(f.path); freed += f.size; } catch (_) {}
    }
  } catch (_) {}
}
