#!/usr/bin/env python3
"""test_sanity.py — smoke tests for the city-template pipeline.

stdlib only; run from the repo root:
    python3 test_sanity.py

checks:
- anchors load from the csv (incl. headerless format)
- the similarity fit recovers a known shift (and is identity on the 2026
  anchor set, which came from the reference data)
- every reference place re-projects back into a sensible playa area and
  exactly the anchor-verified + autofilled split falls out
- the street grid transforms without error
"""

import csv
import math
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, HERE)

import city_template as ct

REF_YEAR = ct.DEFAULT_REF_YEAR
REF_DIR = os.path.join(HERE, "reference")


def load_reference_places():
    places = ct.load_cpns(os.path.join(REF_DIR, f"cpns_{REF_YEAR}.geojson"))
    places += ct.load_plazas(os.path.join(REF_DIR, f"plazas_{REF_YEAR}.geojson"))
    return places


def fit_from_anchors(anchors, places):
    """whole pipeline fit: returns (anchors, angle, scale, rms, transformed)."""
    by_name = {p["name"]: p for p in places}
    lat0 = sum(a[1] for a in anchors) / len(anchors)
    lon0 = sum(a[2] for a in anchors) / len(anchors)
    src, dst = [], []
    for name, alat, alon in anchors:
        p = by_name[name]
        src.append(ct.local_xy(lat0, lon0, p["lat"], p["lon"]))
        dst.append(ct.local_xy(lat0, lon0, alat, alon))
    angle, scale, tx, ty, rms, _ = ct.fit_similarity(src, dst)
    out = []
    for p in places:
        x, y = ct.local_xy(lat0, lon0, p["lat"], p["lon"])
        nx, ny = ct.apply_similarity(angle, scale, tx, ty, x, y)
        out.append({"name": p["name"], "lat": ct.local_to_latlon(
            lat0, lon0, nx, ny)[0], "lon": ct.local_to_latlon(lat0, lon0, nx, ny)[1]})
    return anchors, angle, scale, rms, out


class TestAnchors(unittest.TestCase):

    def test_csv_with_header(self):
        anchors = ct.read_anchors_csv(os.path.join(HERE, f"anchors_{REF_YEAR}.csv"))
        self.assertGreaterEqual(len(anchors), 2)
        for name, lat, lon in anchors:
            self.assertIsInstance(name, str)
            self.assertTrue(-180 < lon < 180)
            self.assertTrue(-90 < lat < 90)

    def test_headerless_csv(self):
        with tempfile.NamedTemporaryFile(
                "w", suffix=".csv", delete=False, newline="") as f:
            f.write("The Man,40.783, -119.208\n")
            f.write("Center Camp, 40.777372264, -119.215611561\n")
            path = f.name
        try:
            anchors = ct.read_anchors_csv(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(anchors), 2)
        self.assertEqual(anchors[0][0], "The Man")
        self.assertAlmostEqual(anchors[1][1], 40.777372264)

    def test_parse_anchor_arg(self):
        name, lat, lon = ct.parse_anchor_arg("Gate Actual, 40.781234123, -119.213456789")
        self.assertEqual(name, "Gate Actual")
        self.assertAlmostEqual(lat, 40.781234123)
        self.assertAlmostEqual(lon, -119.213456789)


