# Photo Organizer — Single Source of Truth (SSOT)

> Authoritative reference for architecture, behavior, and design decisions.
> Version 1.2.0

---

## 1. Application Overview

| Field       | Value                                                     |
|-------------|-----------------------------------------------------------|
| Name        | Photo Organizer                                           |
| Version     | 1.2.0                                                     |
| Stack       | Python 3.8+ (scanner) + Electron (desktop UI)             |
| Entry Point | `main.js` → spawns `python_scanner/scanner.py`            |
| IPC Format  | Line-delimited JSON on stdout (progress/result/error)     |
| Storage     | JSON files only (no database, fully portable)             |

---

## 2. Project Structure

```
main.js                         # Electron main process
preload.js                      # Context bridge (IPC APIs)
renderer/index.html             # Electron UI (HTML + CSS + JS)
python_scanner/
  scanner.py                    # Photo scanner (EXIF, faces, quality, recursive)
  duplicate_detector.py         # 3-layer duplicate detection
  scanner.spec                  # PyInstaller build spec
python_bin/                     # Bundled scanner.exe (built by BUILD-PORTABLE.bat)
photo_organizer.py              # Standalone HTML gallery generator
SSOT.md                         # This file
USER_GUIDE.md                   # User documentation
CHANGELOG.md                    # Version history
```

---

## 3. Data Model — File Entry

Each scanned file produces a JSON object with these fields:

```json
{
  "name": "photo.jpg",
  "path": "/absolute/path/photo.jpg",
  "rel_path": "FolderA/FolderB/photo.jpg",
  "type": "image",
  "ext": "jpg",
  "size_mb": 2.3,
  "size_bytes": 2411724,
  "mtime": 1711324800.0,
  "width": 1920,
  "height": 1080,
  "resolution": "1920x1080",
  "date": "2024-01-15 10:30:00",
  "year": "2024",
  "month": "2024-01",
  "day": "2024-01-15",
  "camera": "iPhone 15 Pro",
  "has_gps": true,
  "gps_lat": 15.4909,
  "gps_lon": 73.8278,
  "thumb": "<base64>",
  "quality_score": 87,
  "quality_label": "Best",
  "sharpness": 92,
  "resolution_score": 80,
  "size_score": 70,
  "faces": ["Alice", "Bob"],
  "face_count": 2,
  "tags": ["vacation", "family"]
}
```

Videos: `quality_score`, `quality_label`, `sharpness`, `resolution_score`, `size_score` = `null`

---

## 4. Scanner Protocol (stdout JSON)

Every line on stdout is valid JSON. Three message types:

```
{"type":"progress","value":45,"current":225,"total":500,"status":"scanning"}
{"type":"result","data":{...}}
{"type":"error","message":"..."}
```

All human-readable logs go to stderr via `log()`.

---

## 5. Quality Scoring System

### Algorithm
```
score = (sharpness × 0.5) + (resolution × 0.3) + (file_size × 0.2)
```

### Adjustments
1. Sharpness clamped to max 1000 (Laplacian variance)
2. Blur penalty: sharpness < 20 → score × 0.5
3. Resolution penalty: <0.5 MP → ×0.6, <1 MP → ×0.75
4. Minimum floor: max(score, 5)

### Labels
| Score | Label  |
|-------|--------|
| 0–10  | Poor   |
| 10–25 | Basic  |
| 25–50 | Good   |
| 50–75 | Better |
| 75–100| Best   |

### Resolution Source
1. EXIF `ExifImageWidth`/`ExifImageHeight` (converted to int safely)
2. Fallback: `PIL Image.open().size`

---

## 6. Duplicate Detection (3-Layer)

| Layer | Method | Scope |
|-------|--------|-------|
| 3 (pre-filter) | Group by `size_bytes` | Eliminates ~70-90% comparisons |
| 1 (exact) | MD5 hash (64KB chunks) | Within same-size groups |
| 2 (near) | pHash via `imagehash` (Hamming ≤ 10) | All images globally |

Keeper selection: highest quality_score → shallowest path → earliest mtime → alphabetical.

---

## 7. Caching

### hash_cache.json
Location: `<root>/hash_cache.json`
Invalidation: `(size_bytes, mtime)` — recompute if either changes.

### Thumbnail Cache
Location: `<root>/.cache/thumbnails/<size>/<rel_path>.jpg`
Generated on-demand via Electron `nativeImage`.
LRU eviction at 500MB. Concurrency: max 4 parallel.

---

## 8. Tagging System

Storage: `<root>/photo_tags.json`
```json
{ "A/photo.jpg": ["vacation", "family"] }
```
Tags are lowercase, trimmed, unique per file.

---

## 9. Settings

| Setting | Storage | Default |
|---------|---------|---------|
| Show Folder Name | `localStorage.showFolderName` | `true` |
| View Mode | In-memory | `grid` |
| Grid Size | In-memory | medium |

---

## 10. Scanning Behavior

- Recursive: `os.walk()` from selected root
- Excluded: `__duplicates__/`, `.cache/`
- File identity: relative path from root
- Symlinks: `followlinks=False`

---

## 11. Electron Integration

- Dev: `python3 scanner.py <folder> --json`
- Production: `python_bin/scanner.exe <folder> --json`
- Detection: `app.isPackaged`
- IPC: line-delimited JSON parser with buffer
- Thumbnail generation: `nativeImage.resize()` (no Python needed)
