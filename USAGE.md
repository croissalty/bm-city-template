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

2. create `anchors_YYYY.csv` with at least 2 rows (more = better). use
   exactly the place names from the reference files:
   ```
   name,lat,lon
   The Man,40.783247448000054,-119.20788409599999
   Center Camp,40.777372264000064,-119.21561156099995
   ```
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

4. open `places_2027_fill.geojson` in QGIS / drop on a map. `entered`
   anchors are marked green; `autofilled` things are amber and unconfirmed.

5. spot-check: verify gate/center camp/temple/the man against the year's
   published coords. if any autofilled point is wrong, add it as an anchor
   and re-run.

## files

- repository `reference/` holds the 2026 geometry used as the template base
  (plus the 2024/2025 files kept for the rigidity check above).
- output: `places_YYYY_fill.csv` + `places_YYYY_fill.geojson`.

## options

- `--year NNNN` (required) — target year; reads `anchors_NNNN.csv`
- `--include-streets` — also transform the street grid (rings + avenues)
- `--reference-dir DIR` — where the reference geojson files live