# Photo Organizer — User Guide

## Getting Started

### Step 1: Launch the App
- **Windows**: Run `START.bat` or the portable `.exe`
- **Development**: Run `npm start`

### Step 2: Select a Folder
Click **"Open Folder"** and choose any folder containing photos. The app scans all subfolders automatically.

### Step 3: Browse Your Photos
Photos appear in a grid with thumbnails. Use the view modes to switch between layouts.

---

## View Modes

| Mode | Description |
|------|-------------|
| **Date** | Photos grouped by date with section headers |
| **Grid** | Flat responsive grid (default) |
| **List** | Compact horizontal rows with full metadata |

Use **S / M / L** buttons to adjust thumbnail size in all views.

---

## Filters

| Filter | Options |
|--------|---------|
| Search | Type a filename to search |
| Date | Filter by month |
| Type | Images only / Videos only |
| Size | Small / Medium / Large / Huge |
| Camera | Filter by camera model |
| Resolution | HD+ (1 MP) / Full HD+ (2 MP) / 4K+ (8 MP) |
| Person | Filter by detected face |
| Tags | Filter by tag name |
| Quality | Good+ (25+) / Better+ (50+) / Best (75+) |

### Sorting
- Newest First / Oldest First
- Best Quality
- Name A-Z
- Largest / Smallest

---

## Quality Score

Each image gets a quality score (0-100) based on:
- **Sharpness** (50% weight) — blur detection via Laplacian variance
- **Resolution** (30% weight) — pixel count relative to dataset
- **File Size** (20% weight) — larger files often mean higher quality

### Labels
| Score | Label | Typical Use |
|-------|-------|-------------|
| 0-10 | Poor | Thumbnails only |
| 10-25 | Basic | Social media |
| 25-50 | Good | Regular viewing |
| 50-75 | Better | Large screens, light printing |
| 75-100 | Best | High-quality printing |

---

## Tagging Photos

1. Click **"Select Photos"** in the sidebar
2. Click photos to select them (checkmark appears)
3. Type a tag name and press **Enter** or click **"+ Add Tag"**
4. Tags appear as colored pills on each photo

### Tag Autocomplete
Start typing and existing tags appear as suggestions. Use arrow keys to navigate, Enter to pick.

---

## Duplicate Detection

The app automatically detects:
- **Exact duplicates** — identical files (MD5 hash)
- **Near duplicates** — visually similar images (pHash)

Switch to the **Duplicates** tab to review. The best-quality image is auto-selected as keeper.

### Actions
- **Move Selected** — moves duplicates to `__duplicates__/` folder
- **Trash Selected** — sends to recycle bin (recoverable)
- **Ignore Group** — hides a group from the list

---

## Export

1. Enter **Select** mode
2. Choose photos
3. Click **"Export"**
4. Enter a folder name
5. Files are copied to `Exported/<name>/`

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Arrow keys | Navigate gallery |
| Enter | Open selected photo |
| Ctrl+A | Select all photos |
| Delete | Trash selected |
| Escape | Exit select mode / close lightbox |

---

## Settings

| Setting | Description |
|---------|-------------|
| Show Folder Path | Toggle folder hierarchy display on/off |
| Clear Cache | Delete thumbnail cache and hash cache |

---

## Large Image View (Lightbox)

Click any photo to view it full-size. The info panel shows:
- File name and folder path
- Date, size, and file type
- Resolution with megapixels and usage recommendation
- Quality score with detailed breakdown
- Detected faces and tags
- GPS coordinates (if available)

Use arrow keys or on-screen buttons to navigate between photos.
