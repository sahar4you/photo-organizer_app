#!/usr/bin/env python3
"""
Photo Organizer — Google Photos-style HTML viewer with filters.
Usage: python3 photo_organizer.py [folder_path]
       If no folder_path given, uses the current directory.
Generates: photo_gallery.html in the target folder.
"""

import os
import sys
import json
import base64
import hashlib
from datetime import datetime
from pathlib import Path
from io import BytesIO

try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("⚠ Pillow not installed. Run: pip install Pillow")
    print("  Continuing without EXIF support...\n")

# NEW: Face detection imports
try:
    import cv2
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering
    HAS_FACE = True
except ImportError:
    HAS_FACE = False
    print("⚠ Face detection requires: pip install opencv-python-headless scikit-learn")
    print("  Continuing without face detection...\n")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.heic'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.3gp'}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
THUMB_SIZE = (300, 300)

# ---------------------------------------------------------------------------
# EXIF helpers
# ---------------------------------------------------------------------------
def get_exif_data(filepath):
    """Extract EXIF metadata from an image file."""
    exif = {}
    if not HAS_PIL:
        return exif
    try:
        img = Image.open(filepath)
        raw = img._getexif()
        if raw:
            for tag_id, value in raw.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag == "GPSInfo":
                    gps = {}
                    for gps_id in value:
                        gps_tag = GPSTAGS.get(gps_id, gps_id)
                        gps[gps_tag] = value[gps_id]
                    exif["GPSInfo"] = gps
                else:
                    exif[tag] = value
    except Exception:
        pass
    return exif


def get_gps_coords(gps_info):
    """Convert GPS EXIF to decimal lat/lon."""
    try:
        def to_decimal(coord, ref):
            d, m, s = [float(x) for x in coord]
            dec = d + m / 60 + s / 3600
            if ref in ('S', 'W'):
                dec = -dec
            return round(dec, 6)
        lat = to_decimal(gps_info['GPSLatitude'], gps_info['GPSLatitudeRef'])
        lon = to_decimal(gps_info['GPSLongitude'], gps_info['GPSLongitudeRef'])
        return lat, lon
    except Exception:
        return None, None


def get_date_from_exif(exif):
    """Try to extract date from EXIF DateTimeOriginal or DateTime."""
    for key in ('DateTimeOriginal', 'DateTime', 'DateTimeDigitized'):
        val = exif.get(key)
        if val:
            try:
                return datetime.strptime(str(val).strip(), "%Y:%m:%d %H:%M:%S")
            except Exception:
                pass
    return None


def get_date_from_filename(filename):
    """Try to parse date from filename like 20250507_121643.jpg."""
    name = Path(filename).stem.split(' ')[0]  # strip " - Copy" etc.
    for fmt in ("%Y%m%d_%H%M%S", "%Y%m%d", "%Y-%m-%d_%H-%M-%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(name[:len(fmt.replace('%', '').replace('-', '').replace('_', '')) + name.count('-') + name.count('_')], fmt)
        except Exception:
            pass
    # fallback: try first 15 chars
    try:
        return datetime.strptime(name[:15], "%Y%m%d_%H%M%S")
    except Exception:
        pass
    return None


def make_thumbnail_b64(filepath):
    """Generate a small base64 JPEG thumbnail for embedding in HTML."""
    if not HAS_PIL:
        return ""
    try:
        img = Image.open(filepath)
        img.thumbnail(THUMB_SIZE)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        buf = BytesIO()
        img.save(buf, format='JPEG', quality=60)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# NEW: Face Detection & Clustering
# ---------------------------------------------------------------------------
def detect_faces_cv(filepath, face_cascade, profile_cascade):
    """Detect faces using OpenCV Haar cascades. Returns list of (x,y,w,h) rects and LBP histograms as embeddings."""
    if not HAS_FACE:
        return [], []
    try:
        img = cv2.imread(str(filepath))
        if img is None:
            return [], []
        h, w = img.shape[:2]
        max_dim = 800
        scale = 1.0
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        # Detect frontal faces
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        if len(faces) == 0:
            # Try profile faces
            faces = profile_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        if len(faces) == 0:
            return [], []

        rects = []
        embeddings = []
        for (fx, fy, fw, fh) in faces:
            rects.append((fx, fy, fw, fh))
            face_roi = gray[fy:fy+fh, fx:fx+fw]
            face_resized = cv2.resize(face_roi, (128, 128))
            hist_vec = []
            # 1) 8x8 spatial grid intensity histograms (512-d)
            for gy in range(8):
                for gx in range(8):
                    block = face_resized[gy*16:(gy+1)*16, gx*16:(gx+1)*16]
                    hist = cv2.calcHist([block], [0], None, [8], [0, 256]).flatten()
                    hist = hist / (hist.sum() + 1e-7)
                    hist_vec.extend(hist)
            # 2) Horizontal edge features via Sobel (structural shape)
            sobel_x = cv2.Sobel(face_resized, cv2.CV_64F, 1, 0, ksize=3)
            sobel_y = cv2.Sobel(face_resized, cv2.CV_64F, 0, 1, ksize=3)
            for gy in range(4):
                for gx in range(4):
                    bx = sobel_x[gy*32:(gy+1)*32, gx*32:(gx+1)*32]
                    by = sobel_y[gy*32:(gy+1)*32, gx*32:(gx+1)*32]
                    mag = np.sqrt(bx**2 + by**2).flatten()
                    h = cv2.calcHist([mag.astype(np.float32)], [0], None, [8], [0, mag.max()+1]).flatten()
                    h = h / (h.sum() + 1e-7)
                    hist_vec.extend(h)
            # 3) Global proportions: eye-line, nose-line, mouth-line ratios
            third_h = face_resized.shape[0] // 3
            for t in range(3):
                strip = face_resized[t*third_h:(t+1)*third_h, :]
                m = strip.mean() / 255.0
                s = strip.std() / 255.0
                hist_vec.extend([m, s])
            embeddings.append(hist_vec)

        return rects, embeddings
    except Exception:
        return [], []


def extract_face_thumbs_cv(filepath, rects):
    """Extract face thumbnail crops as base64 from detected rects."""
    if not HAS_PIL:
        return []
    try:
        img = cv2.imread(str(filepath))
        if img is None:
            return []
        h, w = img.shape[:2]
        max_dim = 800
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))

        thumbs = []
        for (fx, fy, fw, fh) in rects:
            # Add padding
            pad = int(fw * 0.2)
            x1 = max(0, fx - pad)
            y1 = max(0, fy - pad)
            x2 = min(img.shape[1], fx + fw + pad)
            y2 = min(img.shape[0], fy + fh + pad)
            crop = img[y1:y2, x1:x2]
            rgb_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb_crop)
            pil_img.thumbnail((80, 80))
            buf = BytesIO()
            pil_img.save(buf, format='JPEG', quality=70)
            thumbs.append(base64.b64encode(buf.getvalue()).decode())
        return thumbs
    except Exception:
        return []


