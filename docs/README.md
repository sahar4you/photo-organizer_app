# Photo Organizer (INDIATECH247)

## Overview

Offline, high-performance photo intelligence system built with Electron + Python. Designed for fast browsing, filtering, and reference usage in sales and internal operations.

**Key principle**: Images load instantly. All heavy processing runs in the background.

## Core Features

| Feature | Description |
|---------|-------------|
| Cache-first loading | App reopens in <1 second on unchanged folders |
| Face detection | DNN-based with 9-stage filtering, clustering, naming |
| Duplicate detection | MD5 exact + pHash near-duplicate with smart keeper selection |
| Smart filtering | Faces, folders, cameras, tags, quality, resolution |
| Lightbox | Full-quality image with pan/zoom (0.5x-8x), file info |
| Portable EXE | Single-file Windows executable via electron-builder |

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Desktop shell | Electron 33 |
| UI | Single HTML file with inline CSS/JS |
| Image processing | Python 3.10+ (OpenCV, NumPy, scikit-learn, Pillow, imagehash) |
| Face detection | OpenCV DNN (res10 SSD) + Haar cascade fallback |
| IPC | Line-delimited JSON over stdout/stderr |
| Build | electron-builder (portable EXE) + PyInstaller (scanner binary) |

## Project Structure

```
photo-organizer_app/
  main.js                    # Electron main process
  preload.js                 # IPC bridge (contextBridge)
  renderer/index.html        # Complete UI (single file)
  python_scanner/
    scanner.py               # Photo scanning, face detection, quality scoring
    duplicate_detector.py     # 3-layer duplicate detection
    models/                   # DNN face detector model files
      deploy.prototxt
      res10_300x300_ssd_iter_140000.caffemodel
    scanner.spec             # PyInstaller build config
  python/
    setup_env.py             # Auto-install Python dependencies
  package.json               # npm + electron-builder config
  docs/                      # Documentation
```

## Quick Start

```bash
# Install dependencies
npm install

# Run in development
npm start

# Build portable EXE
npm run dist
```

## Version

**v1.0** - Production release by INDIATECH247
