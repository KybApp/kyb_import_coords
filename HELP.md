# Import Data — Detailed Help

**Language / Язык:** [English](HELP.html) | [Русский](HELP_ru.html)

Full description of all plugin features. If you are launching
it for the first time — start with the "Quick start" section.

---

## 1. Quick start

1. Open the plugin: **Plugins → Import data** (or the button on the `KYB_TOOLS` toolbar).
2. Load data in one of three ways:
   - **File** → click «...» and select a file;
   - **From clipboard** → copy text and click the button;
   - **Drag & drop** the file directly into the plugin window.
3. Look at the table and map. If something is wrong —
   adjust the settings.
4. Enter a layer name (required).
5. Click **«Import»**.

Nothing is added to the QGIS project until «Import» is clicked.
This is intentional: check first, import later.

---

## 2. Plugin window

Left side — preview: data table on top, map below.
Right side — settings blocks:

- **Data source** — file and source CRS.
- **Structure** — parsing parameters, coordinate format and precision (⚙ button), vertex numbering.
- **Geometry** — feature type, style, auxiliary layers, display settings (⚙ button).
- **Result** — layer name and saving to GeoPackage.

At the bottom — **Clear data**, **Import**, **Cancel** buttons.

---

## 3. Data source

### "File" field

Path to the loaded file. Drag & drop supported.

### «...» button

Standard file picker. Filter offers:

- all supported;
- text only;
- Excel only;
- spatial only;
- any file.

### «From clipboard» button

Takes text from the system clipboard. Useful when data is
copied from Excel, a browser, or another document.

### Source CRS

Coordinate system of the input data. Selected via the standard
QGIS dialog. Supported:

- standard EPSG;
- custom CRS added via **Settings → Custom CRS** (shown as `USER:xxxxx`).

**CRS validation.** When «Import» is clicked, the plugin checks:

1. The CRS is recognized by QGIS. If not — import is blocked,
   the CRS block is highlighted in red.
2. Data units match the CRS type: meters — projected,
   degrees — geographic. If not — a warning asks «continue?».

On unit mismatch, a yellow warning appears in the "Data source"
block — visible right after loading data.

---

## 4. Structure

### Format

Detected automatically:

- **Decimal** — `55.7244	36.3638`;
- **DMS in one column** — `55°43'28.05"`;
- **DMS in three columns** — `55	43	28.05	36	21	49.94`.

### Headers

Detected by content: if the first row contains noticeably fewer
numbers than the data — it is treated as a header.

### Start/End row

Allow cutting a header or tail of the file. `End row = 0`
means "to the end".

### Encoding and Delimiter

`UTF-8`, `CP1251`, `UTF-16`. Default is UTF-8.
Delimiter: `auto` (default), `tab`, `comma`, `semicolon`, `space`.

Auto mode picks the most stable delimiter from the first 15 rows.
If the manually selected delimiter does not fit and data cannot be
recognized as coordinates, the plugin suggests switching to a suitable one.

### Order / Axes

Only one of the two toggles is shown:

- **Order: Latitude, Longitude / Longitude, Latitude** — for degrees;
- **Axes: North, East / East, North** — for meters.

Default — North, East for meters and Latitude, Longitude
for degrees. This matches the geodetic axis order in MSK,
GSK-2011 and SK-42.

### Coordinate fields

Field labels change automatically:

- for meters — **North:** / **East:**
- for degrees — **Latitude:** / **Longitude:**.

Number of fields depends on format:

- Decimal — 2;
- DMS in one column — 2;
- DMS in three columns — 6.

### Vertex numbering

Controls how vertices are numbered in the layer (and in the preview table):

- **Auto (per feature)** — for each polygon/line numbering starts at 1.
- **Auto (continuous)** — numbering 1, 2, 3... goes continuously across all features.
- **From column** — numbers are taken from the selected source column. If the column has empty values or is not selected, a yellow warning asks to pick another option.

### «⚙» button (Format & precision)

Opens a dialog for coordinate display settings:
- **Latitude/Longitude:** `Decimal` or `DMS` (degrees-minutes-seconds).
- **Decimal places:** separately for degrees, seconds and meters.

---

## 5. Geometry

### Geometry type

- **Point** — each row is a separate point.
- **Line** — one block is one line.
- **Polygon** — block is split into sub-polygons by repeating the first point.
- **Multipolygon** — same as polygon, but all contours are stored in one feature.

**An empty row** between blocks is always a boundary of a new feature.

For spatial files the type is detected automatically and cannot be changed — the data already is what it is.

### Polygon style

- **Outline** — border only.
- **Fill** — fill only.
- **Outline + fill** — both.

### Vertices at corners and Numbering

Create a separate layer with vertices and labels.

### «⚙» button (Display)

Opens a dialog for map object colors/sizes and labels. See section 8 for details.

---

## 6. Result

### Layer name

Required field. If empty — on «Import» click a yellow warning appears
under the field and a red border. As soon as you start typing — the highlight goes away.

For a spatial file the output may be several layers: `<name> — points`, `<name> — lines`, `<name> — polygons`.

### Save to file (GeoPackage)

If enabled — the result is written to `.gpkg`, and the layer loaded from
the file (not a temporary one) is added to the project.

### Vertex layer

