#!/usr/bin/env python3
"""make_qgis_project.py — build bm_city_<year>.qgs using QGIS itself.

runs under the QGIS-bundled python so the .qgs is QGIS-authored and always
parses. usage:
    python3 make_qgis_project.py <year> <workdir> [ref_year]

reads the outputs city_template.py already wrote in <workdir> and writes:
    osm_tiles_<year>.xml        gdal TMS config for the OpenStreetMap base
    bm_city_<year>.qgs          the self-contained QGIS project
    bm_city_<year>_preview.png  verification render of the project
"""

import os
import sys

YEAR = sys.argv[1]
WORK = os.path.abspath(sys.argv[2])
REF_YEAR = sys.argv[3] if len(sys.argv) > 3 else "2026"
PROJNAME = f"burning man {YEAR} predicted city"

from qgis.core import (QgsApplication, QgsProject, QgsVectorLayer,
                       QgsRasterLayer, QgsCategorizedSymbolRenderer,
                       QgsRendererCategory, QgsMarkerSymbol,
                       QgsLineSymbol, QgsFillSymbol,
                       QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsRectangle, QgsReferencedRectangle,
                       QgsMapSettings, QgsMapRendererCustomPainterJob,
                       QgsSettings)
try:
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QImage, QPainter, QColor
except ImportError:
    from PyQt5.QtCore import QSize
    from PyQt5.QtGui import QImage, QPainter, QColor

app = QgsApplication([], False)
app.initQgis()

p = QgsProject.instance()
p.clear()
p.setTitle(PROJNAME)
p.setCrs(QgsCoordinateReferenceSystem.fromEpsgId(3857))


def vlayer(path, name):
    lyr = QgsVectorLayer(os.path.join(WORK, path), name, "ogr")
    if not lyr.isValid():
        raise RuntimeError(f"could not load {path}: "
                           + lyr.dataProvider().error().message())
    return lyr


def osm_layer():
    """OpenStreetMap raster tiles via the gdal TMS driver.

    uses gdal (always present) instead of the wms provider so the project and
    its preview can be built in a headless environment.
    """
    xml = os.path.join(WORK, f"osm_tiles_{YEAR}.xml")
    with open(xml, "w") as f:
        f.write(f"""<GDAL_WMS>
  <Service name="TMS">
    <ServerUrl>https://tile.openstreetmap.org/${{z}}/${{x}}/${{y}}.png</ServerUrl>
    <SRS>EPSG:3857</SRS>
    <MaxConnections>4</MaxConnections>
    <CachePath>tilecache</CachePath>
  </Service>
  <DataWindow>
    <UpperLeftX>-20037508.34</UpperLeftX>
    <UpperLeftY>20037508.34</UpperLeftY>
    <LowerRightX>20037508.34</LowerRightX>
    <LowerRightY>-20037508.34</LowerRightY>
    <TileLevel>18</TileLevel>
    <TileCountX>1</TileCountX>
    <TileCountY>1</TileCountY>
    <YOrigin>top</YOrigin>
  </DataWindow>
  <Projection>EPSG:3857</Projection>
  <BlockSizeX>256</BlockSizeX>
  <BlockSizeY>256</BlockSizeY>
  <BandsCount>3</BandsCount>
</GDAL_WMS>
""")
    lyr = QgsRasterLayer(xml, "OpenStreetMap", "gdal")
    if not lyr.isValid():
        raise RuntimeError("OpenStreetMap tile layer failed: "
                           + lyr.error().message())
    return lyr


# bottom -> top draw order
base = osm_layer()
p.addMapLayer(base)
draw_order = [base]

plazas = vlayer(os.path.join('reference', f"plazas_{REF_YEAR}.geojson"),
                f"plazas {REF_YEAR}")
plazas.renderer().setSymbol(QgsFillSymbol.createSimple(
    {'color': '188,158,255,70', 'outline_color': '139,108,230,150',
     'outline_width': '0.3'}))
p.addMapLayer(plazas)
draw_order.append(plazas)

portals = vlayer(os.path.join('reference', f"cpns_{REF_YEAR}.geojson"),
                 f"street portals {REF_YEAR}")
portals.renderer().setSymbol(QgsMarkerSymbol.createSimple(
    {'name': 'circle', 'size': '1.6', 'color': '#5a5a5a',
     'outline_color': '#222222', 'outline_width': '0.2'}))
