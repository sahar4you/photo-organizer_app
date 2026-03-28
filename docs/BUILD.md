# Build Guide

## Prerequisites

- Node.js 18+
- Python 3.10+
- npm

## Development Setup

```bash
# Clone repository
git clone <repo-url>
cd photo-organizer_app

# Install Node dependencies (also auto-installs Python deps)
npm install

# Run in development mode
npm start
```

The `postinstall` script automatically runs `python/setup_env.py` which installs:
- opencv-python-headless
- numpy
- scikit-learn
- pillow
- imagehash

## Build Portable EXE

### Step 1: Build Python Scanner Binary

```bash
cd python_scanner
pip install pyinstaller
pyinstaller scanner.spec
```

This creates `dist/scanner` (or `scanner.exe` on Windows). Copy it to `python_bin/`:

```bash
cp dist/scanner ../python_bin/scanner
# or on Windows:
# copy dist\scanner.exe ..\python_bin\scanner.exe
```

### Step 2: Build Electron App

```bash
# From project root
npm run dist
```

Output: `dist/PhotoOrganizer-Portable.exe` (Windows)

### Build Targets

| Command | Output |
|---------|--------|
| `npm run dist` | Platform-specific installer/portable |
| `npm run build-portable` | Windows portable EXE specifically |
| `npm run pack` | Unpacked directory (for testing) |

## What Gets Bundled

| Component | Included in EXE |
|-----------|----------------|
| Electron runtime | Yes |
| main.js, preload.js, renderer/ | Yes |
| python_bin/scanner(.exe) | Yes (via extraResources) |
| python_scanner/models/ | Yes (via extraResources) |
| python_scanner/*.py | No (source excluded, binary used) |
| node_modules | Yes (auto) |

## DNN Model Files

The face detection model files are bundled automatically:
- `python_scanner/models/deploy.prototxt` (28KB)
- `python_scanner/models/res10_300x300_ssd_iter_140000.caffemodel` (10.1MB)

These are included via:
- `electron-builder` extraResources (for Electron packaging)
- `scanner.spec` datas list (for PyInstaller packaging)

## Troubleshooting Build

| Issue | Fix |
|-------|-----|
| `scanner.exe not found` | Run PyInstaller first: `cd python_scanner && pyinstaller scanner.spec` |
| Missing Python deps in EXE | Check scanner.spec hiddenimports list |
| DNN model not loading in EXE | Verify models/ bundled in scanner.spec datas |
| Electron build fails | Run `npm install` first, check electron-builder version |
