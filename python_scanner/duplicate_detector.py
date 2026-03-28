#!/usr/bin/env python3
"""
Duplicate Detector — 3-layer duplicate detection system.

Layer 3: Size pre-filter (group by file size)
Layer 1: Exact duplicates (MD5 hash)
Layer 2: Near duplicates (pHash via imagehash library)

Follows SSOT.md design strictly.
"""

import os
import sys
import json
import hashlib
import shutil
from pathlib import Path
from collections import defaultdict

# ---- Debug flag (env-controlled, shared with scanner) ----
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

def log_info(msg):
    print(f"[INFO] {msg}", file=sys.stderr, flush=True)

def log_debug(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr, flush=True)

def log_error(msg):
    print(f"[ERROR] {msg}", file=sys.stderr, flush=True)

try:
    from PIL import Image
    import imagehash
    HAS_IMAGEHASH = True
except ImportError:
    HAS_IMAGEHASH = False

# Directory name for moved duplicates
DUPLICATES_DIR = "__duplicates__"

# Read buffer size for MD5 hashing
CHUNK_SIZE = 65536  # 64KB


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

def _cache_path(folder):
    """Return path to hash_cache.json, preferring .cache/data/ location."""
    new_path = Path(folder) / ".cache" / "data" / "hash_cache.json"
    old_path = Path(folder) / "hash_cache.json"
    # Migrate old to new if needed
    if old_path.exists() and not new_path.exists():
        new_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            old_path.rename(new_path)
        except OSError:
            import shutil
            shutil.copy2(str(old_path), str(new_path))
            old_path.unlink()
    return new_path


def load_hash_cache(folder):
    """Load hash_cache.json. Return empty structure if missing."""
    cache_path = _cache_path(folder)
    if cache_path.exists():
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
            if data.get("version") == 1:
                return data
        except (json.JSONDecodeError, IOError):
            pass
    return {"version": 1, "root": str(folder), "files": {}}


def save_hash_cache(folder, cache):
    """Persist hash cache to .cache/data/hash_cache.json."""
    cache_path = _cache_path(folder)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache["root"] = str(folder)
    try:
        with open(cache_path, "w") as f:
            json.dump(cache, f, indent=2)
    except IOError as e:
        log_error(f"Could not save hash cache: {e}")


def prune_cache(cache, existing_rel_paths):
    """Remove cache entries for files that no longer exist on disk."""
    cached_keys = set(cache.get("files", {}).keys())
    valid_keys = set(existing_rel_paths)
    stale = cached_keys - valid_keys
    for key in stale:
        del cache["files"][key]
    return len(stale)


def is_cache_valid(cache_entry, size_bytes, mtime):
    """Check if (size_bytes, mtime) match — hashes still valid."""
    return (cache_entry.get("size_bytes") == size_bytes
            and cache_entry.get("mtime") == mtime)


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------

