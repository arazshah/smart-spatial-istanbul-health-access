# Data

Nothing under `data/raw/` is committed (see `.gitignore`). This file is the
record of where the data comes from, the exact queries that produce it, and
how to regenerate it. `data/processed/` — the small derived GeoJSON actually
fed into `smart_spatial_system` — *is* committed once the data-prep notebook
produces it.

## Area of interest

**İstanbul Province (il), Turkey** — the whole administrative province on
both the European and Asian sides, not the smaller historic-peninsula or
metropolitan-core definitions.

| | |
|---|---|
| AOI | İstanbul Province, `admin_level=4` in OSM |
| OSM name tag | `İstanbul` (Turkish dotted capital **İ**, U+0130 — not ASCII `I`) |
| Approx. bbox (WGS 84) | 27.95 – 29.96 E, 40.80 – 41.68 N |
| Units of analysis | *mahalle* (neighbourhood), ~960 expected — `admin_level` **unconfirmed, see caveat 6** |
| Source CRS | EPSG:4326 |
| **Analysis CRS** | **EPSG:32635** — WGS 84 / UTM zone 35N |

EPSG:32635 is the metric CRS used for every distance, threshold and area
computation. Zone 35N (24°–30° E) covers all of İstanbul Province; the
province's eastern edge (~29.96° E) stays inside it, so no zone split is
needed. Distances are in metres, which is what the 2000 m threshold assumes.
Anything reported in metres that was computed in EPSG:4326 is wrong by
construction — see `CLAUDE.md`'s CRS note.

## Sources