def cluster_faces(all_face_data, n_target=None):
    """
    Cluster face embeddings using Agglomerative Clustering.
    Much better at grouping the same person vs DBSCAN.
    """
    if not all_face_data:
        return {}, {}

    embeddings = np.array([d[1] for d in all_face_data])

    # Normalize
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embeddings = embeddings / norms

    # Use Agglomerative with cosine affinity — much better for histogram features
    # distance_threshold controls how aggressively we merge (higher = fewer clusters)
    if len(embeddings) < 2:
        labels = np.array([0])
    else:
        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=0.45,
            metric='cosine',
            linkage='average'
        ).fit(embeddings)
        labels = clustering.labels_

    # Build file_index -> person labels mapping
    file_faces = {}
    person_thumbs = {}

    for i, (file_idx, _, face_thumb) in enumerate(all_face_data):
        label = int(labels[i])
        person_name = f"Person {label + 1}"

        if file_idx not in file_faces:
            file_faces[file_idx] = []
        if person_name not in file_faces[file_idx]:
            file_faces[file_idx].append(person_name)

        if person_name not in person_thumbs and face_thumb:
            person_thumbs[person_name] = face_thumb

    return file_faces, person_thumbs


def load_name_mappings(folder):
    """Load saved person name mappings from face_names.json."""
    path = Path(folder) / "face_names.json"
    if path.exists():
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def apply_name_mappings(files, person_thumbs, name_map):
    """Apply saved name mappings (renames + merges) to file data."""
    if not name_map:
        return files, person_thumbs

    # name_map format: {"Person 3": "Pooja", "Person 5": "Pooja", ...}
    # This renames AND merges (multiple keys -> same name = merge)

    new_thumbs = {}
    for pid, thumb in person_thumbs.items():
        new_name = name_map.get(pid, pid)
        if new_name not in new_thumbs:
            new_thumbs[new_name] = thumb

    for f in files:
        if f.get("faces"):
            mapped = []
            for face in f["faces"]:
                new_name = name_map.get(face, face)
                if new_name not in mapped:
                    mapped.append(new_name)
            f["faces"] = mapped

    return files, new_thumbs


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------
def scan_folder(folder, enable_faces=True):
    """Scan folder for media files and extract metadata."""
    folder = Path(folder).resolve()
    files = []
    all_items = sorted(os.listdir(folder))

    # NEW: Init face detection
    face_cascade = None
    profile_cascade = None
    all_face_data = []  # (file_index, embedding, face_thumb)
    if enable_faces and HAS_FACE:
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml')
        profile_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_profileface.xml')

    for i, name in enumerate(all_items):
        filepath = folder / name
        if not filepath.is_file():
            continue
        ext = filepath.suffix.lower()
        if ext not in MEDIA_EXTENSIONS:
            continue

        stat = filepath.stat()
        size_bytes = stat.st_size
        size_mb = round(size_bytes / (1024 * 1024), 2)
        mod_time = datetime.fromtimestamp(stat.st_mtime)
        is_video = ext in VIDEO_EXTENSIONS
        media_type = "video" if is_video else "image"

        # Date
        exif = {}
        date_taken = None
        camera = ""
        resolution = ""
        gps_lat, gps_lon = None, None

        if not is_video:
            exif = get_exif_data(str(filepath))
            date_taken = get_date_from_exif(exif)
            camera = str(exif.get('Make', '')).strip()
            model = str(exif.get('Model', '')).strip()
            if model:
                camera = f"{camera} {model}".strip()
            w = exif.get('ExifImageWidth') or exif.get('ImageWidth', '')
            h = exif.get('ExifImageHeight') or exif.get('ImageLength', '')
            if w and h:
                resolution = f"{w}x{h}"
            gps_info = exif.get('GPSInfo')
            if gps_info:
                gps_lat, gps_lon = get_gps_coords(gps_info)

        if not date_taken:
            date_taken = get_date_from_filename(name)
        if not date_taken:
            date_taken = mod_time

        # Thumbnail (images only, skip for video)
        thumb = ""
        if not is_video:
            thumb = make_thumbnail_b64(str(filepath))

        # NEW: Face detection
        face_count = 0
        if not is_video and face_cascade is not None:
            rects, embeddings = detect_faces_cv(str(filepath), face_cascade, profile_cascade)
            face_thumbs = extract_face_thumbs_cv(str(filepath), rects) if rects else []
            face_count = len(rects)
            file_idx = len(files)
            for fi, emb in enumerate(embeddings):
                ft = face_thumbs[fi] if fi < len(face_thumbs) else ""
                all_face_data.append((file_idx, emb, ft))

        entry = {
            "name": name,
            "path": name,  # relative
            "type": media_type,
            "ext": ext.lstrip('.'),
            "size_mb": size_mb,
            "size_bytes": size_bytes,
            "date": date_taken.strftime("%Y-%m-%d %H:%M:%S"),
            "year": date_taken.strftime("%Y"),
            "month": date_taken.strftime("%Y-%m"),
            "day": date_taken.strftime("%Y-%m-%d"),
            "camera": camera if camera else "Unknown",
            "resolution": resolution if resolution else "Unknown",
            "has_gps": gps_lat is not None,
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
            "thumb": thumb,
            "faces": [],
            "face_count": face_count,
        }
        files.append(entry)
        pct = int((i + 1) / len(all_items) * 100)
        print(f"\r  Scanning: {pct}% ({i+1}/{len(all_items)}) — {name[:40]}", end="", flush=True)

    print(f"\r  Scanned {len(files)} media files from {len(all_items)} total items.       ")

    # NEW: Cluster faces across all images
    if face_cascade is not None and all_face_data:
        print("  🧑 Clustering faces...")
        file_faces, person_thumbs = cluster_faces(all_face_data)
        for file_idx, persons in file_faces.items():
            if file_idx < len(files):
                files[file_idx]["faces"] = persons
        # Attach person_thumbs to return
        return files, person_thumbs
    return files, {}


