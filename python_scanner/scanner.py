#!/usr/bin/env python3
"""
Photo Scanner — scans folder, extracts EXIF + face data, outputs JSON.
Usage: python3 scanner.py /path/to/folder [--json]
"""
import os, sys, json, base64, hashlib
from datetime import datetime
from pathlib import Path
from io import BytesIO

try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import cv2
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering
    HAS_FACE = True
except ImportError:
    HAS_FACE = False

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.heic'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.3gp'}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
THUMB_SIZE = (300, 300)
CACHE_DIR = ".cache"
THUMBS_DIR = os.path.join(CACHE_DIR, "thumbnails")

# ---- JSON stdout helpers ----
def emit_progress(value, current, total, status="scanning"):
    """Write a progress JSON line to stdout."""
    print(json.dumps({"type": "progress", "value": value,
                       "current": current, "total": total,
                       "status": status}), flush=True)

def emit_result(data):
    """Write the final result JSON line to stdout."""
    print(json.dumps({"type": "result", "data": data}), flush=True)

def emit_error(message):
    """Write an error JSON line to stdout."""
    print(json.dumps({"type": "error", "message": message}), flush=True)

def log(msg):
    """Write a log message to stderr (never stdout)."""
    print(msg, file=sys.stderr, flush=True)

# ---- EXIF ----
def get_exif_data(filepath):
    exif = {}
    if not HAS_PIL: return exif
    try:
        img = Image.open(filepath)
        raw = img._getexif()
        if raw:
            for tag_id, value in raw.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag == "GPSInfo":
                    gps = {}
                    for gps_id in value:
                        gps[GPSTAGS.get(gps_id, gps_id)] = value[gps_id]
                    exif["GPSInfo"] = gps
                else:
                    exif[tag] = value
    except: pass
    return exif

def get_gps_coords(gps_info):
    try:
        def to_dec(coord, ref):
            d, m, s = [float(x) for x in coord]
            dec = d + m/60 + s/3600
            if ref in ('S','W'): dec = -dec
            return round(dec, 6)
        return to_dec(gps_info['GPSLatitude'], gps_info['GPSLatitudeRef']), to_dec(gps_info['GPSLongitude'], gps_info['GPSLongitudeRef'])
    except: return None, None

def get_date_from_exif(exif):
    for key in ('DateTimeOriginal', 'DateTime', 'DateTimeDigitized'):
        val = exif.get(key)
        if val:
            try: return datetime.strptime(str(val).strip(), "%Y:%m:%d %H:%M:%S")
            except: pass
    return None

def get_date_from_filename(filename):
    name = Path(filename).stem.split(' ')[0]
    try: return datetime.strptime(name[:15], "%Y%m%d_%H%M%S")
    except: pass
    try: return datetime.strptime(name[:8], "%Y%m%d")
    except: pass
    return None

def make_thumbnail_b64(filepath):
    if not HAS_PIL: return ""
    try:
        img = Image.open(filepath)
        img.thumbnail(THUMB_SIZE)
        if img.mode in ('RGBA', 'P'): img = img.convert('RGB')
        buf = BytesIO()
        img.save(buf, format='JPEG', quality=60)
        return base64.b64encode(buf.getvalue()).decode()
    except: return ""

# ---- Image Quality Scoring ----
def compute_sharpness(filepath):
    """Compute sharpness via Laplacian variance. Returns raw variance float."""
    if not HAS_FACE:
        return 0.0
    try:
        img = cv2.imread(str(filepath))
        if img is None:
            return 0.0
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Resize to max 800px for consistent & fast scoring
        h, w = gray.shape[:2]
        if max(h, w) > 800:
            scale = 800 / max(h, w)
            gray = cv2.resize(gray, (int(w * scale), int(h * scale)))
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except Exception:
        return 0.0

