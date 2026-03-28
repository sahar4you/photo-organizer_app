# Usage Guide

## Getting Started

1. Launch the app (`npm start` or run the portable EXE)
2. Click **Open Photo Folder** or select a recent folder
3. Gallery loads instantly (from cache on repeat visits)

## Gallery Tab

- **Grid views**: Small / Medium / Large (affects thumbnail quality: 150px / 250px / 400px)
- **List view**: Compact list with small thumbnails
- **Date view**: Photos grouped by date
- **Search**: Type in the search box to filter by filename
- **Multi-select**: Click "Select Photos" to enable bulk operations

### Filters (sidebar)

| Filter | Options |
|--------|---------|
| Date | By month |
| Type | Images / Videos |
| Camera | Auto-detected from EXIF |
| Resolution | HD+ / Full HD+ / 4K+ |
| Faces | All / Kept Faces / Has Faces / No Faces / Individual person |
| Folder | All / Root Only / Specific subfolder |
| Tags | All / Has Tags / No Tags / Specific tag |
| Quality | Good+ / Better+ / Best |
| Sort | Date / Quality / Name / Size |

**Filter count**: Shows "Showing X / Y" in the tab bar.

## Faces Tab

- Shows all detected faces as a grid of person cards
- **Kept faces** appear at top with highlight border and "KEEP" badge
- Toggle buttons: **All Faces** / **Kept Faces**
- Click a face card to filter gallery by that person
- Click **Keep** star to mark a face as kept
- Click **Rename / Merge Faces** to rename or merge person groups

## Duplicates Tab

- **Exact duplicates**: Identical files (same MD5 hash)
- **Near duplicates**: Visually similar (pHash within threshold)
- Each group shows: keeper (KEEP badge) + duplicate files
- **Set as keeper**: Change which file is kept
- **Select All**: Selects all duplicates (never selects keepers)
- **Move Selected**: Moves to `__duplicates__/` folder
- **Trash Selected**: Sends to recycle bin
- **Ignore**: Hide a group from view

## Lightbox

- Click any image to open full-quality viewer
- **Navigation**: Arrow keys or click < > buttons
- **Zoom**: Click zoom button or scroll wheel (0.5x to 8x)
- **Pan**: Click and drag when zoomed in
- **Double-click**: Toggle fit/zoom
- **Info panel**: Toggle with "i" button (shows EXIF, quality, faces, tags)
- **Delete**: Trash icon sends file to recycle bin
- **Face editing**: Rename or remove face labels directly in lightbox

## Bulk Operations (Select Mode)

1. Click "Select Photos" in sidebar
2. Click images to select/deselect
3. Available actions:
   - **Add Tag**: Add a tag to selected photos
   - **Remove Tag**: Remove a tag
   - **Move to Folder**: Move with autocomplete suggestions
   - **Export**: Copy to export folder
   - **Delete**: Send to recycle bin
   - **Done**: Exit select mode

## Tags

- Tags are Title Case normalized ("test" becomes "Test")
- Autocomplete suggestions while typing
- Filter by tag in sidebar
- Tags persisted in `.cache/data/photo_tags.json`

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Left/Right | Navigate gallery / lightbox |
| Escape | Close lightbox |
| Enter | Open focused image in lightbox |
