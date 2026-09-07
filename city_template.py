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
import subprocess
import sys

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

EARTH_RADIUS_FT = 20902231  # mean earth radius in feet

# reference year shipped with the repo (rename if you lift a new reference)
DEFAULT_REF_YEAR = 2026

ANCHORS_BASENAME = "anchors_{year}.csv"
ANCHORS_GEOJSON_BASENAME = "anchors_{year}.geojson"
OUT_CSV_BASENAME = "places_{year}_fill.csv"
OUT_GEOJSON_BASENAME = "places_{year}_fill.geojson"
STREETS_GEOJSON_BASENAME = "streets_{year}_fill.geojson"
QGSPROJ_BASENAME = "bm_city_{year}.qgs"


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


def read_anchors_csv(path):
    """read an anchors csv: either name,lat,lon header or headerless rows."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        raw = [r for r in csv.reader(f)
               if r and any(cell.strip() for cell in r)]
    if not raw:
        return []
    has_header = raw[0][0].strip().lower() == "name"
    anchors = []
    for row in raw[1:] if has_header else raw:
        if len(row) < 3:
            continue
        anchors.append((row[0].strip(), float(row[1]), float(row[2])))
    return anchors


def parse_anchor_arg(text):
    """parse 'name, lat, lon' tolerance of spaces and extra commas."""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 3:
        raise ValueError(f"expected 'name,lat,lon' — got: {text!r}")
    return parts[0], float(parts[1]), float(parts[2])


def prompt_anchors():
    """interactive fallback so you can type anchors straight in the shell."""
    print("no anchors file — enter anchors one per line as: name, lat, lon")
    print("(blank line to finish)")
    anchors = []
    while True:
        try:
            line = input("anchor> ").strip()
        except EOFError:
            break
        if not line:
            break
        try:
            anchors.append(parse_anchor_arg(line))
        except ValueError as e:
            print(f"  skip: {e}")
    return anchors


def collect_anchors(args, anchors_path, ref_by_name):
    """anchors come from a csv, repeated --anchor flags, or a prompt."""
    anchors = []
    if os.path.exists(anchors_path):
        anchors = read_anchors_csv(anchors_path)
        if not anchors:
            print(f"  ({anchors_path} was empty; falling back to --anchor/prompt)")
    for fa in getattr(args, "anchor", None) or []:
        anchors.append(parse_anchor_arg(fa))
    if not os.path.exists(anchors_path) and not getattr(args, "anchor", None):
        anchors = prompt_anchors()

    seen = {}
    for name, lat, lon in anchors:
        if name in seen:
            sys.exit(f"duplicate anchor '{name}' given twice")
        seen[name] = True
        if name not in ref_by_name:
            sys.exit(f"anchor '{name}' not in reference data — check spelling")
    if len(anchors) < 2:
        sys.exit("need at least 2 anchors to fit the city transform")
    return anchors


# ---------------------------------------------------------------------------
# QGIS project (.qgs) generation -- QGIS itself authors the project
# ---------------------------------------------------------------------------

# QGIS python bundled with the app. set QGIS_PYTHON to override.
QGIS_MAC_QPY = "/Applications/QGIS.app/Contents/MacOS/python3.12"
MAKEPROJ = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "make_qgis_project.py")


def _qgis_env(qpy):
    """the env the QGIS-bundled python needs to run headless."""
    contents = os.path.dirname(os.path.dirname(qpy))  # .../QGIS.app/Contents
    return {
        "PYTHONHOME": os.path.join(contents, "Frameworks"),
        "PYTHONPATH": os.path.join(contents, "Resources", "python"),
        "QGIS_PREFIX_PATH": os.path.join(contents, "MacOS"),
        "DYLD_FRAMEWORK_PATH": os.path.join(contents, "Frameworks"),
        "PROJ_LIB": os.path.join(contents, "Resources", "qgis", "proj"),
        "QT_QPA_PLATFORM": "offscreen",
    }


def build_qgis_project_via_qgis(year, workdir, ref_year=DEFAULT_REF_YEAR):
    """run make_qgis_project.py under the QGIS-bundled python so QGIS itself
    authors bm_city_<year>.qgs: project CRS, layer CRSs, styles and the osm
    tile base are all correct by construction (no hand-written XML)."""
    qpy = os.environ.get("QGIS_PYTHON", QGIS_MAC_QPY)
    if not os.path.exists(qpy):
        print(f"  (QGIS python not found at {qpy}; set QGIS_PYTHON to also "
              "generate the ready-to-open map)")
        return None
    env = dict(os.environ)
    env.update(_qgis_env(qpy))
    cmd = [qpy, MAKEPROJ, str(year), os.path.abspath(workdir), str(ref_year)]
    proc = subprocess.run(cmd, env=env, cwd=workdir, text=True)
    if proc.returncode != 0:
        raise RuntimeError("QGIS project step failed (see output above)")
    qgs_path = QGSPROJ_BASENAME.format(year=year)
    return qgs_path if os.path.exists(qgs_path) else None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--reference-dir", default="reference")
    ap.add_argument("--include-streets", action="store_true",
                    help="also transform the street grid (rings + avenues)")
    ap.add_argument("--anchor", action="append", metavar="'name,lat,lon'",
                    help="an anchor you entered (repeatable; no csv file needed)")
    args = ap.parse_args()

    year = args.year
    ref_dir = args.reference_dir
    ref_year = DEFAULT_REF_YEAR

    anchors_path = ANCHORS_BASENAME.format(year=year)

    # 1. load reference places
    places = load_cpns(os.path.join(ref_dir, f"cpns_{ref_year}.geojson"))
    places += load_plazas(os.path.join(
        ref_dir, f"plazas_{ref_year}.geojson"))
    ref_by_name = {p["name"]: p for p in places}

    # 2. get anchors (csv file, --anchor flags, or an interactive prompt)
    anchors = collect_anchors(args, anchors_path, ref_by_name)

    # 2b. dot anchor points for QGIS/a quick glance
    anchor_names = [a[0] for a in anchors]
    anchor_gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "properties": {"name": a[0], "source": "entered"},
         "geometry": {"type": "Point", "coordinates": [a[2], a[1]]}}
        for a in anchors]}
    with open(ANCHORS_GEOJSON_BASENAME.format(year=year), "w") as f:
        json.dump(anchor_gj, f, indent=2)

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

        status = "entered" if p["name"] in anchor_names else "autofilled"
        err_ft = ""
        if p["name"] in anchor_names:
            idx = anchor_names.index(p["name"])
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

    # 4b. optionally transform the street grid into its own geojson (clean
    #     LineString layer so QGIS renders it properly under the points)
    streets_added = 0
    streets_gj = {"type": "FeatureCollection", "features": []}
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
                streets_gj["features"].append({
                    "type": "Feature",
                    "properties": {
                        "name": s["name"],
                        "kind": s["kind"],
                        "street_status": "autofilled",
                    },
                    "geometry": {"type": "LineString", "coordinates": coords},
                })
                streets_added += 1
        else:
            print(f"  (no street_lines_{ref_year}.geojson in {ref_dir}; "
                  "skipping streets)")

    out_csv = OUT_CSV_BASENAME.format(year=year)
    out_gj = OUT_GEOJSON_BASENAME.format(year=year)
    streets_gj_path = STREETS_GEOJSON_BASENAME.format(year=year)
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["name", "type", "status", "residual_ft",
                           "gps_latitude", "gps_longitude"])
        w.writeheader()
        w.writerows(rows)
    with open(out_gj, "w") as f:
        json.dump(geojson, f, indent=2)
    if args.include_streets:
        with open(streets_gj_path, "w") as f:
            json.dump(streets_gj, f, indent=2)

    # 4c. let QGIS itself author the ready-to-open project (project CRS,
    #     layer CRSs, styles and the osm base all come out correct)
    qgs_path = build_qgis_project_via_qgis(
        year, os.getcwd(), ref_year)

    n_fill = sum(1 for r in rows if r["status"] == "autofilled")
    print(f"wrote {out_csv}, {out_gj}"
          + (f", {streets_gj_path}" if args.include_streets else "")
          + f", anchors_{year}.geojson")
    print(f"  {len(anchors)} entered anchor(s), {n_fill} autofilled (unconfirmed)")
    if streets_added:
        print(f"  + {streets_added} street lines autofilled")
    print()
    if qgs_path:
        print(f" QGIS: double-click {qgs_path} to open the ready-to-go map")
    else:
        print(" QGIS map: skipped (QGIS python not found)")
    print()
    print(" NOTE: autofilled points are UNCONFIRMED. Verify important ones "
          "and re-run with more anchors.")


if __name__ == "__main__":
    main()