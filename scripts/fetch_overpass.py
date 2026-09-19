#!/usr/bin/env python3
"""Fetch this case study's two Overpass queries into ``data/raw/``.

Pure standard library (``urllib``) so it runs before ``requirements.txt`` is
installed. The two query strings below are the single source of truth and
are reproduced verbatim in ``data/README.md`` - if you change one, change
both, and say why in the commit message.

    python scripts/fetch_overpass.py                 # both layers
    python scripts/fetch_overpass.py --only hospitals
    python scripts/fetch_overpass.py --endpoint https://overpass.kumi.systems/api/interpreter

Writes the raw response bodies to ``data/raw/<layer>.json``. Converting them
to GeoJSON is a separate step, on purpose - the raw response is what you
want to keep when a query returns something surprising:

    python scripts/overpass_to_geojson.py centers   data/raw/hospitals.json          data/raw/hospitals.geojson
    python scripts/overpass_to_geojson.py relations data/raw/mahalle_boundaries.json data/raw/mahalle_boundaries.geojson

If this fails with a proxy 403/407, the session's egress policy blocks
overpass-api.de. Do not route around it - see CLAUDE.md, "Network and
secrets", for the three supported ways to get the data in.
"""
import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"

# NOTE: "İstanbul" below uses the Turkish dotted capital I (U+0130). Overpass
# matches ["name"=...] as an exact string; ASCII "Istanbul" resolves to no
# area and both queries come back with zero elements. See data/README.md
# caveat 1.
QUERIES = {
    "hospitals": """
[out:json][timeout:60];
area["name"="İstanbul"]["admin_level"="4"]->.searchArea;
(
  node["amenity"~"hospital|clinic"](area.searchArea);
  way["amenity"~"hospital|clinic"](area.searchArea);
);
out center;
""".strip(),
    "mahalle_boundaries": """
[out:json][timeout:120];
area["name"="İstanbul"]["admin_level"="4"]->.searchArea;
relation["admin_level"="10"](area.searchArea);
out geom;
""".strip(),
}

RAW_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw"


def fetch(endpoint, query, retries=3, backoff=30):
    """POST one query, retrying on the rate-limit/overload codes Overpass uses."""
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "User-Agent": (
                    "smart-spatial-istanbul-health-access/0.1 "
                    "(+https://github.com/arazshah/smart-spatial-istanbul-health-access)"
                )
            },
        )
        try:
            # Generous: query 2 asks for ~1000 relations with full geometry.
            with urllib.request.urlopen(req, timeout=300) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 504) and attempt < retries:
                wait = backoff * attempt
                print(
                    f"  HTTP {e.code} (Overpass busy), retry {attempt}/{retries - 1} in {wait}s",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError as e:
            last = e
            if attempt < retries:
                wait = backoff * attempt
                print(f"  {e.reason}, retry {attempt}/{retries - 1} in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise last


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--only", choices=sorted(QUERIES), help="fetch just one layer")
    ap.add_argument(
        "--print-queries",
        action="store_true",
        help="print the queries and exit (paste into Overpass Turbo)",
    )
    args = ap.parse_args()

    if args.print_queries:
        for name, q in QUERIES.items():
            print(f"### {name} -> data/raw/{name}.json\n{q}\n")
        return 0

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    names = [args.only] if args.only else list(QUERIES)
    failed = False

    for name in names:
        out = RAW_DIR / f"{name}.json"
        print(f"fetching {name} -> {out}", file=sys.stderr)
        try:
            text = fetch(args.endpoint, QUERIES[name])
        except Exception as e:  # noqa: BLE001 - report, don't mask
            print(f"  FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            print(
                "  If this is a proxy 403/407, the session's egress policy blocks\n"
                "  the endpoint. Do not route around it - see CLAUDE.md.",
                file=sys.stderr,
            )
            failed = True
            continue

        try:
            n = len(json.loads(text).get("elements", []))
        except json.JSONDecodeError:
            # Overpass reports some errors as an HTML page with HTTP 200.
            print("  FAILED: response was not JSON. First 300 chars:", file=sys.stderr)
            print("  " + text[:300].replace("\n", "\n  "), file=sys.stderr)
            failed = True
            continue

        out.write_text(text, encoding="utf-8")
        print(f"  wrote {out} ({len(text):,} bytes, {n} elements)", file=sys.stderr)
        if n == 0:
            print(
                "  WARNING: zero elements. Most likely the area did not resolve -\n"
                "  check the dotted İ survived. See data/README.md caveat 1.",
                file=sys.stderr,
            )
        # Be a good Overpass citizen between the two heavy queries.
        if name != names[-1]:
            time.sleep(5)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
