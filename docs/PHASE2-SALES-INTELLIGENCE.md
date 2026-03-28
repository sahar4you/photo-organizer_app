# Phase 2: Sales Intelligence Roadmap

## Purpose

This app is used for **sales meetings and reference browsing** — showing previous event setups to clients for faster deal conversion.

**Use case**: Sales team opens the app, filters by location/hotel/setup type, and shows relevant reference images to clients during meetings.

**NOT for**: Event delivery to clients.

## Feature: Location Intelligence

### Goal
Extract GPS from images and convert to meaningful location data (hotel, city, state) without requiring internet during usage.

### Data Flow
```
Image EXIF GPS -> reverse geocode (one-time, cached) -> location metadata
```

### Implementation Plan

1. **GPS Extraction** (already available in scanner.py via `gps_lat`, `gps_lon`)

2. **GPS Clustering** (no API needed):
   - Group images by GPS proximity (within ~200m radius)
   - Assign cluster IDs
   - Each cluster = one venue/location

3. **Reverse Geocoding** (one-time batch, cached):
   - Use OpenStreetMap Nominatim (free, no API key)
   - Rate-limited: 1 request/second
   - Cache results in `.cache/data/location_cache.json`
   - Only geocode new GPS clusters

4. **Location Data Structure**:
```json
{
  "gps": [19.0760, 72.8777],
  "location": {
    "state": "Maharashtra",
    "city": "Mumbai",
    "hotel": "Taj Lands End",
    "area": "Bandra"
  }
}
```

## Feature: Setup Tagging

### Tag Categories

| Category | Example Tags |
|----------|-------------|
| Equipment | LED, Sound, Projector, DJ, Lighting |
| Setup Type | Stage, Conference, Wedding, Corporate, Reception |
| Scale | Small (< 100 pax), Medium (100-500), Large (500+) |

### Implementation

- Predefined tag categories in UI (not free-text only)
- Quick-tag buttons for common setups
- Tags stored in existing `photo_tags.json` with category prefix:
  ```json
  { "setup:LED": true, "setup:Stage": true, "scale:Large": true }
  ```

### Auto-Tagging (future)

- Use image classification model to suggest tags
- Detect: screens, stages, lighting rigs, speaker arrays
- Confidence threshold before auto-applying

## Feature: Smart Filters

### New Gallery Filters

| Filter | Options |
|--------|---------|
| Location | All / State / City / Hotel |
| Setup | LED / Sound / Stage / Conference / etc. |
| Scale | Small / Medium / Large |

### Filter Behavior

- Filters stack (AND logic): Location=Mumbai + Setup=Stage shows Mumbai stage photos
- Filter count updates: "Showing 15 / 2000"
- Face filter still works alongside

## UI Plan

### New Tab: Locations

```
[Gallery] [Duplicates] [Faces] [Locations]
```

**Locations tab**:
- Map view (optional, using Leaflet + OpenStreetMap tiles)
- Cluster pins on map
- Click cluster -> show images from that location
- List view fallback: grouped by State > City > Hotel

### Gallery Filter Integration

- Location dropdown populated from cached location data
- Hotel autocomplete
- Setup type multi-select checkboxes

## Data Structure

### Per-Image Extended Metadata

```json
{
  "rel_path": "event_photos/IMG_001.jpg",
  "gps_lat": 19.0760,
  "gps_lon": 72.8777,
  "location": {
    "state": "Maharashtra",
    "city": "Mumbai",
    "hotel": "Taj Lands End",
    "area": "Bandra",
    "cluster_id": "loc_001"
  },
  "setup_tags": ["LED", "Stage", "Wedding"],
  "scale": "Large"
}
```

### Location Cache

`.cache/data/location_cache.json`:
```json
{
  "clusters": [
    {
      "id": "loc_001",
      "center": [19.0760, 72.8777],
      "state": "Maharashtra",
      "city": "Mumbai",
      "hotel": "Taj Lands End",
      "image_count": 45
    }
  ],
  "geocode_cache": {
    "19.076_72.878": { "state": "Maharashtra", "city": "Mumbai", ... }
  }
}
```

## Implementation Steps

### Step 1: GPS Clustering (no API)
- Extract GPS from all images (already done)
- Cluster by proximity using simple distance threshold
- Assign cluster IDs
- **Effort**: 1-2 days

### Step 2: One-Time Geocoding
- Batch geocode cluster centers via Nominatim
- Cache all results locally
- **Effort**: 1 day

### Step 3: Location Cache + Filters
- Store location data in face_cache-style JSON
- Add Location/Hotel filter dropdowns to gallery
- **Effort**: 2-3 days

### Step 4: Locations Tab UI
- List view: State > City > Hotel > Photos
- Click to filter gallery
- **Effort**: 2-3 days

### Step 5: Setup Tagging UI
- Category-based tag buttons
- Quick-tag panel in sidebar
- Filter integration
- **Effort**: 2-3 days

### Step 6 (Optional): Map View
- Leaflet.js with OpenStreetMap tiles
- Cluster markers
- Click to browse
- **Effort**: 3-5 days

## Total Estimated Effort

| Component | Days |
|-----------|------|
| GPS clustering | 1-2 |
| Geocoding + cache | 1 |
| Filters + cache | 2-3 |
| Locations tab | 2-3 |
| Setup tagging | 2-3 |
| Map view (optional) | 3-5 |
| **Total** | **11-17 days** |

## Dependencies

- No new Python packages required for GPS clustering
- Nominatim API: free, no key needed, 1 req/sec rate limit
- Leaflet.js: CDN or bundled (optional, for map view only)