Both layers come from OpenStreetMap via the
[Overpass API](https://overpass-api.de/api/interpreter).

| Layer | File | OSM selection |
|---|---|---|
| Hospitals and clinics | `data/raw/hospitals.geojson` | `amenity=hospital` or `amenity=clinic`, nodes and ways, within the AOI |
| Mahalle boundaries | `data/raw/mahalle_boundaries.geojson` | `admin_level=10` relations within the AOI (**verify the level — caveat 6**) |

## The exact queries

Run against `https://overpass-api.de/api/interpreter` (POST the query as the
`data` parameter, or paste it into [Overpass Turbo](https://overpass-turbo.eu/)
and Run ▶). `scripts/fetch_overpass.py` sends exactly these two strings;
`scripts/download_istanbul_data.md` is the manual/browser fallback.

### 1. Hospitals and clinics → `data/raw/hospitals.geojson`

```
[out:json][timeout:60];
area["name"="İstanbul"]["admin_level"="4"]->.searchArea;
(
  node["amenity"~"hospital|clinic"](area.searchArea);
  way["amenity"~"hospital|clinic"](area.searchArea);
);
out center;
```

`out center` returns each **way** as a single representative point in a
`center` field (not a full `geometry`), and each **node** as its own
`lat`/`lon`. Both become `Point` features — which is what
`nearest_neighbor` wants. Convert with:

```
python scripts/overpass_to_geojson.py centers data/raw/hospitals.json data/raw/hospitals.geojson
```

### 2. Mahalle boundaries → `data/raw/mahalle_boundaries.geojson`

```
[out:json][timeout:120];
area["name"="İstanbul"]["admin_level"="4"]->.searchArea;
relation["admin_level"="10"](area.searchArea);
out geom;
```

`out geom` returns every member way's full coordinate list, so the relations
can be assembled into `Polygon`/`MultiPolygon` without a second lookup.
Convert with:

```
python scripts/overpass_to_geojson.py relations data/raw/mahalle_boundaries.json data/raw/mahalle_boundaries.geojson
```

## Known caveats — check these against the real response, don't assume

These are the things most likely to make the queries above return something
other than what this file claims. Record what actually came back in
`notebooks/01_data_and_problem.ipynb` rather than trusting the numbers here.

1. **`area["name"="İstanbul"]` is an exact string match on the dotted `İ`.**
   If a shell, editor or copy-paste step normalises it to ASCII `I` or
   lowercase `i`, the area resolves to nothing and both queries return zero
   elements. A zero-element response is this bug until proven otherwise.
   `["name:tr"="İstanbul"]` or the province's OSM relation id
   (`area(3600223474)`-style, id to be confirmed at fetch time, not assumed
   here) are the fallbacks.
2. **`admin_level=4` without `boundary=administrative`** can in principle
   match a non-boundary object carrying the same tags. Add
   `["boundary"="administrative"]` if the area looks wrong.
3. **Hospital *relations* are not fetched.** The query selects `node` and
   `way` only, per the study design. A large hospital campus mapped as a
   multipolygon relation is therefore missing. Count how many
   `type=multipolygon` + `amenity=hospital` relations exist in the AOI
   before deciding this is negligible, and name it in the paper's
   limitations either way.
4. **`amenity~"hospital|clinic"` is an unanchored regex**, so it also matches
   any future/rare value *containing* those substrings. Report the actual
   distinct `amenity` values found; if it is exactly
   `{hospital, clinic}`, say so.
5. **Hospitals vs. clinics are very different facilities.** Keep the
   `amenity` value as a property through the whole pipeline so the analysis
   can be re-run hospital-only. "Nearest hospital *or* clinic" is the
   headline definition, and that choice has to be visible.
6. **⚠️ `admin_level=10` for mahalle is the study brief's assumption, and
   the evidence points the other way — verify it before anything else.**
   Two independent OSM-derived Turkish administrative datasets map *mahalle*
   at **`admin_level=8`**, not 10: `osadikoglu/turkey-admin-units-osm`
   (il = 4, ilçe = 6, mahalle = 8 polygons, köy = `place=village` nodes;
   13,793 mahalle polygons nationwide) and Geolocet's Turkey neighbourhoods
   product, also level 8. Neither the OSM wiki's `boundary=administrative`
   country table nor WikiProject Turkey could be read far enough to settle
   it, and this session could not reach Overpass to check empirically — so
   this is a strong signal, not a confirmed fact. **Settle it with real
   data before running phase 1:**

   ```
   python scripts/fetch_overpass.py --probe
   ```

   which counts boundary relations at levels 6/8/9/10 inside the AOI and
   prints example names. The mahalle level is the one with roughly 950–1000
   relations carrying neighbourhood-sized names (İstanbul Province has ~960
   mahalle); `admin_level=6` should come back with ~39, the *ilçe*. Then
   pass the answer as `--mahalle-admin-level` and record the probe output in
   `notebooks/01_data_and_problem.ipynb`. If level 10 returns zero or a
   handful, that is this caveat, not a broken query — and the query text
   above should be corrected here and in `scripts/fetch_overpass.py` in the
   same commit, with a note that it diverges from the original brief.

   Separately: some mahalle may be missing from OSM entirely or have broken
   rings. The converter reports skipped relations — count them rather than
   letting them vanish, and state the coverage fraction in the paper. If OSM
   mahalle coverage for İstanbul turns out to be materially incomplete, the
   unit of analysis itself needs revisiting (see `paper/PLAN.md`'s open
   decisions), because "underserved" computed over a partial set of
   neighbourhoods is not a defensible map.
7. **Overpass rate-limits and times out.** The 120 s timeout on query 2 is
   not generous for ~1000 relations with full geometry; a 429 or a partial
   response is normal and should be retried, not worked around with a
   smaller AOI.

## Regenerating

1. `python scripts/fetch_overpass.py` (needs a route to `overpass-api.de`)
   writes the two raw JSON responses into `data/raw/`; or fetch them any
   other way and drop them there under the same names.
2. `python scripts/overpass_to_geojson.py ...` for each, as above.
3. Run `notebooks/01_data_and_problem.ipynb` end to end. It reads
   `data/raw/`, does the minimal cleaning (drop null/invalid geometry, keep
   only the needed fields, reproject to EPSG:32635, assert the CRS), records
   the real feature counts, and writes `data/processed/`.

## License

OpenStreetMap data is © OpenStreetMap contributors, available under the
[Open Database License (ODbL)](https://www.openstreetmap.org/copyright).
Anything derived from it and redistributed here (`data/processed/`, the
figures, the underserved-mahalle table) carries the same attribution
requirement — retained in each processed file's metadata and repeated in the
paper's Data Availability section. The repository's own code is MIT
(`LICENSE`); the data is not.