# ---------------------------------------------------------------------------
# HTML Generator
# ---------------------------------------------------------------------------
def generate_html(files, folder, person_thumbs=None):
    folder = Path(folder).resolve()
    person_thumbs = person_thumbs or {}
    data_json = json.dumps(files)
    person_thumbs_json = json.dumps(person_thumbs)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Photo Gallery — {folder.name}</title>
<style>
  :root {{
    --bg: #121212; --surface: #1e1e1e; --card: #252525;
    --text: #e0e0e0; --text2: #999; --accent: #4fc3f7; --accent2: #81c784;
    --border: #333; --hover: #2a2a2a;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:var(--bg); color:var(--text); }}

  /* Layout: sidebar + main */
  .app-layout {{ display:flex; height:100vh; overflow:hidden; }}

  /* Left Sidebar */
  .sidebar {{ width:240px; min-width:240px; background:var(--surface); border-right:1px solid var(--border); display:flex; flex-direction:column; height:100vh; overflow-y:auto; }}
  .sidebar-header {{ padding:20px 16px 12px; border-bottom:1px solid var(--border); }}
  .sidebar-header h1 {{ font-size:18px; font-weight:600; }}
  .sidebar-header .subtitle {{ color:var(--text2); font-size:11px; margin-top:4px; }}
  .sidebar-filters {{ padding:12px 16px; flex:1; overflow-y:auto; }}
  .filter-group {{ margin-bottom:14px; }}
  .filter-group label {{ display:block; font-size:11px; color:var(--text2); text-transform:uppercase; letter-spacing:0.6px; margin-bottom:5px; font-weight:600; }}
  select, input[type=text] {{ width:100%; background:var(--card); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:7px 10px; font-size:13px; outline:none; }}
  select:focus, input:focus {{ border-color:var(--accent); }}
  .sidebar-actions {{ padding:12px 16px; border-top:1px solid var(--border); display:flex; flex-direction:column; gap:8px; }}
  .reset-btn {{ background:transparent; color:var(--accent); border:1px solid var(--accent); border-radius:6px; padding:7px 14px; font-size:13px; cursor:pointer; text-align:center; }}
  .reset-btn:hover {{ background:var(--accent); color:#000; }}
  .stats {{ font-size:12px; color:var(--text2); text-align:center; }}

  /* View toggle */
  .view-toggle {{ display:flex; gap:4px; justify-content:center; }}
  .view-toggle button {{ background:var(--card); color:var(--text2); border:1px solid var(--border); padding:5px 12px; cursor:pointer; font-size:12px; border-radius:4px; }}
  .view-toggle button.active {{ background:var(--accent); color:#000; border-color:var(--accent); }}

  /* Main content */
  .main-content {{ flex:1; overflow-y:auto; }}

  /* Grid */
  .gallery {{ padding:16px 24px; }}
  .date-group {{ margin-bottom:24px; }}
  .date-group h2 {{ font-size:15px; color:var(--accent); margin-bottom:10px; font-weight:500; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(180px, 1fr)); gap:8px; }}
  .grid.large {{ grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); }}
  .grid.small {{ grid-template-columns:repeat(auto-fill, minmax(120px, 1fr)); }}

  /* Card */
  .card {{ background:var(--card); border-radius:8px; overflow:hidden; cursor:pointer; transition:transform 0.15s, box-shadow 0.15s; position:relative; }}
  .card:hover {{ transform:translateY(-2px); box-shadow:0 4px 20px rgba(0,0,0,0.4); }}
  .card img {{ width:100%; aspect-ratio:1; object-fit:cover; display:block; background:var(--surface); }}
  .card .video-badge {{ position:absolute; top:8px; right:8px; background:rgba(0,0,0,0.7); color:#fff; padding:2px 8px; border-radius:4px; font-size:11px; }}
  .card .info {{ padding:8px 10px; }}
  .card .info .name {{ font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  .card .info .meta {{ font-size:11px; color:var(--text2); margin-top:2px; }}

  /* Lightbox */
  .lightbox {{ display:none; position:fixed; top:0; left:0; width:100vw; height:100vh; background:rgba(0,0,0,0.95); z-index:200; justify-content:center; align-items:center; flex-direction:column; }}
  .lightbox.open {{ display:flex; }}
  .lightbox img, .lightbox video {{ max-width:90vw; max-height:75vh; border-radius:8px; }}
  .lightbox .lb-info {{ color:var(--text); padding:16px; text-align:center; max-width:600px; }}
  .lightbox .lb-info .lb-name {{ font-size:16px; font-weight:600; }}
  .lightbox .lb-info .lb-meta {{ font-size:13px; color:var(--text2); margin-top:6px; line-height:1.6; }}
  .lightbox .lb-close {{ position:absolute; top:16px; right:24px; font-size:28px; color:var(--text); cursor:pointer; background:none; border:none; }}
  .lightbox .lb-nav {{ position:absolute; top:50%; transform:translateY(-50%); font-size:36px; color:var(--text); cursor:pointer; background:rgba(0,0,0,0.5); border:none; padding:8px 14px; border-radius:8px; }}
  .lightbox .lb-prev {{ left:16px; }}
  .lightbox .lb-next {{ right:16px; }}

  /* No results */
  .no-results {{ text-align:center; padding:60px; color:var(--text2); font-size:16px; }}

  /* Face management modal */
  .modal-overlay {{ display:none; position:fixed; top:0; left:0; width:100vw; height:100vh; background:rgba(0,0,0,0.8); z-index:300; justify-content:center; align-items:center; }}
  .modal-overlay.open {{ display:flex; }}
  .modal {{ background:var(--surface); border-radius:12px; padding:24px; width:400px; max-width:90vw; max-height:80vh; overflow-y:auto; }}
  .modal h3 {{ font-size:16px; margin-bottom:16px; }}
  .modal .face-row {{ display:flex; align-items:center; gap:10px; padding:8px; border-bottom:1px solid var(--border); }}
  .modal .face-row img {{ width:44px; height:44px; border-radius:50%; object-fit:cover; }}
  .modal .face-row input {{ flex:1; background:var(--card); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:6px 10px; font-size:13px; }}
  .modal .face-row .face-id {{ font-size:11px; color:var(--text2); min-width:70px; }}
  .modal-actions {{ margin-top:16px; display:flex; gap:8px; justify-content:flex-end; }}
  .modal-actions button {{ padding:8px 16px; border-radius:6px; font-size:13px; cursor:pointer; border:none; }}
  .btn-save {{ background:var(--accent); color:#000; font-weight:600; }}
  .btn-cancel {{ background:var(--card); color:var(--text); border:1px solid var(--border) !important; }}
  .merge-hint {{ font-size:11px; color:var(--accent2); margin-bottom:12px; padding:8px; background:rgba(129,199,132,0.1); border-radius:6px; }}

  /* Sidebar toggle for mobile */
  .sidebar-toggle {{ display:none; position:fixed; bottom:16px; left:16px; z-index:150; background:var(--accent); color:#000; border:none; border-radius:50%; width:48px; height:48px; font-size:20px; cursor:pointer; box-shadow:0 2px 12px rgba(0,0,0,0.5); }}

  @media (max-width:768px) {{
    .sidebar {{ position:fixed; left:-260px; top:0; z-index:150; transition:left 0.3s; box-shadow:4px 0 20px rgba(0,0,0,0.5); }}
    .sidebar.open {{ left:0; }}
    .sidebar-toggle {{ display:block; }}
    .grid {{ grid-template-columns:repeat(auto-fill, minmax(140px, 1fr)); }}
  }}
</style>
</head>
<body>

<div class="app-layout">

<!-- MODIFIED: Left Sidebar Navigation -->
<aside class="sidebar" id="sidebar">
  <div class="sidebar-header">
    <h1>📸 Gallery</h1>
    <div class="subtitle">{folder.name}</div>
  </div>
  <div class="sidebar-filters">
    <div class="filter-group">
      <label>Search</label>
      <input type="text" id="searchBox" placeholder="File name...">
    </div>
    <div class="filter-group">
      <label>Date</label>
      <select id="filterMonth"><option value="">All Dates</option></select>
    </div>
    <div class="filter-group">
      <label>Type</label>
      <select id="filterType">
        <option value="">All Types</option>
        <option value="image">Images</option>
        <option value="video">Videos</option>
      </select>
    </div>
    <div class="filter-group">
      <label>Size</label>
      <select id="filterSize">
        <option value="">All Sizes</option>
        <option value="small">&lt; 1 MB</option>
        <option value="medium">1-5 MB</option>
        <option value="large">5-20 MB</option>
        <option value="huge">&gt; 20 MB</option>
      </select>
    </div>
    <div class="filter-group">
      <label>Camera</label>
      <select id="filterCamera"><option value="">All Cameras</option></select>
    </div>
    <div class="filter-group">
      <label>Resolution</label>
      <select id="filterRes"><option value="">All Resolutions</option></select>
    </div>
    <div class="filter-group">
      <label>👤 Person / Face</label>
      <select id="filterFace"><option value="">All People</option><option value="__has_face__">Has Faces</option><option value="__no_face__">No Faces</option></select>
    </div>
    <div id="faceAvatars" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;"></div>
    <button onclick="openFaceManager()" style="width:100%;background:var(--card);color:var(--accent);border:1px solid var(--border);border-radius:6px;padding:6px;font-size:12px;cursor:pointer;margin-bottom:14px;">✏️ Rename / Merge Faces</button>
    <div class="filter-group">
      <label>Sort</label>
      <select id="sortBy">
        <option value="date_desc">Newest First</option>
        <option value="date_asc">Oldest First</option>
        <option value="name_asc">Name A-Z</option>
        <option value="size_desc">Largest First</option>
        <option value="size_asc">Smallest First</option>
      </select>
    </div>
    <div class="filter-group">
      <label>Grid Size</label>
      <div class="view-toggle">
        <button onclick="setGrid('small')" id="vSmall">S</button>
        <button onclick="setGrid('')" id="vMed" class="active">M</button>
        <button onclick="setGrid('large')" id="vLarge">L</button>
      </div>
    </div>
  </div>
  <div class="sidebar-actions">
    <div class="stats" id="stats"></div>
    <button class="reset-btn" onclick="resetFilters()">Reset All Filters</button>
  </div>
</aside>

<!-- Main Content -->
<main class="main-content">
  <div class="gallery" id="gallery"></div>
</main>

</div>

<!-- Mobile sidebar toggle -->
<button class="sidebar-toggle" id="sidebarToggle" onclick="document.getElementById('sidebar').classList.toggle('open')">☰</button>

<!-- Face Manager Modal -->
<div class="modal-overlay" id="faceModal">
  <div class="modal">
    <h3>👤 Rename & Merge Faces</h3>
    <div class="merge-hint">💡 Type the <b>same name</b> for multiple persons to merge them.<br>Changes apply <b>instantly</b> in the gallery. Save downloads <b>face_names.json</b> — place it in the photo folder for permanent changes.</div>
    <div id="faceManagerRows"></div>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeFaceManager()">Cancel</button>
      <button class="btn-save" onclick="saveFaceNames()">Save Names</button>
    </div>
  </div>
</div>

<!-- Lightbox -->
<div class="lightbox" id="lightbox">
  <button class="lb-close" onclick="closeLightbox()">&times;</button>
  <button class="lb-nav lb-prev" onclick="navLightbox(-1)">&#8249;</button>
  <button class="lb-nav lb-next" onclick="navLightbox(1)">&#8250;</button>
  <div id="lbMedia"></div>
  <div class="lb-info">
    <div class="lb-name" id="lbName"></div>
    <div class="lb-meta" id="lbMeta"></div>
  </div>
</div>

<script>
const DATA = {data_json};
const PERSON_THUMBS = {person_thumbs_json};
// NEW: Track original person IDs for cumulative renames
const ORIG_IDS = {{}};
DATA.forEach(f => (f.faces||[]).forEach(p => {{ ORIG_IDS[p] = p; }}));
let allNameMaps = {{}};
let filtered = [];
let currentLbIndex = -1;
let gridSize = '';

// Populate filter dropdowns
function populateFilters() {{
  const months = [...new Set(DATA.map(f => f.month))].sort().reverse();
  const cameras = [...new Set(DATA.map(f => f.camera))].sort();
  const resolutions = [...new Set(DATA.map(f => f.resolution))].filter(r => r !== 'Unknown').sort();

  const mSel = document.getElementById('filterMonth');
  months.forEach(m => {{ const o = document.createElement('option'); o.value = m; o.textContent = m; mSel.appendChild(o); }});

  const cSel = document.getElementById('filterCamera');
  cameras.forEach(c => {{ const o = document.createElement('option'); o.value = c; o.textContent = c; cSel.appendChild(o); }});

  const rSel = document.getElementById('filterRes');
  resolutions.forEach(r => {{ const o = document.createElement('option'); o.value = r; o.textContent = r; rSel.appendChild(o); }});

  // NEW: Populate face/person filter
  const persons = [...new Set(DATA.flatMap(f => f.faces || []))].filter(p => p !== 'Unknown').sort((a,b) => {{
    const na = parseInt(a.replace('Person ','')) || 0;
    const nb = parseInt(b.replace('Person ','')) || 0;
    return na - nb;
  }});
  const fSel = document.getElementById('filterFace');
  persons.forEach(p => {{ const o = document.createElement('option'); o.value = p; o.textContent = p; fSel.appendChild(o); }});

  // NEW: Render face avatar chips
  const avatarDiv = document.getElementById('faceAvatars');
  persons.forEach(p => {{
    const thumb = PERSON_THUMBS[p];
    const chip = document.createElement('div');
    chip.style.cssText = 'cursor:pointer;text-align:center;border-radius:8px;padding:4px;border:2px solid transparent;transition:border-color 0.2s;';
    chip.title = p;
    chip.onclick = () => {{ document.getElementById('filterFace').value = p; applyFilters(); }};
    if (thumb) {{
      chip.innerHTML = `<img src="data:image/jpeg;base64,${{thumb}}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;display:block;"><div style="font-size:10px;color:var(--text2);margin-top:2px;">${{p.replace('Person ','')}}</div>`;
    }} else {{
      chip.innerHTML = `<div style="width:40px;height:40px;border-radius:50%;background:var(--card);display:flex;align-items:center;justify-content:center;font-size:16px;">👤</div><div style="font-size:10px;color:var(--text2);margin-top:2px;">${{p.replace('Person ','')}}</div>`;
    }}
    avatarDiv.appendChild(chip);
  }});
}}

function matchSize(mb, filter) {{
  if (!filter) return true;
  if (filter === 'small') return mb < 1;
  if (filter === 'medium') return mb >= 1 && mb < 5;
  if (filter === 'large') return mb >= 5 && mb < 20;
  if (filter === 'huge') return mb >= 20;
  return true;
}}

function applyFilters() {{
  const search = document.getElementById('searchBox').value.toLowerCase();
  const month = document.getElementById('filterMonth').value;
  const type = document.getElementById('filterType').value;
  const size = document.getElementById('filterSize').value;
  const camera = document.getElementById('filterCamera').value;
  const res = document.getElementById('filterRes').value;
  const face = document.getElementById('filterFace').value;
  const sort = document.getElementById('sortBy').value;

  filtered = DATA.filter(f => {{
    if (search && !f.name.toLowerCase().includes(search)) return false;
    if (month && f.month !== month) return false;
    if (type && f.type !== type) return false;
    if (!matchSize(f.size_mb, size)) return false;
    if (camera && f.camera !== camera) return false;
    if (res && f.resolution !== res) return false;
    // NEW: Face filter
    if (face === '__has_face__' && (!f.faces || f.faces.length === 0)) return false;
    if (face === '__no_face__' && f.faces && f.faces.length > 0) return false;
    if (face && face !== '__has_face__' && face !== '__no_face__' && (!f.faces || !f.faces.includes(face))) return false;
    return true;
  }});

  // Sort
  filtered.sort((a, b) => {{
    if (sort === 'date_desc') return b.date.localeCompare(a.date);
    if (sort === 'date_asc') return a.date.localeCompare(b.date);
    if (sort === 'name_asc') return a.name.localeCompare(b.name);
    if (sort === 'size_desc') return b.size_bytes - a.size_bytes;
    if (sort === 'size_asc') return a.size_bytes - b.size_bytes;
    return 0;
  }});

  render();
}}

function render() {{
  const gallery = document.getElementById('gallery');
  const stats = document.getElementById('stats');
  stats.textContent = `${{filtered.length}} of ${{DATA.length}} files`;

  if (filtered.length === 0) {{
    gallery.innerHTML = '<div class="no-results">No files match your filters.</div>';
    return;
  }}

  // Group by day
  const groups = {{}};
  filtered.forEach(f => {{
    if (!groups[f.day]) groups[f.day] = [];
    groups[f.day].push(f);
  }});

  let html = '';
  Object.keys(groups).sort().reverse().forEach(day => {{
    html += `<div class="date-group"><h2>${{day}} &mdash; ${{groups[day].length}} files</h2><div class="grid ${{gridSize}}">`;
    groups[day].forEach(f => {{
      const idx = filtered.indexOf(f);
      const thumbSrc = f.thumb ? `data:image/jpeg;base64,${{f.thumb}}` : '';
      const placeholder = f.type === 'video'
        ? `<div style="width:100%;aspect-ratio:1;background:var(--surface);display:flex;align-items:center;justify-content:center;font-size:40px;">🎬</div>`
        : `<div style="width:100%;aspect-ratio:1;background:var(--surface);display:flex;align-items:center;justify-content:center;font-size:40px;">🖼</div>`;
      const imgTag = thumbSrc ? `<img src="${{thumbSrc}}" alt="${{f.name}}" loading="lazy">` : placeholder;

      const faceBadge = f.face_count > 0 ? `<div style="position:absolute;top:8px;left:8px;background:rgba(0,0,0,0.7);color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;">👤 ${{f.face_count}}</div>` : '';
      html += `<div class="card" onclick="openLightbox(${{idx}})">
        ${{imgTag}}
        ${{f.type === 'video' ? '<div class="video-badge">VIDEO</div>' : ''}}
        ${{faceBadge}}
        <div class="info">
          <div class="name" title="${{f.name}}">${{f.name}}</div>
          <div class="meta">${{f.size_mb}} MB &bull; ${{f.camera !== 'Unknown' ? f.camera : f.ext.toUpperCase()}}</div>
        </div>
      </div>`;
    }});
    html += '</div></div>';
  }});
  gallery.innerHTML = html;
}}

// Lightbox
function openLightbox(idx) {{
  currentLbIndex = idx;
  const f = filtered[idx];
  const lb = document.getElementById('lightbox');
  const media = document.getElementById('lbMedia');
  const name = document.getElementById('lbName');
  const meta = document.getElementById('lbMeta');

  if (f.type === 'video') {{
    media.innerHTML = `<video src="${{f.path}}" controls autoplay style="max-width:90vw;max-height:75vh;border-radius:8px;"></video>`;
  }} else {{
    media.innerHTML = `<img src="${{f.path}}" style="max-width:90vw;max-height:75vh;border-radius:8px;">`;
  }}

  name.textContent = f.name;
  let metaHtml = `${{f.date}} &bull; ${{f.size_mb}} MB &bull; ${{f.ext.toUpperCase()}}`;
  if (f.camera !== 'Unknown') metaHtml += `<br>Camera: ${{f.camera}}`;
  if (f.resolution !== 'Unknown') metaHtml += ` &bull; ${{f.resolution}}`;
  if (f.faces && f.faces.length > 0) metaHtml += `<br>👤 ${{f.faces.join(', ')}}`;
  if (f.has_gps) metaHtml += `<br>📍 <a href="https://maps.google.com/?q=${{f.gps_lat}},${{f.gps_lon}}" target="_blank" style="color:var(--accent)">View on Map</a>`;
  meta.innerHTML = metaHtml;

  lb.classList.add('open');
  document.body.style.overflow = 'hidden';
}}

function closeLightbox() {{
  document.getElementById('lightbox').classList.remove('open');
  document.body.style.overflow = '';
  const v = document.querySelector('#lbMedia video');
  if (v) v.pause();
}}

function navLightbox(dir) {{
  let next = currentLbIndex + dir;
  if (next < 0) next = filtered.length - 1;
  if (next >= filtered.length) next = 0;
  openLightbox(next);
}}

// Keyboard navigation
document.addEventListener('keydown', e => {{
  if (!document.getElementById('lightbox').classList.contains('open')) return;
  if (e.key === 'Escape') closeLightbox();
  if (e.key === 'ArrowLeft') navLightbox(-1);
  if (e.key === 'ArrowRight') navLightbox(1);
}});

function setGrid(size) {{
  gridSize = size;
  document.querySelectorAll('.view-toggle button').forEach(b => b.classList.remove('active'));
  if (size === 'small') document.getElementById('vSmall').classList.add('active');
  else if (size === 'large') document.getElementById('vLarge').classList.add('active');
  else document.getElementById('vMed').classList.add('active');
  render();
}}

// Face manager
function openFaceManager() {{
  const rows = document.getElementById('faceManagerRows');
  rows.innerHTML = '';
  const persons = [...new Set(DATA.flatMap(f => f.faces || []))].filter(p => p !== 'Unknown').sort((a,b) => {{
    const na = parseInt(a.replace('Person ','')) || 0;
    const nb = parseInt(b.replace('Person ','')) || 0;
    return na - nb;
  }});
  const imgCount = {{}};
  DATA.forEach(f => {{ (f.faces||[]).forEach(p => {{ imgCount[p] = (imgCount[p]||0) + 1; }}); }});
  persons.forEach(p => {{
    const row = document.createElement('div');
    row.className = 'face-row';
    const thumb = PERSON_THUMBS[p];
    const imgHtml = thumb ? `<img src="data:image/jpeg;base64,${{thumb}}">` : '<div style="width:44px;height:44px;border-radius:50%;background:var(--card);display:flex;align-items:center;justify-content:center;">👤</div>';
    row.innerHTML = `${{imgHtml}}<div class="face-id">${{p}}<br><span style="font-size:10px;">${{imgCount[p]||0}} photos</span></div><input type="text" data-person-id="${{p}}" value="${{p}}" placeholder="Enter name...">`;
    rows.appendChild(row);
  }});
  document.getElementById('faceModal').classList.add('open');
}}

function closeFaceManager() {{
  document.getElementById('faceModal').classList.remove('open');
}}

function saveFaceNames() {{
  const inputs = document.querySelectorAll('#faceManagerRows input[data-person-id]');
  const nameMap = {{}};
  let changed = false;
  inputs.forEach(inp => {{
    const currentId = inp.getAttribute('data-person-id');
    const newName = inp.value.trim();
    if (newName && newName !== currentId) {{
      nameMap[currentId] = newName;
      changed = true;
    }}
  }});
  if (!changed) {{ closeFaceManager(); return; }}

  // 1) Apply renames in-memory to DATA
  DATA.forEach(f => {{
    if (f.faces) {{
      const mapped = [];
      f.faces.forEach(face => {{
        const nn = nameMap[face] || face;
        if (!mapped.includes(nn)) mapped.push(nn);
      }});
      f.faces = mapped;
    }}
  }});

  // 2) Update PERSON_THUMBS
  const oldThumbs = Object.assign({{}}, PERSON_THUMBS);
  Object.keys(nameMap).forEach(k => {{
    const newName = nameMap[k];
    if (oldThumbs[k] && !PERSON_THUMBS[newName]) PERSON_THUMBS[newName] = oldThumbs[k];
    delete PERSON_THUMBS[k];
  }});

  // 3) Track cumulative original-to-current mapping for face_names.json
  Object.keys(nameMap).forEach(k => {{
    // Find all original IDs that currently map to k
    Object.keys(ORIG_IDS).forEach(origKey => {{
      if (ORIG_IDS[origKey] === k) ORIG_IDS[origKey] = nameMap[k];
    }});
  }});
  // Build final map: original Person IDs -> current display names
  const finalMap = {{}};
  Object.keys(ORIG_IDS).forEach(origKey => {{
    if (ORIG_IDS[origKey] !== origKey) finalMap[origKey] = ORIG_IDS[origKey];
  }});

  // 4) Download face_names.json (place in same folder as gallery)
  const blob = new Blob([JSON.stringify(finalMap, null, 2)], {{type: 'application/json'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'face_names.json';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);

  // 5) Fully refresh sidebar + gallery
  closeFaceManager();
  refreshFaceUI();
  // Reset face filter to avoid stale selection
  document.getElementById('filterFace').value = '';
  applyFilters();

  // Show confirmation
  const msg = document.createElement('div');
  msg.style.cssText = 'position:fixed;bottom:20px;right:20px;background:var(--accent2);color:#000;padding:12px 20px;border-radius:8px;font-size:13px;font-weight:600;z-index:999;';
  msg.textContent = '✅ Names saved! Place face_names.json in photo folder & rescan for permanent changes.';
  document.body.appendChild(msg);
  setTimeout(() => msg.remove(), 5000);
}}

function refreshFaceUI() {{
  // Rebuild face filter dropdown and avatars
  const fSel = document.getElementById('filterFace');
  while (fSel.options.length > 3) fSel.remove(3); // keep All/Has/No
  const avatarDiv = document.getElementById('faceAvatars');
  avatarDiv.innerHTML = '';

  const persons = [...new Set(DATA.flatMap(f => f.faces || []))].filter(p => p !== 'Unknown').sort();
  persons.forEach(p => {{
    const o = document.createElement('option'); o.value = p; o.textContent = p; fSel.appendChild(o);
  }});
  persons.forEach(p => {{
    const thumb = PERSON_THUMBS[p];
    const chip = document.createElement('div');
    chip.style.cssText = 'cursor:pointer;text-align:center;border-radius:8px;padding:4px;border:2px solid transparent;transition:border-color 0.2s;';
    chip.title = p;
    chip.onclick = () => {{ fSel.value = p; applyFilters(); }};
    const label = p.startsWith('Person ') ? p.replace('Person ','') : p;
    if (thumb) {{
      chip.innerHTML = `<img src="data:image/jpeg;base64,${{thumb}}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;display:block;"><div style="font-size:10px;color:var(--text2);margin-top:2px;">${{label}}</div>`;
    }} else {{
      chip.innerHTML = `<div style="width:40px;height:40px;border-radius:50%;background:var(--card);display:flex;align-items:center;justify-content:center;font-size:16px;">👤</div><div style="font-size:10px;color:var(--text2);margin-top:2px;">${{label}}</div>`;
    }}
    avatarDiv.appendChild(chip);
  }});
}}

function resetFilters() {{
  document.getElementById('searchBox').value = '';
  document.getElementById('filterMonth').value = '';
  document.getElementById('filterType').value = '';
  document.getElementById('filterSize').value = '';
  document.getElementById('filterCamera').value = '';
  document.getElementById('filterRes').value = '';
  document.getElementById('filterFace').value = '';
  document.getElementById('sortBy').value = 'date_desc';
  applyFilters();
}}

// Attach events
['searchBox','filterMonth','filterType','filterSize','filterCamera','filterRes','filterFace','sortBy'].forEach(id => {{
  document.getElementById(id).addEventListener('input', applyFilters);
  document.getElementById(id).addEventListener('change', applyFilters);
}});

// Init
populateFilters();
applyFilters();
</script>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    folder = Path(folder).resolve()

    if not folder.is_dir():
        print(f"Error: '{folder}' is not a valid directory.")
        sys.exit(1)

    print(f"📁 Scanning: {folder}")
    files, person_thumbs = scan_folder(folder)

    if not files:
        print("No media files found.")
        sys.exit(0)

    face_count = sum(1 for f in files if f.get("face_count", 0) > 0)
    person_count = len(person_thumbs)
    print(f"  👤 Faces detected in {face_count} images, {person_count} unique people identified.")

    # Load and apply saved name mappings
    name_map = load_name_mappings(folder)
    if name_map:
        print(f"  📝 Applied {len(name_map)} saved name mappings from face_names.json")
        files, person_thumbs = apply_name_mappings(files, person_thumbs, name_map)

    print("🖼  Generating HTML gallery...")
    html = generate_html(files, folder, person_thumbs)
    output = folder / "photo_gallery.html"
    with open(output, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"✅ Gallery saved: {output}")
    print(f"   {len(files)} media files indexed.")
    print(f"   Open photo_gallery.html in any browser to browse your photos.")