def compute_quality_scores(filepath, size_bytes, resolution_str, sharpness_raw,
                           max_sharpness, max_pixels, max_size):
    """Compute normalized quality sub-scores and final weighted score."""
    # Clamp sharpness to avoid outliers
    clamped = min(sharpness_raw, 1000.0)
    sharpness = min(100, round((clamped / max_sharpness) * 100)) if max_sharpness > 0 else 0

    # Resolution: 0-100
    pixels = 0
    if resolution_str and resolution_str != "Unknown":
        parts = resolution_str.split("x")
        if len(parts) == 2:
            try:
                pixels = int(parts[0]) * int(parts[1])
            except ValueError:
                pass
    resolution_score = min(100, round((pixels / max_pixels) * 100)) if max_pixels > 0 else 0

    # File size: 0-100
    size_score = min(100, round((size_bytes / max_size) * 100)) if max_size > 0 else 0

    # Weighted final score
    quality_score = round(sharpness * 0.5 + resolution_score * 0.3 + size_score * 0.2)

    # Blur penalty: heavily blurry images get score halved
    if sharpness < 20:
        quality_score = round(quality_score * 0.5)

    # Resolution-based adjustment for tiny images
    megapixels = pixels / 1_000_000
    if megapixels < 0.5:
        quality_score = round(quality_score * 0.6)
    elif megapixels < 1:
        quality_score = round(quality_score * 0.75)

    # Minimum floor: no image scores below 5
    quality_score = max(quality_score, 5)

    # Quality label
    if quality_score >= 75:
        quality_label = "Best"
    elif quality_score >= 50:
        quality_label = "Better"
    elif quality_score >= 25:
        quality_label = "Good"
    elif quality_score >= 10:
        quality_label = "Basic"
    else:
        quality_label = "Poor"

    return {
        "quality_score": quality_score,
        "quality_label": quality_label,
        "sharpness": sharpness,
        "resolution_score": resolution_score,
        "size_score": size_score,
    }

# ---- Face Detection (OpenCV) ----
def detect_faces_cv(filepath, face_cascade, profile_cascade):
    if not HAS_FACE or face_cascade is None:
        return [], []
    try:
        img = cv2.imread(str(filepath))
        if img is None:
            log(f"Face: cv2.imread returned None for {filepath}")
            return [], []
        h, w = img.shape[:2]
        max_dim = 800
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = cv2.resize(img, (int(w*scale), int(h*scale)))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        # Multi-pass face detection: try progressively looser parameters
        faces = ()
        for sf, mn in [(1.1, 5), (1.05, 3), (1.15, 3)]:
            faces = face_cascade.detectMultiScale(gray, scaleFactor=sf, minNeighbors=mn, minSize=(30, 30))
            if len(faces) > 0:
                break

        # Try profile cascade if frontal found nothing
        if len(faces) == 0 and profile_cascade is not None:
            for sf, mn in [(1.1, 5), (1.05, 3)]:
                faces = profile_cascade.detectMultiScale(gray, scaleFactor=sf, minNeighbors=mn, minSize=(30, 30))
                if len(faces) > 0:
                    break

        if len(faces) == 0:
            return [], []

        rects, embeddings = [], []
        for (fx,fy,fw,fh) in faces:
            rects.append((fx,fy,fw,fh))
            face_roi = gray[fy:fy+fh, fx:fx+fw]
            face_resized = cv2.resize(face_roi, (128,128))
            hist_vec = []
            for gy in range(8):
                for gx in range(8):
                    block = face_resized[gy*16:(gy+1)*16, gx*16:(gx+1)*16]
                    hist = cv2.calcHist([block],[0],None,[8],[0,256]).flatten()
                    hist = hist / (hist.sum()+1e-7)
                    hist_vec.extend(hist)
            sobel_x = cv2.Sobel(face_resized, cv2.CV_64F, 1, 0, ksize=3)
            sobel_y = cv2.Sobel(face_resized, cv2.CV_64F, 0, 1, ksize=3)
            for gy in range(4):
                for gx in range(4):
                    bx = sobel_x[gy*32:(gy+1)*32, gx*32:(gx+1)*32]
                    by = sobel_y[gy*32:(gy+1)*32, gx*32:(gx+1)*32]
                    mag = np.sqrt(bx**2+by**2).flatten()
                    h2 = cv2.calcHist([mag.astype(np.float32)],[0],None,[8],[0,mag.max()+1]).flatten()
                    h2 = h2/(h2.sum()+1e-7)
                    hist_vec.extend(h2)
            third_h = face_resized.shape[0]//3
            for t in range(3):
                strip = face_resized[t*third_h:(t+1)*third_h, :]
                hist_vec.extend([strip.mean()/255.0, strip.std()/255.0])
            embeddings.append(hist_vec)
        return rects, embeddings
    except: return [], []