def compute_file_hash(filepath):
    """MD5 hash of full file contents, read in 64KB chunks.
    Returns hex string prefixed with 'md5:'."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return f"md5:{h.hexdigest()}"


def compute_phash(filepath):
    """Perceptual hash using imagehash.phash().
    Returns hex string representation of the 64-bit hash.
    Returns None if image cannot be opened or imagehash unavailable."""
    if not HAS_IMAGEHASH:
        return None
    try:
        img = Image.open(filepath)
        h = imagehash.phash(img)
        return str(h)
    except Exception:
        return None


def hamming_distance(hash1, hash2):
    """Compute Hamming distance between two pHash hex strings.
    Uses imagehash built-in subtraction operator.
    Always returns a native Python int (not numpy int64) for JSON safety."""
    if not HAS_IMAGEHASH or hash1 is None or hash2 is None:
        return 999  # sentinel: cannot compare
    try:
        h1 = imagehash.hex_to_hash(hash1)
        h2 = imagehash.hex_to_hash(hash2)
        return int(h1 - h2)  # int() to avoid numpy int64
    except Exception:
        return 999


# ---------------------------------------------------------------------------
# Union-Find for transitive grouping
# ---------------------------------------------------------------------------

class UnionFind:
    """Disjoint set structure for clustering near-duplicate pairs."""

    def __init__(self):
        self.parent = {}
        self.rank = {}

    def find(self, x):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


# ---------------------------------------------------------------------------
# Layer 3: Size pre-filter
# ---------------------------------------------------------------------------

def group_by_size(files):
    """Group files by size_bytes. Returns dict {size: [file_entries...]}.
    Groups with only 1 file are excluded (cannot be exact duplicates)."""
    size_groups = defaultdict(list)
    for entry in files:
        size_groups[entry["size_bytes"]].append(entry)
    # Keep only groups with 2+ files
    return {sz: grp for sz, grp in size_groups.items() if len(grp) >= 2}


# ---------------------------------------------------------------------------
# Layer 1: Exact duplicates (MD5)
# ---------------------------------------------------------------------------

def find_exact_duplicates(files, cache, root):
    """Detect exact duplicates using size pre-filter + MD5.

    Returns list of groups:
    [{"hash": "md5:...", "keep": "rel/path", "duplicates": ["rel/path", ...]}]
    """
    # Layer 3: group by size first
    size_groups = group_by_size(files)

    # Compute MD5 only within same-size groups
    hash_groups = defaultdict(list)
    for size, group in size_groups.items():
        for entry in group:
            rel = entry["rel_path"]
            abs_path = Path(root) / rel
            cached = cache["files"].get(rel, {})

            if is_cache_valid(cached, entry["size_bytes"], entry["mtime"]):
                file_hash = cached.get("file_hash")
            else:
                try:
                    file_hash = compute_file_hash(abs_path)
                except (IOError, OSError) as e:
                    log_error(f"Cannot hash {rel}: {e}")
                    continue

            # Update cache
            if rel not in cache["files"]:
                cache["files"][rel] = {}
            cache["files"][rel]["size_bytes"] = entry["size_bytes"]
            cache["files"][rel]["mtime"] = entry["mtime"]
            cache["files"][rel]["file_hash"] = file_hash

            hash_groups[file_hash].append(entry)

    # Build duplicate groups (only where 2+ files share a hash)
    exact_groups = []
    for file_hash, group in hash_groups.items():
        if len(group) < 2:
            continue
        sorted_group = _sort_by_keeper_priority(group)
        exact_groups.append({
            "hash": file_hash,
            "keep": sorted_group[0]["rel_path"],
            "duplicates": [e["rel_path"] for e in sorted_group[1:]],
        })

    return exact_groups


# ---------------------------------------------------------------------------
# Layer 2: Near duplicates (pHash)
# ---------------------------------------------------------------------------

def find_near_duplicates(files, cache, root, threshold=10, exact_pairs=None):
    """Detect near-duplicate images using pHash + Hamming distance.

    Args:
        files: list of file entry dicts
        cache: hash cache dict (mutated with new phash values)
        root: absolute root path
        threshold: max Hamming distance to consider as near-duplicate
        exact_pairs: set of frozenset pairs already flagged as exact duplicates

    Returns list of groups:
    [{"representative": "rel/path", "keep": "rel/path",
      "duplicates": [...], "members": [{"rel_path": ..., "distance": ...}]}]
    """
    if not HAS_IMAGEHASH:
        log_info("imagehash not installed, skipping near-duplicate detection")
        return []

    if exact_pairs is None:
        exact_pairs = set()

    # Filter to images only (skip videos)
    images = [f for f in files if f["type"] == "image"]

    # Safety check for O(n^2)
    if len(images) > 3000:
        pair_count = len(images) * (len(images) - 1) // 2
        log_info(f"Near-duplicate scan: {len(images)} images = "
                 f"{pair_count:,} pairwise comparisons, may take a while")

    # Compute pHash for all images (using cache)
    image_hashes = []  # list of (entry, phash_str)
    for entry in images:
        rel = entry["rel_path"]
        abs_path = Path(root) / rel
        cached = cache["files"].get(rel, {})

        if (is_cache_valid(cached, entry["size_bytes"], entry["mtime"])
                and cached.get("phash") is not None):
            phash_str = cached["phash"]
        else:
            phash_str = compute_phash(abs_path)
            if phash_str is None:
                log_debug(f"Cannot compute pHash for {rel}")
                continue

        # Update cache
        if rel not in cache["files"]:
            cache["files"][rel] = {}
        cache["files"][rel]["size_bytes"] = entry["size_bytes"]
        cache["files"][rel]["mtime"] = entry["mtime"]
        cache["files"][rel]["phash"] = phash_str

        image_hashes.append((entry, phash_str))

    # Pairwise comparison with Union-Find clustering
    uf = UnionFind()
    n = len(image_hashes)
    for i in range(n):
        for j in range(i + 1, n):
            rel_i = image_hashes[i][0]["rel_path"]
            rel_j = image_hashes[j][0]["rel_path"]

            # Skip pairs already flagged as exact duplicates
            if frozenset((rel_i, rel_j)) in exact_pairs:
                continue

            dist = hamming_distance(image_hashes[i][1], image_hashes[j][1])
            if dist <= threshold:
                uf.union(rel_i, rel_j)

    # Build groups from Union-Find
    clusters = defaultdict(list)
    hash_lookup = {e["rel_path"]: ph for e, ph in image_hashes}
    entry_lookup = {e["rel_path"]: e for e, _ in image_hashes}

    for entry, phash_str in image_hashes:
        root_key = uf.find(entry["rel_path"])
        clusters[root_key].append(entry["rel_path"])

    # Convert to output format (only groups with 2+ members)
    near_groups = []
    for root_key, members in clusters.items():
        if len(members) < 2:
            continue

        member_entries = [entry_lookup[rp] for rp in members]
        sorted_members = _sort_by_keeper_priority(member_entries)
        keeper = sorted_members[0]
        keeper_phash = hash_lookup[keeper["rel_path"]]

        member_details = []
        for e in sorted_members:
            ph = hash_lookup[e["rel_path"]]
            dist = hamming_distance(keeper_phash, ph)
            member_details.append({
                "rel_path": e["rel_path"],
                "distance": dist,
            })

        near_groups.append({
            "representative": keeper["rel_path"],
            "keep": keeper["rel_path"],
            "duplicates": [e["rel_path"] for e in sorted_members[1:]],
            "members": member_details,
        })

    return near_groups


# ---------------------------------------------------------------------------
# Keeper selection
# ---------------------------------------------------------------------------

import re as _re

def _is_copy_file(rel_path):
    """Detect if a file is likely a copy based on naming patterns."""
    name = rel_path.rsplit('/', 1)[-1].rsplit('\\', 1)[-1].lower()
    stem = name.rsplit('.', 1)[0] if '.' in name else name
    if 'copy' in stem or 'kopie' in stem:
        return True
    # Match patterns like "file (1)", "file (2)", "file - Copy"
    if _re.search(r'\(\d+\)$', stem.strip()):
        return True
    if _re.search(r' - \d+$', stem.strip()):
        return True
    return False

def _sort_by_keeper_priority(entries):
    """Sort file entries by keeper priority (first element = keeper).

    Priority logic:
    1. Not a copy file (originals always beat copies)
    2. Earliest mtime (oldest file = true original)
    3. Highest quality score
    4. Shortest filename (simpler name = likely original)
    5. Shallowest path (root IMG.jpg over FolderA/IMG.jpg if same age)
    6. Alphabetical tiebreaker

    Example: IMG.jpg (root, old) > FolderA/IMG.jpg (subfolder) > IMG - Copy.jpg (copy)
    """
    return sorted(entries, key=lambda e: (
        1 if _is_copy_file(e["rel_path"]) else 0,  # originals ALWAYS before copies
        e["mtime"],                                   # earliest file = true original
        -(e.get("quality_score") or 0),               # highest quality
        len(e["rel_path"].rsplit('/', 1)[-1]),         # shortest filename
        e["rel_path"].count("/"),                      # shallowest path
        e["rel_path"],                                 # alphabetical tiebreaker
    ))


# ---------------------------------------------------------------------------
# File operations (move duplicates)
# ---------------------------------------------------------------------------

def _safe_dest_path(dest_path):
    """Resolve destination name collisions by appending _dup2, _dup3, etc."""
    if not dest_path.exists():
        return dest_path
    stem = dest_path.stem
    suffix = dest_path.suffix
    parent = dest_path.parent
    counter = 2
    while True:
        new_name = f"{stem}_dup{counter}{suffix}"
        candidate = parent / new_name
        if not candidate.exists():
            return candidate
        counter += 1


def _remove_empty_parents(path, stop_at):
    """Remove empty directories bottom-up, stopping at stop_at."""
    current = path.parent
    while current != stop_at and current != current.parent:
        try:
            if current.is_dir() and not any(current.iterdir()):
                current.rmdir()
            else:
                break
        except OSError:
            break
        current = current.parent


def move_duplicates(duplicate_groups, root, dry_run=True):
    """Move duplicate files to root/__duplicates__/, preserving structure.

    Args:
        duplicate_groups: dict with "exact" and "near" lists
        root: absolute root path
        dry_run: if True, only report what would be moved (no file ops)

    Returns list of {"source": rel_path, "destination": rel_path, "status": str}
    """
    root = Path(root)
    dup_dir = root / DUPLICATES_DIR
    moved = []

    # Collect all duplicate rel_paths (from both exact and near groups)
    all_duplicates = []
    for group in duplicate_groups.get("exact", []):
        for rel in group.get("duplicates", []):
            all_duplicates.append(rel)
    for group in duplicate_groups.get("near", []):
        for rel in group.get("duplicates", []):
            all_duplicates.append(rel)

    # Deduplicate (a file might appear in both exact and near groups)
    seen = set()
    unique_duplicates = []
    for rel in all_duplicates:
        if rel not in seen:
            seen.add(rel)
            unique_duplicates.append(rel)

    for rel in unique_duplicates:
        src = root / rel
        dest = dup_dir / rel
        dest = _safe_dest_path(dest)

        if dry_run:
            moved.append({
                "source": rel,
                "destination": str(dest.relative_to(root)),
                "status": "dry_run",
            })
            continue

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            moved.append({
                "source": rel,
                "destination": str(dest.relative_to(root)),
                "status": "moved",
            })
            # Clean up empty source directories
            _remove_empty_parents(src, root)
        except PermissionError as e:
            log_error(f"Permission denied moving {rel}: {e}")
            moved.append({"source": rel, "destination": "", "status": "error_permission"})
        except OSError as e:
            log_error(f"Cannot move {rel}: {e}")
            moved.append({"source": rel, "destination": "", "status": "error"})

    return moved


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def detect_duplicates(files, folder, threshold=10, dry_run=True):
    """Orchestrate full duplicate detection pipeline.

    Args:
        files: list of file entry dicts (must have rel_path, size_bytes, mtime, type)
        folder: absolute root folder path
        threshold: Hamming distance threshold for near-duplicates
        dry_run: if True, do not move files

    Returns dict:
    {
        "exact": [...],
        "near": [...],
        "moved": [...],
        "stats": {"total_files": N, "exact_groups": N, "near_groups": N, "duplicates_found": N}
    }
    """
    folder = Path(folder).resolve()

    # Step 1: Load and prune cache
    cache = load_hash_cache(folder)
    rel_paths = [f["rel_path"] for f in files]
    pruned = prune_cache(cache, rel_paths)
    if pruned > 0:
        log_debug(f"Cache: pruned {pruned} stale entries")

    # Step 2: Find exact duplicates (Layer 3 + Layer 1)
    log_info("Detecting exact duplicates (MD5)...")
    exact_groups = find_exact_duplicates(files, cache, folder)

    # Build exact-pair set for Layer 2 exclusion
    exact_pairs = set()
    for group in exact_groups:
        all_in_group = [group["keep"]] + group["duplicates"]
        for i in range(len(all_in_group)):
            for j in range(i + 1, len(all_in_group)):
                exact_pairs.add(frozenset((all_in_group[i], all_in_group[j])))

    # Step 3: Find near duplicates (Layer 2)
    log_info("Detecting near duplicates (pHash)...")
    near_groups = find_near_duplicates(files, cache, folder, threshold, exact_pairs)

    # Step 4: Save updated cache
    save_hash_cache(folder, cache)

    # Step 5: Validate and deduplicate groups (ensure unique paths)
    for g in exact_groups:
        g["duplicates"] = list(dict.fromkeys(d for d in g["duplicates"] if d != g["keep"]))
    for g in near_groups:
        seen = set()
        deduped_members = []
        for m in g["members"]:
            if m["rel_path"] not in seen:
                seen.add(m["rel_path"])
                deduped_members.append(m)
        g["members"] = deduped_members
        g["duplicates"] = list(dict.fromkeys(d for d in g["duplicates"] if d != g["keep"]))
        # Validate: log if any group had duplicate entries
        all_paths = [g["keep"]] + g["duplicates"]
        if len(set(all_paths)) != len(all_paths):
            log_error(f"Duplicate paths in near group: {all_paths}")

    duplicate_groups = {"exact": exact_groups, "near": near_groups}

    # Step 6: Move duplicates (or dry run)
    moved = move_duplicates(duplicate_groups, folder, dry_run=dry_run)

    # Stats
    exact_dup_count = sum(len(g["duplicates"]) for g in exact_groups)
    near_dup_count = sum(len(g["duplicates"]) for g in near_groups)

    return {
        "exact": exact_groups,
        "near": near_groups,
        "moved": moved,
        "stats": {
            "total_files": len(files),
            "exact_groups": len(exact_groups),
            "near_groups": len(near_groups),
            "duplicates_found": exact_dup_count + near_dup_count,
        },
    }
