#!/usr/bin/env python3
"""city_template.py — regenerate stable playa places for a new year.

The playa is a rigid layout: every named place (plazas, portals, stations,
departments, The Man, Gate, ...) sits at a fixed clock + ring distance.
If you know the coordinates of just a handful of anchor points for a new
year, this fits a rigid transform (shift + rotation + uniform scale) from
the reference year to the new year and re-places every other point.

Output marks every place as either:
    'entered'      -> you gave its coordinate (a verified anchor)
    'autofilled'   -> computed from the transform (UNCONFIRMED)
    'suggested'    -> computed exactly, can't be independently verified

Usage:
    python3 city_template.py --year 2027 [--reference-dir reference]
"""

import argparse
import csv
import json
import math
import os
import sys

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

EARTH_RADIUS_FT = 20902231  # mean earth radius in feet

# reference year shipped with the repo (rename if you lift a new reference)
DEFAULT_REF_YEAR = 2026

ANCHORS_BASENAME = "anchors_{year}.csv"
OUT_CSV_BASENAME = "places_{year}_fill.csv"
OUT_GEOJSON_BASENAME = "places_{year}_fill.geojson"


# ---------------------------------------------------------------------------
# geodesy helpers
# ---------------------------------------------------------------------------

def radians(x):
    return math.radians(x)


def to_cartesian(lat, lon):
    """project a lat/lon to local flat-earth XY in feet, origin at (lat0, lon0)."""
    return lon, lat


def bearing_dist(lat1, lon1, lat2, lon2):
    """bearing (deg, 0=N) and distance (ft) between two lat/lon points."""
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlam = radians(lon2 - lon1)

    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    dist = 2 * EARTH_RADIUS_FT * math.asin(math.sqrt(a))

    x = math.sin(dlam) * math.cos(phi2)
    y = (math.cos(phi1) * math.sin(phi2)
         - math.sin(phi1) * math.cos(phi2) * math.cos(dlam))
    bearing = (math.degrees(math.atan2(x, y)) + 360) % 360
    return bearing, dist


def local_xy(lat0, lon0, lat, lon):
    """approx local N/E meters->ft around (lat0, lon0)."""
    dlat = radians(lat - lat0)
    dlon = radians(lon - lon0)
    x = dlon * math.cos(radians(lat0)) * EARTH_RADIUS_FT  # easting, ft
    y = dlat * EARTH_RADIUS_FT                              # northing, ft
    return x, y


def local_to_latlon(lat0, lon0, x, y):
    """inverse of local_xy."""
    lon = lon0 + math.degrees(x / (math.cos(radians(lat0)) * EARTH_RADIUS_FT))
    lat = lat0 + math.degrees(y / EARTH_RADIUS_FT)
    return lat, lon


def fit_similarity(src, dst):
    """fit shift+rotation+uniform-scale mapping src -> dst, return (angle_deg,
    scale, tx_e, ty_n) and residual RMS in ft. src/dst are lists of (x,y) ft
    easting/northing around their own centroids.
    """
    n = len(src)
    sx = sum(p[0] for p in src) / n
    sy = sum(p[1] for p in src) / n
    dx = sum(q[0] for q in dst) / n
    dy = sum(q[1] for q in dst) / n

    # umeyama-style: maximize correlation of centered vectors
    s_c = [(p[0] - sx, p[1] - sy) for p in src]
    d_c = [(q[0] - dx, q[1] - dy) for q in dst]

    # complex products sum: a = sum(d * conj(s))
    a_re = sum(d_c[i][0] * s_c[i][0] + d_c[i][1] * s_c[i][1] for i in range(n))
    a_im = sum(d_c[i][1] * s_c[i][0] - d_c[i][0] * s_c[i][1] for i in range(n))

    s_sq = sum(s_c[i][0] ** 2 + s_c[i][1] ** 2 for i in range(n))

    # rotation angle from atan2(a_im, a_re) is the angle src->dst
    theta = math.atan2(a_im, a_re)
    scale = math.sqrt(a_re ** 2 + a_im ** 2) / s_sq

    # apply to find translation
    c = scale * math.cos(theta)
    s = scale * math.sin(theta)
    t_x = dx - (c * sx - s * sy)
    t_y = dy - (s * sx + c * sy)

    # residuals
    resid = []
    for i in range(n):
        x_src, y_src = s_c[i][0] + sx, s_c[i][1] + sy
        px = c * x_src - s * y_src + t_x
        py = s * x_src + c * y_src + t_y
        rx = px - dst[i][0]
        ry = py - dst[i][1]
        resid.append(math.hypot(rx, ry))

    rms = math.sqrt(sum(r * r for r in resid) / n) if n else 0.0
    return math.degrees(theta), scale, t_x, t_y, rms, resid