p.addMapLayer(portals)
draw_order.append(portals)

outlines_path = os.path.join(WORK, 'reference',
                             f"street_outlines_{REF_YEAR}.geojson")
if os.path.exists(outlines_path):
    outlines = vlayer(outlines_path, f"street corridors {REF_YEAR}")
    outlines.renderer().setSymbol(QgsFillSymbol.createSimple(
        {'color': '200,200,200,35', 'outline_color': '150,150,150,90',
         'outline_width': '0.2'}))
    p.addMapLayer(outlines)
    draw_order.append(outlines)

streets_path = os.path.join(WORK, f"streets_{YEAR}_fill.geojson")
if os.path.exists(streets_path):
    streets = vlayer(streets_path, f"streets {YEAR} (predicted)")
    streets.renderer().setSymbol(QgsLineSymbol.createSimple(
        {'color': '#8c8c8c', 'width': '0.7'}))
    p.addMapLayer(streets)
    draw_order.append(streets)

anchors = vlayer(f"anchors_{YEAR}.geojson", "anchors (entered)")
anchors.renderer().setSymbol(QgsMarkerSymbol.createSimple(
    {'name': 'star', 'size': '4.2', 'color': '#155d3a',
     'outline_color': '#ffffff', 'outline_width': '0.5'}))
p.addMapLayer(anchors)
draw_order.append(anchors)

places = vlayer(f"places_{YEAR}_fill.geojson", f"places {YEAR} (predicted)")
entered = QgsMarkerSymbol.createSimple(
    {'name': 'circle', 'size': '3.4', 'color': '#27906c',
     'outline_color': '#155d3a', 'outline_width': '0.4'})
autofill = QgsMarkerSymbol.createSimple(
    {'name': 'circle', 'size': '2.8', 'color': '#f0a500',
     'outline_color': '#b07a00', 'outline_width': '0.4'})
rend = QgsCategorizedSymbolRenderer('status', [
    QgsRendererCategory('entered', entered, 'entered (you entered this)', True),
    QgsRendererCategory('autofilled', autofill,
                        'autofilled (unconfirmed)', True)])
places.setRenderer(rend)
p.addMapLayer(places)
draw_order.append(places)


def bounds():
    rect = QgsRectangle()
    got = False
    for lyr in draw_order:
        if lyr.type() != 0:
            continue
        ex = lyr.extent()
        if ex.isEmpty():
            continue
        if not got:
            rect = QgsRectangle(ex)
            got = True
        else:
            rect.combineExtentWith(ex)
    if got:
        src = QgsCoordinateReferenceSystem.fromEpsgId(4326)
        dst = QgsCoordinateReferenceSystem.fromEpsgId(3857)
        rect = QgsCoordinateTransform(src, dst, p).transformBoundingBox(rect)
        rect.grow(rect.width() * 0.12)
    return rect


def render_preview(rect):
    settings = QgsMapSettings()
    settings.setDestinationCrs(p.crs())
    settings.setLayers(list(reversed(draw_order)))  # draw_order[0]=OSM=bottom; settings are top-down
    settings.setExtent(rect)
    settings.setOutputSize(QSize(1500, 1000))
    settings.setBackgroundColor(QColor(255, 255, 255))
    image = QImage(1500, 1000, QImage.Format_RGB32)
    painter = QPainter(image)
    job = QgsMapRendererCustomPainterJob(settings, painter)
    job.start()
    job.waitForFinished()
    painter.end()
    preview = os.path.join(WORK, f"bm_city_{YEAR}_preview.png")
    image.save(preview)
    return preview


rect = bounds()
# bake an initial view centred on the playa so the project opens zoomed in
QgsSettings().setValue("qgis/saveProjectViewSettings", True)
p.viewSettings().setDefaultViewExtent(
    QgsReferencedRectangle(rect, QgsCoordinateReferenceSystem.fromEpsgId(3857)))

qgs = os.path.join(WORK, f"bm_city_{YEAR}.qgs")
ok = p.write(qgs)
if not ok:
    raise RuntimeError("qgis would not write the project")
preview = render_preview(rect)
print(f"QVOK wrote {qgs}")
print(f"QVOK preview {preview}")
sys.stdout.flush()
os._exit(0)  # skip Qt teardown (segfaults headless)