# Photo Organizer App

A desktop photo organizer with Google Photos-like filtering, face detection, grouping, and an interactive gallery.

## Features

- **EXIF Metadata Extraction** – Date, camera, GPS, resolution
- **Smart Filters** – Filter by date, size, type, camera, resolution
- **Face Detection & Clustering** – OpenCV Haar cascades + AgglomerativeClustering
- **Face Rename & Merge** – Assign real names, merge duplicates, persisted in `face_names.json`
- **Interactive Gallery** – Lightbox, keyboard navigation, responsive layout
- **Standalone Script** – `python3 photo_organizer.py /path/to/photos` generates a self-contained HTML gallery
- **Electron Desktop App** – Native app with direct disk save for face names

## Quick Start – Standalone Script

```bash
pip install Pillow opencv-python scikit-learn numpy
python3 photo_organizer.py /path/to/photos
# Opens generated gallery.html in your browser
```

## Quick Start – Electron App (Windows)

1. Run `SETUP.bat` (installs Node + Python dependencies)
2. Run `START.bat` (launches the app)
3. Pick a folder and browse your photos

## Build Portable .exe

```bash
BUILD-PORTABLE.bat
```

## Project Structure

```
photo_organizer.py          # Standalone Python script (generates HTML gallery)
main.js                     # Electron main process
preload.js                  # Context bridge (IPC)
renderer/index.html         # Electron UI
python_scanner/scanner.py   # Python scanner for Electron (--json output)
package.json                # Electron + builder config
SETUP.bat                   # Windows setup script
START.bat                   # Windows launch script
BUILD-PORTABLE.bat          # Windows portable build script
```

## Requirements

- Python 3.8+
- Node.js 18+ (for Electron app)
- Pillow, opencv-python, scikit-learn, numpy

## License

MIT