def extract_face_thumbs_cv(filepath, rects):
    if not HAS_PIL: return []
    try:
        img = cv2.imread(str(filepath))
        if img is None: return []
        h, w = img.shape[:2]
        max_dim = 800
        if max(h,w) > max_dim:
            scale = max_dim/max(h,w)
            img = cv2.resize(img, (int(w*scale), int(h*scale)))
        thumbs = []
        for (fx,fy,fw,fh) in rects:
            pad = int(fw*0.2)
            x1,y1 = max(0,fx-pad), max(0,fy-pad)
            x2,y2 = min(img.shape[1],fx+fw+pad), min(img.shape[0],fy+fh+pad)
            crop = cv2.cvtColor(img[y1:y2,x1:x2], cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(crop)
            pil_img.thumbnail((80,80))
            buf = BytesIO()
            pil_img.save(buf, format='JPEG', quality=70)
            thumbs.append(base64.b64encode(buf.getvalue()).decode())
        return thumbs
    except: return []

def cluster_faces(all_face_data):
    if not all_face_data: return {}, {}
    embeddings = np.array([d[1] for d in all_face_data])
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms==0] = 1
    embeddings = embeddings / norms
    if len(embeddings) < 2:
        labels = np.array([0])
    else:
        clustering = AgglomerativeClustering(
            n_clusters=None, distance_threshold=0.45,
            metric='cosine', linkage='average'
        ).fit(embeddings)
        labels = clustering.labels_

    file_faces, person_thumbs = {}, {}
    for i, (file_idx, _, face_thumb) in enumerate(all_face_data):
        label = int(labels[i])
        person_name = f"Person {label+1}"
        if file_idx not in file_faces: file_faces[file_idx] = []
        if person_name not in file_faces[file_idx]: file_faces[file_idx].append(person_name)
        if person_name not in person_thumbs and face_thumb:
            person_thumbs[person_name] = face_thumb
    return file_faces, person_thumbs

# ---- Scanner ----
DUPLICATES_DIR = "__duplicates__"

def _collect_media_files(folder):
    """Recursively collect all media files under folder, skipping __duplicates__/.
    Returns sorted list of (absolute_path, rel_path) tuples."""
    folder = Path(folder)
    media_files = []
    for dirpath, dirnames, filenames in os.walk(folder):
        # Skip __duplicates__ directory (keep .cache accessible for app logic)
        dirnames[:] = [d for d in dirnames if d != DUPLICATES_DIR]
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext in MEDIA_EXTENSIONS:
                abs_path = Path(dirpath) / name
                rel_path = str(abs_path.relative_to(folder))
                # Hide .cache files from scan results
                if rel_path.startswith(CACHE_DIR + os.sep) or rel_path.startswith(CACHE_DIR + '/'):
                    continue
                media_files.append((abs_path, rel_path))
    return sorted(media_files, key=lambda x: x[1])