def apply_similarity(angle_deg, scale, tx, ty, x, y):
    c = scale * math.cos(radians(angle_deg))
    s = scale * math.sin(radians(angle_deg))
    return c * x - s * y + tx, s * x + c * y + ty


# ---------------------------------------------------------------------------
# data loading
# ---------------------------------------------------------------------------

def load_cpns(path):
    with open(path) as f:
        gj = json.load(f)
    out = []
    for feat in gj["features"]:
        props = feat.get("properties", {})
        lon, lat = feat["geometry"]["coordinates"][:2]
        out.append({
            "uid": props.get("OBJECTID"),
            "name": props.get("NAME"),
            "type": props.get("TYPE", "CPN"),
            "lat": lat,
            "lon": lon,
        })
    return out


def load_plazas(path):
    with open(path) as f:
        gj = json.load(f)
    out = []
    for feat in gj["features"]:
        props = feat.get("properties", {})
        poly = feat["geometry"]["coordinates"][0]
        lat = sum(p[1] for p in poly) / len(poly)
        lon = sum(p[0] for p in poly) / len(poly)
        out.append({
            "uid": props.get("objectid"),
            "name": props.get("name"),
            "type": props.get("type", "Plaza"),
            "lat": lat,
            "lon": lon,
        })
    return out


