# Photo Organizer — Single Source of Truth (SSOT)

> This document is the authoritative reference for the Photo Organizer app's architecture, behavior, and design decisions.
> All implementation must conform to this document.

---

## 1. Application Overview

| Field       | Value                                             |
|-------------|---------------------------------------------------|
| Name        | Photo Organizer                                   |
| Stack       | Python 3.8+ (backend scanner) + Electron (desktop UI) |
| Entry Point | `main.js` (Electron) → spawns `python_scanner/scanner.py` |
| Output      | JSON scan result piped from Python → Electron via stdout |

---

## 2. Project Structure

```
photo_organizer.py              # Standalone Python script (HTML gallery generator)
main.js                         # Electron main process
preload.js                      # Context bridge (IPC)
renderer/index.html             # Electron UI
python_scanner/
  scanner.py                    # Photo scanner (EXIF, faces, recursive traversal)
  duplicate_detector.py         # Duplicate detection module (3-layer system)
package.json                    # Electron + builder config
SSOT.md                         # This file — Single Source of Truth
README.md                       # User-facing documentation
```

---

## 3. Scanning Behavior

### 3.1 Recursive Traversal
- Scanner uses `os.walk()` to traverse ALL nested subdirectories from the selected root
- Scans the **entire directory tree**, not just the top-level folder
- Supported extensions: `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.webp`, `.tiff`, `.tif`, `.heic`, `.mp4`, `.mov`, `.avi`, `.mkv`, `.wmv`, `.3gp`

### 3.2 Excluded Directories
- `__duplicates__/` — always skipped during scanning (system-managed folder)
- Symlink loops avoided via `os.walk(followlinks=False)` (default)

### 3.3 File Identity
- Each file is identified by its **relative path** from the scan root
- Example: root is `/home/user/Photos`, file is `/home/user/Photos/A/B/pic.jpg` → rel_path = `A/B/pic.jpg`
- Relative paths are used as keys in cache and duplicate group output

---

## 4. Duplicate Detection System

### 4.1 Architecture — 3 Layers

| Layer | Purpose             | Method                     | Scope             |
|-------|---------------------|----------------------------|--------------------|
| 3     | Pre-filter          | Group by `size_bytes`      | Eliminates ~70-90% of comparisons |
| 1     | Exact duplicates    | MD5 file hash              | Within same-size groups only |
| 2     | Near duplicates     | Perceptual hash (pHash)    | All images globally |

### 4.2 Detection is GLOBAL
- Duplicates are detected **across all folders** in the entire tree
- Not scoped to individual folders
- A file in `root/A/B/` can be a duplicate of a file in `root/X/Y/Z/`

### 4.3 Layer Details

**Layer 3 — Size Pre-filter:**
- Group all files by `size_bytes`
- Groups with only 1 file are excluded from exact-duplicate hashing
- O(n) grouping step

**Layer 1 — Exact Duplicates (MD5):**
- `hashlib.md5()`, read in 64KB chunks
- Applied only within same-size groups (Layer 3 output)
- Files with identical MD5 = exact duplicates

**Layer 2 — Near Duplicates (pHash):**
- Library: `imagehash.phash()` (from `imagehash` package)
- Comparison: Hamming distance via `hash1 - hash2`
- Threshold: ≤ 10 (configurable)
- Applied to all image files globally (videos excluded)
- Pairs already flagged as exact duplicates are skipped
- Clustering via Union-Find for transitive grouping
- **Safety check**: if image count > 3000, log warning about O(n²) comparisons

### 4.4 Dependencies
```
pip install imagehash
```
(`imagehash` pulls in PIL, numpy, scipy internally)

---

## 5. Caching — hash_cache.json

### 5.1 Location
- `root/hash_cache.json` — stored at the scan root directory

### 5.2 Structure
```json
{
  "version": 1,
  "root": "/absolute/path/to/root",
  "files": {
    "A/photo1.jpg": {
      "size_bytes": 2048576,
      "mtime": 1711324800.0,
      "file_hash": "md5:d41d8cd98f00b204...",
      "phash": "d4c3b2a1e5f67890"
    }
  }
}
```

### 5.3 Cache Invalidation
- Key: `(size_bytes, mtime)` per file
- If either value changed → recompute hashes for that file
- If both match → use cached hashes (skip recomputation)

