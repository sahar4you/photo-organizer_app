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

# ---- Face Detection ----
def detect_faces_cv(filepath, face_cascade, profile_cascade):
    if not HAS_FACE: return [], []
    try:
        img = cv2.imread(str(filepath))
        if img is None: return [], []
        h, w = img.shape[:2]
        max_dim = 800
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = cv2.resize(img, (int(w*scale), int(h*scale)))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30,30))
        if len(faces) == 0:
            faces = profile_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30,30))
        if len(faces) == 0: return [], []

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
        # Skip __duplicates__ directory
        dirnames[:] = [d for d in dirnames if d != DUPLICATES_DIR]
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext in MEDIA_EXTENSIONS:
                abs_path = Path(dirpath) / name
                rel_path = str(abs_path.relative_to(folder))
                media_files.append((abs_path, rel_path))
    return sorted(media_files, key=lambda x: x[1])

def scan_folder(folder):
    folder = Path(folder).resolve()
    files = []

    # Recursive traversal — collect all media files in tree
    all_media = _collect_media_files(folder)
    total_count = len(all_media)

    face_cascade, profile_cascade = None, None
    all_face_data = []
    if HAS_FACE:
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml')
        profile_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_profileface.xml')

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
        gps_lat, gps_lon = None, None

        if not is_video:
            exif = get_exif_data(str(filepath))
            date_taken = get_date_from_exif(exif)
            camera = str(exif.get('Make','')).strip()
            model = str(exif.get('Model','')).strip()
            if model: camera = f"{camera} {model}".strip()
            w2 = exif.get('ExifImageWidth') or exif.get('ImageWidth','')
            h2 = exif.get('ExifImageHeight') or exif.get('ImageLength','')
            if w2 and h2: resolution = f"{w2}x{h2}"
            gps_info = exif.get('GPSInfo')
            if gps_info: gps_lat, gps_lon = get_gps_coords(gps_info)

        if not date_taken: date_taken = get_date_from_filename(name)
        if not date_taken: date_taken = mod_time

        thumb = ""
        if not is_video: thumb = make_thumbnail_b64(str(filepath))

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
            "has_gps": gps_lat is not None,
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
            "thumb": thumb,
            "faces": [],
            "face_count": face_count,
        }
        files.append(entry)
        pct = int((i+1)/total_count*100) if total_count else 100
        print(f"\rScanning: {pct}% ({i+1}/{total_count}) — {rel_path[:50]}", end="", flush=True)

    print(f"\rScanned {len(files)} media files.                    ", flush=True)

    person_thumbs = {}
    if face_cascade and all_face_data:
        print("Clustering faces...", flush=True)
        file_faces, person_thumbs = cluster_faces(all_face_data)
        for file_idx, persons in file_faces.items():
            if file_idx < len(files):
                files[file_idx]["faces"] = persons

    # Load and apply name mappings
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
        print("Running duplicate detection...", flush=True)
        duplicate_result = detect_duplicates(files, folder, threshold=10, dry_run=dry_run)
    except ImportError:
        print("Warning: duplicate_detector module not found, skipping.", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Duplicate detection failed: {e}", file=sys.stderr)

    return files, person_thumbs, duplicate_result

if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    json_mode = "--json" in sys.argv

    folder = Path(folder).resolve()
    if not folder.is_dir():
        print(json.dumps({"error": f"Not a directory: {folder}"}))
        sys.exit(1)

    files, person_thumbs, duplicate_result = scan_folder(folder)

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
        print(json.dumps(result))
    else:
        print(f"Total: {len(files)} files, {result['face_images']} with faces, {result['persons']} people")
        if duplicate_result:
            s = duplicate_result["stats"]
            print(f"Duplicates: {s['exact_groups']} exact groups, "
                  f"{s['near_groups']} near groups, "
                  f"{s['duplicates_found']} total duplicates found")
