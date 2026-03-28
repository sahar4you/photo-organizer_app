# Troubleshooting

## Cache Not Working (app rescans every time)

**Symptoms**: Full scan runs on every app open instead of instant load.

**Causes and fixes**:

1. **Files changed**: Any file added, removed, or modified invalidates `scan_result_cache.json`. This is correct behavior.

2. **Cache version mismatch**: After app update, `CACHE_VERSION` or `CACHE_FORMAT_VERSION` may have changed. First scan after update will be full; subsequent opens will be cached.

3. **Cache file corrupted**: Delete `.cache/data/scan_result_cache.json` and reopen. A fresh scan will rebuild it.

4. **Folder on network drive**: Mtime resolution may differ. Copy folder locally for best performance.

## Slow Scan

**For first scan (no cache)**:

- Face detection is the bottleneck (uses multiprocessing with 2-4 workers)
- 300 images: ~1-3 minutes
- 1000+ images: ~5-10 minutes
- The gallery loads instantly via Phase 1; only Phase 2 (background) is slow

**For repeat scans**:

- Should be instant (<1 second) if files unchanged
- If still slow, check that `.cache/data/` directory exists and is writable

## Missing Faces

1. **DNN model not loaded**: Check logs for "DNN model files not found". Ensure `python_scanner/models/` contains both model files.

2. **Face too small**: Minimum face size is 80x80 pixels. Distant/group photos may not detect small faces.

3. **Strict filtering**: The 9-stage filter rejects:
   - Low confidence (<0.75)
   - Blurry faces (Laplacian variance < 80)
   - Non-frontal faces (requires exactly 2 eyes)
   - Edge faces (touching image border)

4. **Max 5 faces per image**: Only the 5 largest faces are kept per image.

**To debug**: Set `DEBUG=true` environment variable before running. This enables verbose face detection logs showing rejection reasons.

## Duplicate Issues

### Wrong file marked as duplicate

The keeper selection uses this priority:
1. Not a copy file (originals before copies)
2. Earliest modification time
3. Highest quality score
4. Shortest filename
5. Shallowest path

Use "Set as keeper" button to override.

### Duplicate groups contain wrong files

Near-duplicate threshold is Hamming distance <= 10 (out of 64 bits). Lower values are stricter. This is set in `detect_duplicates()` call in scanner.py.

### Files in subfolders (path issues)

Paths with backslashes (Windows) or special characters are escaped in onclick handlers. If "Set as keeper" doesn't work, this may be a path escaping issue. Check browser console for JS errors.

## Python Dependencies

If face detection or duplicate detection isn't working:

```bash
# Check Python version
python3 --version  # Need 3.10+

# Manual install
python3 -m pip install opencv-python-headless numpy scikit-learn pillow imagehash

# Verify
python3 -c "import cv2; print(cv2.__version__)"
```

## Electron Dialog Issues

All dialogs use Electron's `dialog.showMessageBox` via IPC. If dialogs don't appear:
- Check that `mainWindow` is valid in main.js
- Check browser console for IPC errors
- Ensure preload.js exposes `showMessageBox`

## Performance Tips

- **Large libraries (1000+ images)**: First scan will be slow. Subsequent opens use cache.
- **Network folders**: Copy locally for best performance.
- **Low-end machines**: Face detection uses max 4 workers. Set `DEBUG=true` to monitor CPU.
- **Clear cache**: Use "Clear Cache" button in sidebar if thumbnails look wrong.
