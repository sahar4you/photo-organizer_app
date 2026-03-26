# Changelog

## v1.2.0

### Quality Scoring
- Image quality scoring system (sharpness + resolution + file size)
- Quality labels: Poor / Basic / Good / Better / Best
- Blur penalty for very blurry images
- Resolution penalty for tiny images (<1 MP)
- Quality filter in sidebar (Good+, Better+, Best)
- Quality badges on photo cards and duplicate rows
- Quality-based keeper selection in duplicate groups

### Resolution Display
- PIL fallback for image dimensions when EXIF is missing
- Explicit width/height fields in scan output
- Resolution shown as "1920 x 1080 (2.1 MP)" everywhere
- Usage labels: Thumbnail / Social Media / Web / Print
- Resolution-based filter (HD+, Full HD+, 4K+)

### Lightbox Enhancements
- Full metadata panel: folder, date, size, resolution, MP, usage label
- Quality breakdown with icons and descriptive labels
- Human-readable quality reason text
- Tags and GPS display

### UX Improvements
- Three view modes: Date / Grid / List
- S/M/L sizing works across all view modes
- Sticky tab bar and tag bar
- Show/hide folder path setting (persisted in localStorage)
- Tag autocomplete with keyboard navigation
- Selection fix: event delegation replaces broken inline onclick
- Keyboard shortcuts: arrows, Enter, Delete, Ctrl+A, Escape

### Scan Progress
- Real-time progress bar with contextual status messages
- JSON-only stdout protocol (no mixed text)

### Help Section
- In-app Help/About modal with quality score guide

---

## v1.1.0

### Portable Build
- PyInstaller bundling: scanner.py → scanner.exe
- No Python required on user machine
- BUILD-PORTABLE.bat automation script
- Dev/production path detection via app.isPackaged

### Tagging System
- Multi-select mode for bulk operations
- Add/remove tags with autocomplete
- Tag filter and clickable chips
- Tags stored in photo_tags.json

### Export Feature
- Export selected photos to named subfolder
- Preserve folder structure option
- Name collision handling

### Thumbnail System
- On-demand thumbnail generation via Electron nativeImage
- Lazy loading with IntersectionObserver
- Dynamic sizes (S: 150px, M: 200px, L: 300px)
- LRU cache with 500MB limit
- Stale thumbnail cleanup after scan
- Concurrency control (max 4 parallel)

### Duplicate Detection Enhancements
- Similarity percentage display (replaces raw Hamming distance)
- Suggested Best badge based on quality
- Ignore Group feature with persistence
- Trash (recycle bin) replaces permanent delete

### Cache Management
- Clear Cache button (hash_cache + thumbnails)

---

## v1.0.0

### Initial Release
- Recursive photo scanning with EXIF extraction
- Face detection (OpenCV Haar cascades)
- Face clustering (Agglomerative, cosine distance)
- Face rename and merge with persistence
- 3-layer duplicate detection (size pre-filter + MD5 + pHash)
- Duplicate move to __duplicates__/ folder
- Interactive gallery with date grouping
- Lightbox with keyboard navigation
- Filters: date, type, size, camera, person
- Standalone HTML gallery generator (photo_organizer.py)
- Electron desktop app with IPC bridge
