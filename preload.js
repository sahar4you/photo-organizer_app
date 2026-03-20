// Ready to use – Preload bridge for Electron renderer
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  pickFolder: () => ipcRenderer.invoke('pick-folder'),
  scanFolder: (folderPath) => ipcRenderer.invoke('scan-folder', folderPath),
  saveFaceNames: (folderPath, nameMap) => ipcRenderer.invoke('save-face-names', folderPath, nameMap),
  loadFaceNames: (folderPath) => ipcRenderer.invoke('load-face-names', folderPath),
  readImage: (filePath) => ipcRenderer.invoke('read-image', filePath),
  onScanProgress: (callback) => ipcRenderer.on('scan-progress', (_, msg) => callback(msg)),
});