def load_streets(path):
    """load the street grid: list of (name, kind, [lat,lon,...] vertices)."""
    with open(path) as f:
        gj = json.load(f)
    out = []
    for feat in gj["features"]:
        props = feat.get("properties", {})
        geom = feat.get("geometry")
        if not geom or geom["type"] != "LineString":
            continue
        coords = []
        for lon, lat in geom["coordinates"]:
            # keep only the useful street kinds; 'path' is 4:45-style alleys
            coords.append((lat, lon))
        out.append({
            "name": props.get("name"),
            "kind": props.get("kind"),
            "coords": coords,
        })
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--reference-dir", default="reference")
    ap.add_argument("--include-streets", action="store_true",
                    help="also transform the street grid (rings + avenues)")
    args = ap.parse_args()

    year = args.year
    ref_dir = args.reference_dir
    ref_year = DEFAULT_REF_YEAR

    anchors_path = ANCHORS_BASENAME.format(year=year)
    if not os.path.exists(anchors_path):
        sys.exit(
            f"no {anchors_path} found — create it with columns: name,lat,lon\n"
            "  use exactly the names from the reference files so the template "
            "knows which anchor maps to which place."
        )

    # 1. load reference places
    places = load_cpns(os.path.join(ref_dir, f"cpns_{ref_year}.geojson"))
    places += load_plazas(os.path.join(
        ref_dir, f"plazas_{ref_year}.geojson"))
    ref_by_name = {p["name"]: p for p in places}

    # 2. load anchors
    anchors = []
    with open(anchors_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        parsed = list(reader)
        if not parsed:
            sys.exit(f"{anchors_path} is empty")
        # tolerate a headerless file: first real row looks like data
        if "name" not in parsed[0]:
            for line in parsed:
                vals = list(line.values())
                if len(vals) == 3:
                    anchors.append((vals[0].strip(), float(vals[1]), float(vals[2])))
        else:
            for row in parsed:
                name = row["name"].strip()
                try:
                    lat = float(row["lat"])
                    lon = float(row["lon"])
                except (KeyError, ValueError):
                    sys.exit(f"line in {anchors_path} missing name/lat/lon columns")
                anchors.append((name, lat, lon))
    if not anchors:
        sys.exit("no usable anchor rows — expected name,lat,lon")
    for name, _, _ in anchors:
        if name not in ref_by_name:
            sys.exit(f"anchor '{name}' not in reference data — check spelling")

    if len(anchors) < 2:
        sys.exit("need at least 2 anchors to fit the city transform")

    # 3. fit transform on anchor points, in local flat-earth ft
    lat0 = sum(a[1] for a in anchors) / len(anchors)
    lon0 = sum(a[2] for a in anchors) / len(anchors)

    src = []  # reference anchor coords, ft
    dst = []  # new-year anchor coords, ft
    for name, alat, alon in anchors:
        ref_p = ref_by_name[name]
        rx, ry = local_xy(lat0, lon0, ref_p["lat"], ref_p["lon"])
        nx, ny = local_xy(lat0, lon0, alat, alon)
        src.append((rx, ry))
        dst.append((nx, ny))
    angle, scale, tx, ty, rms, resid = fit_similarity(src, dst)

    print(f"fitted transform  ref{ref_year} -> {year}:")
    print(f"  rotation   = {angle:+.2f} deg")
    print(f"  scale      = {scale:.6f}")
    print(f"  anchor RMS = {rms:.1f} ft")
    print()

    # 4. apply to every place & write output
    rows = []
    geojson = {"type": "FeatureCollection", "features": []}
    for p in places:
        rx, ry = local_xy(lat0, lon0, p["lat"], p["lon"])
        nx, ny = apply_similarity(angle, scale, tx, ty, rx, ry)
        nlat, nlon = local_to_latlon(lat0, lon0, nx, ny)

        status = "entered" if p["name"] in {a[0] for a in anchors} else "autofilled"
        err_ft = ""
        if p["name"] in {a[0] for a in anchors}:
            # find the residual for this anchor
            idx = [a[0] for a in anchors].index(p["name"])
            err_ft = f"{resid[idx]:.1f}"

        rows.append({
            "name": p["name"],
            "type": p["type"],
            "status": status,
            "residual_ft": err_ft,
            "gps_latitude": round(nlat, 8),
            "gps_longitude": round(nlon, 8),
        })

        geojson["features"].append({
            "type": "Feature",
            "properties": {
                "name": p["name"],
                "type": p["type"],
                "status": status,
                "residual_ft": err_ft,
            },
            "geometry": {"type": "Point", "coordinates": [nlon, nlat]},
        })

    rows.sort(key=lambda r: (r["status"] != "entered", r["name"]))

    # 4b. optionally transform the street grid too
    streets_added = 0
    if args.include_streets:
        streets_path = os.path.join(
            ref_dir, f"street_lines_{ref_year}.geojson")
        if os.path.exists(streets_path):
            for s in load_streets(streets_path):
                coords = []
                for slat, slon in s["coords"]:
                    rx, ry = local_xy(lat0, lon0, slat, slon)
                    nx, ny = apply_similarity(angle, scale, tx, ty, rx, ry)
                    nlat, nlon = local_to_latlon(lat0, lon0, nx, ny)
                    coords.append([nlon, nlat])
                geojson["features"].append({
                    "type": "Feature",
                    "properties": {
                        "name": s["name"],
                        "kind": s["kind"],
                        "status": "autofilled_street",
                        "residual_ft": "",
                    },
                    "geometry": {"type": "LineString", "coordinates": coords},
                })
                streets_added += 1
        else:
            print(f"  (no street_lines_{ref_year}.geojson in {ref_dir}; "
                  "skipping streets)")

    out_csv = OUT_CSV_BASENAME.format(year=year)
    out_gj = OUT_GEOJSON_BASENAME.format(year=year)
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["name", "type", "status", "residual_ft",
                           "gps_latitude", "gps_longitude"])
        w.writeheader()
        w.writerows(rows)
    with open(out_gj, "w") as f:
        json.dump(geojson, f, indent=2)

    n_fill = sum(1 for r in rows if r["status"] == "autofilled")
    print(f"wrote {out_csv} and {out_gj}")
    print(f"  {len(anchors)} entered anchor(s), {n_fill} autofilled (unconfirmed)")
    if streets_added:
        print(f"  + {streets_added} street lines autofilled")
    print()
    print(" NOTE: autofilled points are UNCONFIRMED. Verify important ones "
          "and re-run with more anchors.")


if __name__ == "__main__":
    main()