### 5.4 Cache Pruning
- On load, remove entries for files that no longer exist on disk
- Prevents stale data from deleted/moved files

---

## 6. Duplicate Resolution

### 6.1 Keeper Selection (deterministic priority)
1. **Shallowest path depth** — prefer `root/a.jpg` over `root/X/Y/a.jpg`
2. **Earliest file mtime** — prefer older file (likely the original)
3. **Alphabetical rel_path** — tiebreaker for reproducibility

One file is kept per duplicate group. All others are moved.

### 6.2 __duplicates__/ Folder

| Rule                  | Detail                                              |
|-----------------------|-----------------------------------------------------|
| Location              | `root/__duplicates__/`                              |
| Created               | Automatically when duplicates are found             |
| Excluded from scan    | Always — hardcoded skip in `os.walk` pruning        |
| Structure preserved   | Original relative path is mirrored inside           |
| Name collisions       | Append `_dup2`, `_dup3`, etc.                       |

**Example:**
```
BEFORE:
  root/A/photo1.jpg       (original)
  root/B/photo1.jpg       (duplicate)
  root/C/A/photo1.jpg     (duplicate)

AFTER:
  root/A/photo1.jpg                          (kept)
  root/__duplicates__/B/photo1.jpg           (moved)
  root/__duplicates__/C/A/photo1.jpg         (moved)
```

### 6.3 Operation Modes
- `mode="move"` — `shutil.move()` — **default, implemented**
- `mode="copy"` — `shutil.copy2()` — **future flag, not yet implemented**

### 6.4 Post-Move Cleanup
- Empty source directories are removed bottom-up after moves

---

## 7. Scan Result JSON Structure

```json
{
  "folder": "/absolute/root",
  "files": [
    {
      "name": "photo1.jpg",
      "path": "/absolute/root/A/photo1.jpg",
      "rel_path": "A/photo1.jpg",
      "type": "image",
      "size_bytes": 2048576,
      "date": "2024-01-15 10:30:00",
      "faces": [],
      "..."
    }
  ],
  "duplicate_groups": {
    "exact": [
      {
        "hash": "md5:d41d8cd9...",
        "keep": "A/photo1.jpg",
        "duplicates": ["B/photo1.jpg"]
      }
    ],
    "near": [
      {
        "representative": "A/sunset.jpg",
        "keep": "A/sunset.jpg",
        "duplicates": ["D/sunset_small.jpg"],
        "members": [
          {"rel_path": "A/sunset.jpg", "distance": 0},
          {"rel_path": "D/sunset_small.jpg", "distance": 7}
        ]
      }
    ]
  },
  "total": 150,
  "face_images": 42,
  "persons": 5
}
```

---

## 8. Edge Case Handling

| Case                            | Handling                                        |
|---------------------------------|-------------------------------------------------|
| Same filename, different folders | rel_path is unique — no conflict                |
| Deep nesting (10+ levels)       | os.walk handles natively                        |
| Symlink loops                   | `followlinks=False` (os.walk default)           |
| File vanishes mid-scan          | try/except per file, skip + log warning         |
| Destination collision           | Append `_dup2`, `_dup3` suffix                  |
| Read-only filesystem            | Catch `PermissionError`, log warning, continue  |
| Empty dirs after move           | Remove bottom-up if empty                       |
| Stale cache entries             | Prune on load                                   |
| 3000+ images (pHash)            | Log O(n²) warning, proceed                      |
| Corrupt/truncated image         | pHash fails gracefully, skip, log warning       |
| HEIC without pillow-heif        | Skip file, log warning                          |
| Videos                          | MD5 exact-dup only; pHash skipped               |

---

## 9. Face Detection (existing, unchanged)

- **Method**: OpenCV Haar Cascade (frontal + profile)
- **Embedding**: Custom ~640-d vector (histogram + Sobel + proportions)
- **Clustering**: Agglomerative, cosine distance, threshold=0.45
- **Storage**: `face_names.json` in scanned folder (person ID → display name)

---

## 10. Electron Integration

- `main.js` spawns `python3 scanner.py <folder> --json`
- Scanner writes JSON to stdout; Electron parses last JSON block
- Progress lines (`Scanning: XX%`) forwarded to renderer via IPC
- `hash_cache.json` and `face_names.json` managed by Python, read/written directly to disk
- No Electron-side changes needed for duplicate detection (data flows through existing JSON pipeline)
