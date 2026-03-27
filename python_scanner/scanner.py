#!/usr/bin/env python3
"""
Photo Scanner — scans folder, extracts EXIF + face data, outputs JSON.
Usage: python3 scanner.py /path/to/folder [--json]
"""
import os, sys, json, base64, hashlib
from datetime import datetime
from pathlib import Path
from io import BytesIO

# ---- Debug flag (env-controlled) ----
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

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

# ---- Log level system ----
def log_info(msg):
    """Always-visible info log to stderr."""
    print(f"[INFO] {msg}", file=sys.stderr, flush=True)

def log_debug(msg):
    """Debug log to stderr — only visible when DEBUG=true."""
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr, flush=True)

def log_error(msg):
    """Always-visible error log to stderr."""
    print(f"[ERROR] {msg}", file=sys.stderr, flush=True)

# ---- Numpy-safe JSON conversion ----
def convert_numpy(obj):
    """Recursively convert numpy types to native Python types for JSON serialization."""
    try:
        import numpy as np
        if isinstance(obj, dict):
            return {k: convert_numpy(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_numpy(i) for i in obj]
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    if isinstance(obj, dict):
        return {k: convert_numpy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy(i) for i in obj]
    return obj

# ---- JSON stdout helpers ----
def emit_progress(value, current, total, status="scanning"):
    """Write a progress JSON line to stdout."""
    print(json.dumps({"type": "progress", "value": value,
                       "current": current, "total": total,
                       "status": status}), flush=True)

def emit_result(data):
    """Write the final result JSON line to stdout."""
    clean_data = convert_numpy(data)
    log_debug("Converted numpy types for JSON serialization")
    print(json.dumps({"type": "result", "data": clean_data}), flush=True)

def emit_error(message):
    """Write an error JSON line to stdout."""
    print(json.dumps({"type": "error", "message": message}), flush=True)

# ---- EXIF ----
def get_exif_data(filepath):
    """Extract EXIF data using Pillow with multiple fallback strategies."""
    exif = {}
    if not HAS_PIL:
        return exif

    # Strategy 1: Pillow _getexif() (most common)
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
            if exif:
                return exif
    except Exception:
        pass

    # Strategy 2: Pillow getexif() (newer API, works with more formats)
    try:
        img = Image.open(filepath)
        exif_data = img.getexif()
        if exif_data:
            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, tag_id)
                exif[tag] = value
            # Try to get IFD GPS data from newer API
            try:
                gps_ifd = exif_data.get_ifd(0x8825)
                if gps_ifd:
                    gps = {}
                    for gps_id, value in gps_ifd.items():
                        gps[GPSTAGS.get(gps_id, gps_id)] = value
                    exif["GPSInfo"] = gps
            except Exception:
                pass
    except Exception:
        pass

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

def compute_quality_scores(size_bytes, pixels, sharpness_raw,
                           max_sharpness, max_pixels, max_size):
    """Compute normalized quality sub-scores and final weighted score."""
    # Clamp sharpness to avoid outliers
    clamped = min(sharpness_raw, 1000.0)
    sharpness = min(100, round((clamped / max_sharpness) * 100)) if max_sharpness > 0 else 0

    # Resolution: 0-100 from actual width*height pixels
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

# DNN face detector model paths (bundled with opencv)
_dnn_net = None
_dnn_loaded = False

def _get_dnn_detector():
    """Load OpenCV DNN face detector (res10 SSD) once globally."""
    global _dnn_net, _dnn_loaded
    if _dnn_loaded:
        return _dnn_net
    _dnn_loaded = True
    if not HAS_FACE:
        return None
    try:
        model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '')
        # Try bundled model first, then opencv's data path
        prototxt = None
        caffemodel = None
        # Check common locations
        for base in [model_dir, os.path.dirname(cv2.__file__), '.']:
            p = os.path.join(base, 'deploy.prototxt')
            c = os.path.join(base, 'res10_300x300_ssd_iter_140000_fp16.caffemodel')
            if os.path.exists(p) and os.path.exists(c):
                prototxt, caffemodel = p, c
                break
        if prototxt and caffemodel:
            _dnn_net = cv2.dnn.readNetFromCaffe(prototxt, caffemodel)
            log_debug(f"DNN face detector loaded from {prototxt}")
        else:
            log_debug("DNN face detector model files not found (optional fallback)")
    except Exception as e:
        log_error(f"DNN face detector failed to load: {e}")
    return _dnn_net