def scan_folder(folder):
    folder = Path(folder).resolve()
    files = []

    # Recursive traversal — collect all media files in tree
    all_media = _collect_media_files(folder)
    total_count = len(all_media)

    # Warn if large library
    if total_count > 3000:
        log(f"Warning: {total_count} files found. Scanning may take a while.")

    face_cascade, profile_cascade = None, None
    all_face_data = []
    if HAS_FACE:
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml'
        profile_path = cv2.data.haarcascades + 'haarcascade_profileface.xml'
        face_cascade = cv2.CascadeClassifier(cascade_path)
        profile_cascade = cv2.CascadeClassifier(profile_path)
        if face_cascade.empty():
            log(f"FACE ERROR: Failed to load frontal cascade from {cascade_path}")
            face_cascade = None
        else:
            log(f"Face cascade loaded OK from {cascade_path}")
        if profile_cascade is not None and profile_cascade.empty():
            log(f"FACE WARNING: Profile cascade failed from {profile_path}")
            profile_cascade = None
    else:
        log("Face detection unavailable: cv2/numpy/sklearn not installed")

    for i, (filepath, rel_path) in enumerate(all_media):
        name = filepath.name
        ext = filepath.suffix.lower()

        try:
            stat = filepath.stat()
        except OSError:
            continue
        size_bytes = stat.st_size
        size_mb = round(size_bytes/(1024*1024), 2)
        mod_time = datetime.fromtimestamp(stat.st_mtime)
        is_video = ext in VIDEO_EXTENSIONS
        media_type = "video" if is_video else "image"

        exif = {}
        date_taken = None
        camera = ""
        resolution = ""
        img_width, img_height = 0, 0
        gps_lat, gps_lon = None, None

        if not is_video:
            exif = get_exif_data(str(filepath))
            date_taken = get_date_from_exif(exif)
            camera = str(exif.get('Make','')).strip()
            model = str(exif.get('Model','')).strip()
            if model: camera = f"{camera} {model}".strip()
            w2 = exif.get('ExifImageWidth') or exif.get('ImageWidth', 0)
            h2 = exif.get('ExifImageHeight') or exif.get('ImageLength', 0)
            # Convert EXIF values (may be tuples/IFDRational) to int safely
            try:
                w2 = int(w2) if w2 else 0
                h2 = int(h2) if h2 else 0
            except (ValueError, TypeError):
                w2, h2 = 0, 0
            # Fallback: read actual image dimensions via PIL if EXIF is missing
            if (not w2 or not h2) and HAS_PIL:
                try:
                    with Image.open(str(filepath)) as pil_img:
                        w2, h2 = pil_img.size
                except Exception:
                    w2, h2 = 0, 0
            if w2 and h2:
                img_width, img_height = w2, h2
                resolution = f"{img_width}x{img_height}"
            gps_info = exif.get('GPSInfo')
            if gps_info: gps_lat, gps_lon = get_gps_coords(gps_info)

        if not date_taken: date_taken = get_date_from_filename(name)
        if not date_taken: date_taken = mod_time

        thumb = ""
        sharpness_raw = 0.0
        if not is_video:
            thumb = make_thumbnail_b64(str(filepath))
            sharpness_raw = min(compute_sharpness(str(filepath)), 1000.0)

        face_count = 0
        if not is_video and face_cascade is not None:
            rects, embeddings = detect_faces_cv(str(filepath), face_cascade, profile_cascade)
            face_thumbs = extract_face_thumbs_cv(str(filepath), rects) if rects else []
            face_count = len(rects)
            if face_count > 0:
                log(f"Face: {face_count} face(s) in {rel_path}")
            file_idx = len(files)
            for fi, emb in enumerate(embeddings):
                ft = face_thumbs[fi] if fi < len(face_thumbs) else ""
                all_face_data.append((file_idx, emb, ft))

        entry = {
            "name": name,
            "path": str(filepath),
            "rel_path": rel_path,
            "type": media_type,
            "ext": ext.lstrip('.'),
            "size_mb": size_mb,
            "size_bytes": size_bytes,
            "mtime": stat.st_mtime,
            "date": date_taken.strftime("%Y-%m-%d %H:%M:%S"),
            "year": date_taken.strftime("%Y"),
            "month": date_taken.strftime("%Y-%m"),
            "day": date_taken.strftime("%Y-%m-%d"),
            "camera": camera or "Unknown",
            "resolution": resolution or "Unknown",
            "width": img_width,
            "height": img_height,
            "has_gps": gps_lat is not None,
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
            "thumb": thumb,
            "sharpness_raw": sharpness_raw,
            "quality_score": None if is_video else 0,
            "quality_label": None if is_video else "Poor",
            "sharpness": None if is_video else 0,
            "resolution_score": None if is_video else 0,
            "size_score": None if is_video else 0,
            "faces": [],
            "face_count": face_count,
            "tags": [],
        }
        files.append(entry)
        pct = int((i+1)/total_count*100) if total_count else 100
        log(f"Scanning: {pct}% ({i+1}/{total_count}) — {rel_path[:50]}")
        # Emit JSON progress to stdout every 10 files
        if (i + 1) % 10 == 0 or (i + 1) == total_count:
            emit_progress(pct, i + 1, total_count, "scanning")

    total_faces = sum(1 for f in files if f.get("face_count", 0) > 0)
    log(f"Scanned {len(files)} media files. {total_faces} with faces, {len(all_face_data)} face embeddings.")

    # ---- Quality score normalization (second pass) ----
    images = [f for f in files if f["type"] == "image"]
    if images:
        max_sharpness = min(max((f["sharpness_raw"] for f in images), default=1.0), 1000.0) or 1.0
        max_pixels = 1
        for f in images:
            res = f.get("resolution", "Unknown")
            if res and res != "Unknown":
                parts = res.split("x")
                if len(parts) == 2:
                    try:
                        px = int(parts[0]) * int(parts[1])
                        if px > max_pixels: max_pixels = px
                    except ValueError:
                        pass
        max_size = max((f["size_bytes"] for f in images), default=1) or 1

        for f in images:
            scores = compute_quality_scores(
                f["path"], f["size_bytes"], f.get("resolution", "Unknown"),
                f["sharpness_raw"], max_sharpness, max_pixels, max_size
            )
            f["quality_score"] = scores["quality_score"]
            f["quality_label"] = scores["quality_label"]
            f["sharpness"] = scores["sharpness"]
            f["resolution_score"] = scores["resolution_score"]
            f["size_score"] = scores["size_score"]

    # Remove sharpness_raw from output (internal only)
    for f in files:
        f.pop("sharpness_raw", None)

    # Load and apply photo tags (check .cache/data/ first, then root for backward compat)
    tags_path = folder / ".cache" / "data" / "photo_tags.json"
    if not tags_path.exists():
        tags_path = folder / "photo_tags.json"
    if tags_path.exists():
        try:
            with open(tags_path) as f:
                tags_map = json.load(f)
            for entry in files:
                entry["tags"] = tags_map.get(entry["rel_path"], [])
        except Exception:
            pass

    person_thumbs = {}
    if face_cascade and all_face_data:
        emit_progress(100, total_count, total_count, "clustering faces")
        log("Clustering faces...")
        file_faces, person_thumbs = cluster_faces(all_face_data)
        for file_idx, persons in file_faces.items():
            if file_idx < len(files):
                files[file_idx]["faces"] = persons

    # Load and apply name mappings
    name_map_path = folder / ".cache" / "data" / "face_names.json"
    if not name_map_path.exists():
        name_map_path = folder / "face_names.json"
    name_map = {}
    if name_map_path.exists():
        try:
            with open(name_map_path) as f: name_map = json.load(f)
        except: pass

    if name_map:
        new_thumbs = {}
        for pid, th in person_thumbs.items():
            nn = name_map.get(pid, pid)
            if nn not in new_thumbs: new_thumbs[nn] = th
        person_thumbs = new_thumbs
        for f in files:
            if f.get("faces"):
                mapped = []
                for face in f["faces"]:
                    nn = name_map.get(face, face)
                    if nn not in mapped: mapped.append(nn)
                f["faces"] = mapped

    # Duplicate detection
    duplicate_result = None
    try:
        from duplicate_detector import detect_duplicates
        dry_run = "--move-duplicates" not in sys.argv
        emit_progress(100, total_count, total_count, "detecting duplicates")
        log("Running duplicate detection...")
        duplicate_result = detect_duplicates(files, folder, threshold=10, dry_run=dry_run)
    except ImportError:
        log("Warning: duplicate_detector module not found, skipping.")
    except Exception as e:
        log(f"Warning: Duplicate detection failed: {e}")

    return files, person_thumbs, duplicate_result

