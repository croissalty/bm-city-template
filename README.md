# burning man city template

turn a handful of anchor coordinates for a new burn into the whole predicted
city layout: every named place (plazas, portals, departments, the man, ...)
plus the street grid, and a ready-to-open QGIS map.

black rock city is a rigid layout — every place sits at a fixed clock + ring
distance from the man. give the tool a few places you're sure about for the
new year and it fits the shift/rotation/scale and re-derives everything else.

## quick start

```bash
# 1. put your anchors in anchors_2027.csv (see anchors_2026.csv for the format)
# 2. run
python3 city_template.py --year 2027 --include-streets
# 3. open the map
open bm_city_2027.qgs
```

data + map land in the same folder:

| file                     | what it is                                  |
|--------------------------|---------------------------------------------|
| `places_2027_fill.csv`   | every predicted place as a row              |
| `places_2027_fill.geojson` | points (green = entered, amber = autofilled) |
| `streets_2027_fill.geojson` | the street grid as line features           |
| `anchors_2027.geojson`   | just the anchors you entered                |
| `bm_city_2027.qgs`       | open this in QGIS (opens zoomed on the city) |
| `bm_city_2027_preview.png` | a render of the same project               |

the `.qgs` is authored by QGIS itself (via its bundled python), so project
crs, layer crs and styles are always correct — and the playa renders round
because the project is in EPSG:3857.

## docs

full workflow, anchor tips, caveats and test results: **`USAGE.md`**.

## sanity checks

```bash
python3 test_sanity.py
```

## note

autofilled points are predictions and **unconfirmed** — verify anything
important against the year's official published coordinates once they drop
(see caveats in `USAGE.md`).