def _detect_faces_dnn(img):
    """Detect faces using OpenCV DNN (more accurate than Haar for selfies)."""
    net = _get_dnn_detector()
    if net is None:
        return []
    h, w = img.shape[:2]
    blob = cv2.dnn.blobFromImage(cv2.resize(img, (300, 300)), 1.0,
                                  (300, 300), (104.0, 177.0, 123.0))
    net.setInput(blob)
    detections = net.forward()
    faces = []
    for i in range(detections.shape[2]):
        confidence = detections[0, 0, i, 2]
        if confidence > 0.5:
            box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
            x1, y1, x2, y2 = box.astype(int)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 > x1 and y2 > y1:
                faces.append((x1, y1, x2 - x1, y2 - y1))
    return faces

def detect_faces_cv(filepath, face_cascade, profile_cascade):
    if not HAS_FACE or face_cascade is None:
        return [], []
    try:
        img = cv2.imread(str(filepath))
        if img is None:
            log_debug(f"cv2.imread failed for {filepath}")
            return [], []
        h, w = img.shape[:2]
        original_w, original_h = w, h
        log_debug(f"Face processing {filepath} ({original_w}x{original_h})")
        max_dim = 800
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = cv2.resize(img, (int(w*scale), int(h*scale)))
            log_debug(f"Resized for face detection: {img.shape[1]}x{img.shape[0]} (original: {original_w}x{original_h})")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        # Multi-pass Haar cascade detection
        faces = ()
        for sf, mn in [(1.1, 5), (1.05, 3), (1.15, 3), (1.05, 2)]:
            faces = face_cascade.detectMultiScale(gray, scaleFactor=sf, minNeighbors=mn, minSize=(30, 30))
            if len(faces) > 0:
                log_debug(f"Haar frontal found {len(faces)} face(s) with sf={sf},mn={mn}")
                break

        # Try profile cascade if frontal found nothing
        if len(faces) == 0 and profile_cascade is not None:
            for sf, mn in [(1.1, 5), (1.05, 3)]:
                faces = profile_cascade.detectMultiScale(gray, scaleFactor=sf, minNeighbors=mn, minSize=(30, 30))
                if len(faces) > 0:
                    log_debug(f"Haar profile found {len(faces)} face(s) with sf={sf},mn={mn}")
                    break

        # DNN fallback: much more accurate for selfies, rotated/tilted faces
        if len(faces) == 0:
            log_debug(f"Haar found 0 faces, trying DNN fallback...")
            dnn_faces = _detect_faces_dnn(img)
            if dnn_faces:
                faces = dnn_faces
                log_debug(f"DNN detected {len(faces)} face(s)")
            else:
                log_debug(f"DNN also found 0 faces")

        if len(faces) == 0:
            log_debug(f"No faces in {filepath}")
            return [], []

        log_debug(f"Found {len(faces)} face(s) in {filepath}")
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

    log_info(f"Found {total_count} media files")

    # Warn if large library
    if total_count > 3000:
        log_info(f"Large library ({total_count} files), scanning may take a while")

    face_cascade, profile_cascade = None, None
    all_face_data = []
    log_debug(f"HAS_FACE={HAS_FACE}, cv2 available={HAS_FACE}")
    if HAS_FACE:
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml'
        profile_path = cv2.data.haarcascades + 'haarcascade_profileface.xml'
        face_cascade = cv2.CascadeClassifier(cascade_path)
        profile_cascade = cv2.CascadeClassifier(profile_path)
        if face_cascade.empty():
            log_error(f"Failed to load frontal cascade from {cascade_path}")
            face_cascade = None
        else:
            log_info("Face detection enabled")
            log_debug(f"Face cascade loaded from {cascade_path}")
        if profile_cascade is not None and profile_cascade.empty():
            log_debug(f"Profile cascade failed from {profile_path}")
            profile_cascade = None
    else:
        log_info("Face detection unavailable (cv2/numpy/sklearn not installed)")

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
        camera_make = ""
        camera_model = ""
        resolution = ""
        img_width, img_height = 0, 0
        iso, exposure, focal_length, aperture = None, None, None, None
        dpi, bit_depth = None, None
        gps_lat, gps_lon = None, None

        if not is_video:
            exif = get_exif_data(str(filepath))
            date_taken = get_date_from_exif(exif)
            camera_make = str(exif.get('Make','')).strip()
            camera_model = str(exif.get('Model','')).strip()
            camera = f"{camera_make} {camera_model}".strip() if camera_model else camera_make
            # ISO
            try:
                iso_val = exif.get('ISOSpeedRatings')
                if iso_val:
                    iso = int(iso_val) if not isinstance(iso_val, (list, tuple)) else int(iso_val[0])
            except (ValueError, TypeError, IndexError):
                pass
            # Exposure time
            try:
                exp_val = exif.get('ExposureTime')
                if exp_val:
                    exp_f = float(exp_val)
                    exposure = f"1/{int(round(1/exp_f))}" if 0 < exp_f < 1 else f"{exp_f}s"
            except (ValueError, TypeError, ZeroDivisionError):
                pass
            # Focal length
            try:
                fl_val = exif.get('FocalLength')
                if fl_val:
                    focal_length = f"{float(fl_val):.1f}mm"
            except (ValueError, TypeError):
                pass
            # Aperture (FNumber)
            try:
                fn_val = exif.get('FNumber')
                if fn_val:
                    aperture = f"f/{float(fn_val):.1f}"
            except (ValueError, TypeError):
                pass
            # DPI
            try:
                xres = exif.get('XResolution')
                if xres:
                    dpi = int(float(xres))
            except (ValueError, TypeError):
                pass
            # Bit depth (BitsPerSample)
            try:
                bps = exif.get('BitsPerSample')
                if bps:
                    bit_depth = int(bps) if not isinstance(bps, (list, tuple)) else int(bps[0])
            except (ValueError, TypeError, IndexError):
                pass
            # --- Original resolution (NEVER use resized dimensions) ---
            # Priority: 1) PIL actual pixels, 2) EXIF tags
            exif_source = "none"
            w2, h2 = 0, 0

            # Best source: actual image dimensions via PIL (always accurate)
            if HAS_PIL:
                try:
                    with Image.open(str(filepath)) as pil_img:
                        w2, h2 = pil_img.size
                        exif_source = "PIL"
                except Exception:
                    w2, h2 = 0, 0

            # Fallback: EXIF dimension tags
            if not w2 or not h2:
                w2 = exif.get('ExifImageWidth') or exif.get('ImageWidth', 0)
                h2 = exif.get('ExifImageHeight') or exif.get('ImageLength', 0)
                try:
                    w2 = int(w2) if w2 else 0
                    h2 = int(h2) if h2 else 0
                    if w2 and h2:
                        exif_source = "EXIF"
                except (ValueError, TypeError):
                    w2, h2 = 0, 0

            if w2 and h2:
                img_width, img_height = w2, h2
                resolution = f"{img_width}x{img_height}"

            gps_info = exif.get('GPSInfo')
            if gps_info: gps_lat, gps_lon = get_gps_coords(gps_info)

            # Log original resolution (first 5 images, debug only)
            if i < 5:
                log_debug(f"Resolution: {img_width}x{img_height} (source: {exif_source}) - {rel_path}")
                log_debug(f"EXIF: camera={camera}, iso={iso}, exposure={exposure}, "
                          f"aperture={aperture}, focal={focal_length}, dpi={dpi}, "
                          f"gps={gps_lat},{gps_lon}")

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
                log_debug(f"Face: {face_count} face(s) in {rel_path}")
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
            "camera_make": camera_make or None,
            "camera_model": camera_model or None,
            "resolution": resolution or "Unknown",
            "width": img_width,
            "height": img_height,
            "dpi": dpi,
            "bit_depth": bit_depth,
            "iso": iso if not is_video else None,
            "exposure": exposure if not is_video else None,
            "aperture": aperture if not is_video else None,
            "focal_length": focal_length if not is_video else None,
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
        # Emit JSON progress to stdout every 10 files
        if (i + 1) % 10 == 0 or (i + 1) == total_count:
            log_info(f"[SCAN] {pct}% ({i+1}/{total_count})")
            emit_progress(pct, i + 1, total_count, "scanning")

    total_faces = sum(1 for f in files if f.get("face_count", 0) > 0)
    log_info(f"Scanned {len(files)} files. Faces detected: {total_faces} images, {len(all_face_data)} embeddings")

    # ---- Quality score normalization (second pass) ----
    images = [f for f in files if f["type"] == "image"]
    if images:
        max_sharpness = min(max((f["sharpness_raw"] for f in images), default=1.0), 1000.0) or 1.0
        max_pixels = max((f["width"] * f["height"] for f in images if f["width"] > 0 and f["height"] > 0), default=1) or 1
        max_size = max((f["size_bytes"] for f in images), default=1) or 1

        for f in images:
            px = f["width"] * f["height"] if f["width"] > 0 and f["height"] > 0 else 0
            scores = compute_quality_scores(
                f["size_bytes"], px,
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
        log_info("Clustering faces...")
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
        log_info("Running duplicate detection...")
        duplicate_result = detect_duplicates(files, folder, threshold=10, dry_run=dry_run)
    except ImportError:
        log_info("Duplicate detector module not found, skipping")
    except Exception as e:
        log_error(f"Duplicate detection failed: {e}")

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

    log_info(f"Complete: {len(files)} files, {result['face_images']} with faces, {result['persons']} people")
    if duplicate_result:
        s = duplicate_result["stats"]
        log_info(f"Duplicate groups found: {s['exact_groups']} exact, "
                 f"{s['near_groups']} near, {s['duplicates_found']} total duplicates")

    emit_result(result)