class TestFit(unittest.TestCase):

    def setUp(self):
        self.places = load_reference_places()
        self.by_name = {p["name"]: p for p in self.places}
        self.anchors = ct.read_anchors_csv(
            os.path.join(HERE, f"anchors_{REF_YEAR}.csv"))
        self.assertGreaterEqual(len(self.anchors), 2)

    def test_2026_anchors_are_identity(self):
        _, angle, scale, rms, _ = fit_from_anchors(self.anchors, self.places)
        self.assertLess(abs(angle), 0.01, "expected ~zero rotation")
        self.assertAlmostEqual(scale, 1.0, delta=1e-6)
        self.assertLess(rms, 0.1, "anchors should sit on the reference grid")

    def test_known_shift_recovered(self):
        shift_n = -50.0  # ft north (+y in the local frame)
        shift_e = 30.0
        anchors = []
        for name, alat, alon in self.anchors:
            nlat, nlon = ct.local_to_latlon(alat, alon, shift_e, shift_n)
            anchors.append((name, nlat, nlon))
        _, angle, scale, rms, _ = fit_from_anchors(anchors, self.places)
        self.assertAlmostEqual(scale, 1.0, delta=1e-6)
        self.assertLess(abs(angle), 0.01)
        self.assertLess(rms, 0.5, "a pure shift must fit with ~0 residual")

    def test_all_places_transform_to_playa_area(self):
        _, _, _, rms, out = fit_from_anchors(self.anchors, self.places)
        self.assertEqual(len(out), len(self.places))
        self.assertLess(rms, 0.1)
        for p in out:
            self.assertTrue(40.65 <= p["lat"] <= 40.9)
            self.assertTrue(-119.35 <= p["lon"] <= -119.05)
        anchor_names = {a[0] for a in self.anchors}
        entered = sum(1 for p in out if p["name"] in anchor_names)
        autofilled = sum(1 for p in out if p["name"] not in anchor_names)
        self.assertEqual(entered, len(self.anchors))
        self.assertEqual(entered + autofilled, len(out))


class TestStreets(unittest.TestCase):

    def test_street_grid_transforms(self):
        streets_path = os.path.join(
            REF_DIR, f"street_lines_{REF_YEAR}.geojson")
        self.assertTrue(os.path.exists(streets_path))
        streets = ct.load_streets(streets_path)
        self.assertGreaterEqual(len(streets), 500, "grid should be dense")

        anchors = ct.read_anchors_csv(os.path.join(HERE, f"anchors_{REF_YEAR}.csv"))
        places = load_reference_places()
        lat0 = sum(a[1] for a in anchors) / len(anchors)
        lon0 = sum(a[2] for a in anchors) / len(anchors)
        src, dst = [], []
        by_name = {p["name"]: p for p in places}
        for name, alat, alon in anchors:
            p0 = by_name[name]
            src.append(ct.local_xy(lat0, lon0, p0["lat"], p0["lon"]))
            dst.append(ct.local_xy(lat0, lon0, alat, alon))
        angle, scale, tx, ty, _, _ = ct.fit_similarity(src, dst)

        count = 0
        for s in streets:
            for slat, slon in s["coords"]:
                x, y = ct.local_xy(lat0, lon0, slat, slon)
                nx, ny = ct.apply_similarity(angle, scale, tx, ty, x, y)
                nlat, nlon = ct.local_to_latlon(lat0, lon0, nx, ny)
                self.assertTrue(40.6 <= nlat <= 40.95, "vertex in playa band")
                self.assertTrue(-119.4 <= nlon <= -119.0, "vertex in playa band")
                count += 1
        self.assertGreater(count, 2000, "transform every grid vertex")


class TestPipelineWrite(unittest.TestCase):

    def test_csv_component_outputs_parse(self):
        # the committed output files from the real runs must parse cleanly
        csv_path = os.path.join(HERE, f"places_{REF_YEAR}_fill.csv")
        gj_path = os.path.join(HERE, f"places_{REF_YEAR}_fill.geojson")
        self.assertTrue(os.path.exists(csv_path))
        self.assertTrue(os.path.exists(gj_path))
        with open(csv_path, newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 72, "2026 grid has 72 named places")
        with open(gj_path) as f:
            import json
            gj = json.load(f)
        self.assertEqual(len(gj["features"]), len(rows))
        statuses = {r["status"] for r in rows}
        self.assertLessEqual(statuses, {"entered", "autofilled"})


if __name__ == "__main__":
    unittest.main(verbosity=2)