# burning man city template

regenerate the stable playa places (and optionally the street grid) for a
future year from a handful of anchor coordinates.

## why this works

black rock city is a rigid layout: every named place sits at a fixed clock
hour + ring distance measured from The Man. if you know the coordinates of
just a few places for a new year, the whole grid can be re-derived.

measured across the last three years of official data (2024, 2025, 2026),
place anchors line up with essentially zero rotation / zero scale change:

| fit (plazas only)   |  n | rotation     | scale     | rms   |
|---------------------|----|--------------|-----------|-------|
| 2024 -> 2025        |  5 | -0.0007 deg  | 1.00160   | 4 ft  |
| 2025 -> 2026        |  9 | +0.0032 deg  | 1.00000   | 0 ft  |

and a prediction test (2 anchors -> 40 places, compared against real data)
landed: median error ~0 ft, p95 ~53 ft. the street grid predicted to ~17 ft
median against real street lines.

**caveats (read before trusting output):**
- rotation/scale are *not* assumed — the tool fits them fresh from your
  anchors on every run, so a layout-change year is handled automatically.
  the ~0 deg / ~1.0 scale values above are just a record of the past.
- a huge design change or a renamed plaza breaks name-matching. the tool
  fails loudly if an anchor name is not in the reference data.
- every autofilled point is marked `status = autofilled` and is
  **unconfirmed**. verify anything important (gate, center camp, temple,
  the man) against the year's actual published coordinates before shipping
  anything built on it.
- historical note: 2024 names used clock notation (`3:00 & G Plaza`) and
  2025+ dropped the `:00` (`3 & G Plaza`). if you lift a new reference year
  that re-introduces the difference, name joins will silently not match and
  anchors will be rejected (see "fails loudly" above).

## workflow for a new year

1. download the new year's official places when they drop:
   https://api.burningman.org or the innovate GIS data repo:
   https://github.com/burningmantech/innovate-GIS-data

2. enter anchors — pick one of three ways:
   - create `anchors_YYYY.csv` (or copy + edit the prior year's):
     ```
     name,lat,lon
     The Man,40.783247448000054,-119.20788409599999
     Center Camp,40.777372264000064,-119.21561156099995
     ```
   - skip the file and pass them straight on the command line:
     ```
     python3 city_template.py --year 2027 \
       --anchor "The Man, 40.783247448, -119.207884096" \
       --anchor "Center Camp, 40.777372264, -119.215611561"
     ```
   - or run with neither and the tool will prompt you line by line:
     ```
     anchor> The Man, 40.783247448, -119.207884096
     anchor> Center Camp, 40.777372264, -119.215611561
     anchor>    <- blank line finishes
     ```
   use exactly the place names from the reference files.
   good anchor choices (usually published early, geometrically distinct):
   - The Man
   - Center Camp
   - Gate Actual
   - one plaza on each side, e.g. 3 & G Plaza and 9 & G Plaza

3. run:
   ```
   python3 city_template.py --year 2027
   ```
   or with the street grid:
   ```
   python3 city_template.py --year 2027 --include-streets
   ```
   the run also hands the outputs to QGIS itself (via its bundled python) so
   QGIS authors `bm_city_2027.qgs` — project + layer CRSs, styles and the
   basemap are correct by construction. if QGIS isn't installed the data
   files still write and it tells you how to point at QGIS (`QGIS_PYTHON`).

4. open the ready-to-go map: **double-click `bm_city_2027.qgs`**, or eyeball
   `bm_city_2027_preview.png` first (a render of the same project). it's a
   self-contained QGIS project — the predicted places (green=entered,
   amber=autofilled), your anchors, the real 2026 portals/plazas/streets, and
   an OpenStreetMap basemap, all already layered. the project renders in
   EPSG:3857 (so the circular playa stays round and lines up with the OSM
   tiles) while every geojson stays in EPSG:4326 — QGIS reprojects them on
   the fly. nothing you do here touches any other map you have.

5. prefer data over the map? `places_2027_fill.csv` has the same points as
   rows. `entered` anchors are green; `autofilled` things are amber and
   unconfirmed.

6. spot-check: verify gate/center camp/temple/the man against the year's
   published coords. if any autofilled point is wrong, add it as an anchor
   and re-run.

## files

- repository `reference/` holds the 2026 geometry used as the template base
  (plus the 2024/2025 files kept for the rigidity check above).
- per-year output (all in the same folder as the tool):
  - `places_YYYY_fill.csv` — points as rows (name,type,status,lat,lon)
  - `places_YYYY_fill.geojson` — the point layer (entered/autofilled)
  - `streets_YYYY_fill.geojson` — street grid as clean line features
  - `anchors_YYYY.geojson` — just the anchors you entered
  - `bm_city_YYYY.qgs` — the ready-to-open QGIS project
  - `bm_city_YYYY_preview.png` — a render of the project (needs QGIS only when
    it's generated)
  - `osm_tiles_YYYY.xml` — the OpenStreetMap tile config the project uses

## options

- `--year NNNN` (required) — target year; reads `anchors_NNNN.csv`
- `--include-streets` — also transform the street grid (rings + avenues)
- `--anchor "name,lat,lon"` — an anchor on the command line (repeatable;
  no csv file needed)
- `--reference-dir DIR` — where the reference geojson files live
- `QGIS_PYTHON` (env) — path to the QGIS-bundled python, if not on this mac
  at `/Applications/QGIS.app/Contents/MacOS/python3.12`