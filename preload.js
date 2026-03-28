// Ready to use – Preload bridge for Electron renderer
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  pickFolder: () => ipcRenderer.invoke('pick-folder'),
  scanFolder: (folderPath) => ipcRenderer.invoke('scan-folder', folderPath),
  validateFolder: (folderPath) => ipcRenderer.invoke('validate-folder', folderPath),
  saveFaceNames: (folderPath, nameMap) => ipcRenderer.invoke('save-face-names', folderPath, nameMap),
  loadFaceNames: (folderPath) => ipcRenderer.invoke('load-face-names', folderPath),
  readImage: (filePath) => ipcRenderer.invoke('read-image', filePath),
  showInFolder: (filePath) => ipcRenderer.invoke('show-in-folder', filePath),
  moveDuplicates: (folderPath) => ipcRenderer.invoke('move-duplicates', folderPath),
  trashFiles: (filePaths) => ipcRenderer.invoke('trash-files', filePaths),
  deleteFile: (filePath) => ipcRenderer.invoke('delete-file', filePath),
  showMessageBox: (options) => ipcRenderer.invoke('show-message-box', options),
  saveIgnoredGroups: (folderPath, groups) => ipcRenderer.invoke('save-ignored-groups', folderPath, groups),
  loadIgnoredGroups: (folderPath) => ipcRenderer.invoke('load-ignored-groups', folderPath),
  saveTags: (folderPath, tagsMap) => ipcRenderer.invoke('save-tags', folderPath, tagsMap),
  loadTags: (folderPath) => ipcRenderer.invoke('load-tags', folderPath),
  moveTaggedFiles: (folderPath, relPaths, subfolder) => ipcRenderer.invoke('move-tagged-files', folderPath, relPaths, subfolder),
  exportFiles: (folderPath, relPaths, subfolder, preserveStructure) => ipcRenderer.invoke('export-files', folderPath, relPaths, subfolder, preserveStructure),
  clearCache: (folderPath) => ipcRenderer.invoke('clear-cache', folderPath),
  generateThumbnail: (folderPath, relPath, size) => ipcRenderer.invoke('generate-thumbnail', folderPath, relPath, size),
  cleanupStaleThumbnails: (folderPath, validRelPaths) => ipcRenderer.invoke('cleanup-stale-thumbnails', folderPath, validRelPaths),
  onScanProgress: (callback) => ipcRenderer.on('scan-progress', (_, msg) => callback(msg)),
  onScanProgressJson: (callback) => ipcRenderer.on('scan-progress-json', (_, data) => callback(data)),
});
