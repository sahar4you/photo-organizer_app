# Architecture

## System Flow

The app uses a 3-phase scan architecture with cache-first loading.

### Phase 0: Cache-First Load (instant)

```
scanCurrentFolder()
  -> loadScanCache(folder)
  -> validate folder signature (file count + newest mtime)
  -> IF valid: render gallery from cache, RETURN (no Python processes)
```

**Folder signature**: `{fileCount}:{newestMtimeMs}` computed by walking the folder tree. Changes when any file is added, removed, or modified.

### Phase 1: Quick Metadata Scan (1-2 seconds)

Only runs if cache is missing or stale.

```
Python scanner.py --quick
  -> collect media files
  -> extract EXIF (Pillow)
  -> read resolution (PIL)
  -> parse dates (EXIF + filename)
  -> output JSON result
```

**Skips**: face detection, duplicate detection, thumbnails, quality scoring.

Gallery renders immediately after Phase 1. Loading overlay dismissed.

### Phase 2: Full Background Scan (30s - 5min)

Runs after gallery is visible. UI never blocked.

```
Python scanner.py (full mode)
  -> metadata + EXIF extraction
  -> thumbnail generation
  -> sharpness/quality scoring
  -> face detection (multiprocessing)
  -> face clustering
  -> duplicate detection (MD5 + pHash)
  -> output JSON result
```

Results merged into existing DATA. Scan result saved to cache for next app open.

## Caching System

### Cache Files (stored in `{folder}/.cache/data/`)

| File | Purpose | Invalidation |
|------|---------|-------------|
| `scan_result_cache.json` | Full scan result (Phase 0) | Folder signature change (file add/remove/modify) |
| `face_cache.json` | Per-file face detection results | Per-file mtime + cache version |
| `dup_result_cache.json` | Duplicate grouping results | MD5 of all (rel_path, size, mtime) tuples |
| `hash_cache.json` | Per-file MD5 + pHash hashes | Per-file size + mtime |
| `face_names.json` | Face name mappings + kept faces | Manual edit only |

### Cache Version

`CACHE_VERSION = "v4"` in scanner.py, `CACHE_FORMAT_VERSION = 2` in duplicate_detector.py. Bumping either forces reprocessing of affected cache.

### Cache Flow

```
App open -> check scan_result_cache (Phase 0)
  HIT  -> instant load, done
  MISS -> Phase 1 (quick scan) -> Phase 2 (full scan)
            Phase 2 checks:
              face_cache -> skip unchanged files
              dup_result_cache -> skip if file set unchanged
              hash_cache -> skip re-hashing unchanged files
```

## Data Model

### DATA Array (renderer)

Each file entry:

```javascript
{
  name: "photo.jpg",
  path: "/absolute/path/photo.jpg",
  rel_path: "subfolder/photo.jpg",
  type: "image" | "video",
  ext: "jpg",
  size_mb: 2.5,
  size_bytes: 2621440,
  mtime: 1234567890.0,
  date: "2023-01-15 14:30:45",
  year: "2023", month: "2023-01", day: "2023-01-15",
  camera: "Samsung SM-G998B",
  resolution: "4080x3060",
  width: 4080, height: 3060,
  quality_score: 85, quality_label: "Best",
  faces: ["Person 1", "Deva"],
  face_count: 2,
  tags: ["Vacation"],
  // ... iso, exposure, aperture, focal_length, gps_lat, gps_lon, etc.
}
```

### DUP_GROUPS

```javascript
{
  exact: [
    { hash: "md5:abc...", keep: "original.jpg", duplicates: ["copy.jpg"] }
  ],
  near: [
    {
      keep: "best.jpg",
      duplicates: ["similar.jpg"],
      members: [
        { rel_path: "best.jpg", distance: 0 },
        { rel_path: "similar.jpg", distance: 8 }
      ]
    }
  ]
}
```

### Face Mappings

`face_names.json`:
```json
{
  "Person 1": "Deva",
  "Person 2": "Akhilesh",
  "Deva": "__kept__"
}
```

Names are applied during scan. `__kept__` entries mark faces for the gallery "Kept Faces" filter.

## IPC Architecture

```
Renderer (index.html)
  -> window.api.* (preload.js contextBridge)
  -> ipcRenderer.invoke(channel, args)
  -> main.js ipcMain.handle(channel)
  -> spawn Python / fs operations / dialog
  -> return result
```

### Key IPC Channels

| Channel | Direction | Purpose |
|---------|-----------|---------|
| scan-folder-quick | R->M | Phase 1 metadata scan |
| scan-folder-full | R->M | Phase 2 full scan |
| load-scan-cache | R->M | Load cached scan result |
| save-scan-cache | R->M | Save scan result to cache |
| show-message-box | R->M | Electron-native dialog |
| delete-file | R->M | Trash file with confirmation |
| generate-thumbnail | R->M | Lazy thumbnail generation |

## Face Detection Pipeline

9-stage DNN filter:

1. Confidence > 0.75
2. Minimum size 80x80
3. Absolute area > 5000px
4. Relative area > 2% of image
5. Aspect ratio 0.6-1.4
6. Edge rejection (5px margin)
7. Blur check (Laplacian variance > 80)
8. Eye validation (exactly 2 eyes in upper 50%)
9. Eye geometry (distance 20-70% of face width, vertical alignment < 30%)

Post-filter: max 5 faces per image (keep largest).

Multiprocessing: up to 4 workers, batch size 6, 50ms throttle between batches.

## Duplicate Detection Pipeline

1. **Layer 3**: Group by file size (skip unique sizes)
2. **Layer 1**: MD5 hash within same-size groups (exact duplicates)
3. **Layer 2**: pHash comparison with Hamming distance <= 10 (near duplicates)
4. **Union-Find**: Transitive clustering of near-duplicate pairs
5. **Keeper selection**: Priority: not-copy > oldest > highest quality > shortest name