If «Vertices at corners» or «Numbering» is enabled, a second layer
`<name> — vertices` is created. Fields: `num`, `vertex`.

---

## 7. Preview table

One row — one vertex (for points — the point itself).

### Unified table view

The table view does not depend on the source (text, Excel or spatial).
Source columns (if any) are shown on the left, computed columns on the right:

| col1 | col2 | → No. | → Vert. No. | → Type | → Coord1 | → Coord2 | → Area m² | → Area ha | → Perimeter/length m |
|---|---|---|---|---|---|---|---|---|---|
| ... | ... | 1 | 1 | Line | 55.67 | 36.38 | | | 1456.26 |

Area and length are filled **only in the first row of a feature**.
Other vertices — coordinates only.

### Vertex limit

For each feature no more than 80 vertices are shown. If there are more,
instead of the rest a gray row `... vertices hidden: N ...` is shown.
This lets you see all features even if one of them is very long.

### Context menu (right click)

- **Copy** — selected cells to clipboard as TSV (pastes into Excel);
- **Add row** — empty row after the current one;
- **Delete row** — remove the current row.

Row edits are applied to the data and immediately reflected on the map.

**Ctrl+C** copies the whole current selection (row, rectangle, Ctrl+click multi-select) — same as the menu item.

---

## 8. «⚙» settings (two dialogs)

The plugin has two gears for different things.

### In the "Structure" block (Format & precision)

Lets you choose:
- Coordinate format: `Decimal` or `DMS`;
- Degree precision (decimal places);
- Second precision (for DMS);
- Meter precision.

Changes are applied to the table immediately after «OK».
Rounding is visual only — full values go into the layer.

### In the "Geometry" block (Display)

Lets you set:
- Point color and size;
- Line color and width;
- Polygon outline color, width and fill color;
- Number and area label color and size.

The «Reset» button returns default settings (blue points, green lines,
red outline, pink fill). Settings are saved in QgsSettings.

---

## 9. Preview map

### What you see

- Feature geometry — colored by current settings.
- Vertex number labels (if enabled).
- Area labels (for polygons) — shown as `S₁=21237.18 m²`.
- Total area in the top-left corner (for polygons).
- Scale bar in the bottom-left corner.

---

## 10. Area and length calculation

### Units
- Area — m² and ha.
- Length — meters.

### How it's calculated
**For projected CRS** (MSK, GSK-2011, SK-42, UTM): standard QGIS formulas.

**For geographic CRS** (EPSG:4326, WGS84): via Web Mercator. We compute
meters per degree of longitude at the centroid latitude of the feature.
The approximation is valid for features up to a few kilometers.

### Precision
- Area in m² — 2 decimals.
- Area in ha — 4 decimals.
- Perimeter and length in m — 2 decimals.

---

## 11. Excel and spatial files

### Excel (`.xls`, `.xlsx`, `.ods`)
Read via GDAL/OGR — built into QGIS. No external libraries required.
- The first non-empty sheet is taken.
- The first row is treated as a header.
- Limitation: if the file has **no headers**, the first data row will be lost. Save the file as `.csv` and load it as text.

### Spatial files
Read via GDAL/OGR.
- **Shapefile** (`.shp`, `.dbf`, `.shx`, `.prj`);
- **GeoJSON** (`.geojson`, `.json`);
- **KML** (`.kml`);
- **GeoPackage** (`.gpkg`).

**Attributes are transferred** from the source file. If the shapefile had
fields `name`, `type` — they will be in the resulting layer along with our
`num`, `area_m2`, etc.

**Mixed types.** If a single KML has points, lines, and polygons — the plugin
splits them into three layers on output.

---

## 12. Saving and loading settings

What is remembered between sessions:
- delimiter and encoding;
- source CRS and geometry type;
- axis order and vertex numbering;
- display settings, coordinate format and precision;
- GeoPackage save path.

Stored in QgsSettings under the `KYB_import_coords/` prefix.

---

## 13. «Clear data» button

Fully resets the current state (file field, data, table, map and spatial mode).
Fields return to visible state. Settings (delimiter, CRS, colors) are **not** reset.

When loading a new source, clearing happens **automatically** before loading.

---

## 14. FAQ

**The plugin does not appear in the menu.**
Check the path: inside the `KYB_import_coords` folder there must be files
`__init__.py`, `plugin.py`, etc. If there is another nested folder inside —
move the files one level up. Restart QGIS.

**File does not load — "Not coordinate-like".**
Reasons: wrong delimiter, wrong encoding, text instead of numbers in data.
The plugin may suggest another delimiter — accept it if so.

**"Could not read Excel".**
The file is password-protected or damaged. Open in Excel and save as `.csv`.

**"Invalid CRS" error.**
A CRS is selected that QGIS does not have. Open the list, pick a standard one,
or add your own via **Settings → Custom CRS**.

**"Data is not consistent with CRS" warning.**
Data in meters but CRS is geographic (or vice versa). Most likely, the wrong
CRS is selected.

**Feature disappeared from the table.**
Make sure the feature has vertices. If a feature has more than 80 vertices, it
is truncated by a `... vertices hidden: N ...` row (the feature itself is fully
displayed on the map).

**Area labels overlap the contour.**
Not fixed yet. The label is placed at the contour centroid. For complex polygons
it may fall on an edge.