if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    json_mode = "--json" in sys.argv

    folder = Path(folder).resolve()
    if not folder.is_dir():
        emit_error(f"Not a directory: {folder}")
        sys.exit(1)

    files, person_thumbs, duplicate_result = scan_folder(folder)

    emit_progress(100, len(files), len(files), "finalizing")

    result = {
        "folder": str(folder),
        "files": files,
        "person_thumbs": person_thumbs,
        "total": len(files),
        "face_images": sum(1 for f in files if f.get("face_count",0) > 0),
        "persons": len(person_thumbs),
    }

    # Attach duplicate groups to result
    if duplicate_result:
        result["duplicate_groups"] = {
            "exact": duplicate_result["exact"],
            "near": duplicate_result["near"],
        }
        result["duplicate_stats"] = duplicate_result["stats"]
        result["duplicate_moved"] = duplicate_result["moved"]

    if json_mode:
        emit_result(result)
    else:
        # Human-readable output to stderr for non-JSON mode
        log(f"Total: {len(files)} files, {result['face_images']} with faces, {result['persons']} people")
        if duplicate_result:
            s = duplicate_result["stats"]
            log(f"Duplicates: {s['exact_groups']} exact groups, "
                f"{s['near_groups']} near groups, "
                f"{s['duplicates_found']} total duplicates found")
        emit_result(result)
