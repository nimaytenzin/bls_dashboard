#!/usr/bin/env python3
"""Build liveability heatmap GeoJSON and interactive HTML from PostGIS boundaries."""

import json
import re
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ASSETS_DIR = ROOT / "assets"
OUT_GEOJSON = ASSETS_DIR / "liveability_heatmap.geojson"
OUT_HTML = ROOT / "heatmap.html"

DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "dbname": "nsfd_backend_dev",
    "user": "postgres",
    "password": "mysecretpassword",
}

TOWN_DB_NAMES = {
    "Thimphu": "Thimphu Thromde",
    "Mongar": "Mongar",
    "Phuentsholing": "Phuentshogling Thromde",
    "Samdrup Jongkhar": "Samdrupjongkhar Thromde",
}

# Colours taken from the source Excel legend (theme fills sampled / explicit fills read)
LEGEND = [
    {"range_min": 0, "range_max": 20, "label": "Very low liveable", "color": "#C52115"},
    {"range_min": 21, "range_max": 40, "label": "Low liveable", "color": "#F5B4B0"},
    {"range_min": 41, "range_max": 60, "label": "Moderate liveable", "color": "#D4F1DB"},
    {"range_min": 61, "range_max": 80, "label": "High Liveable", "color": "#92D050"},
    {"range_min": 81, "range_max": 100, "label": "Very high liveable", "color": "#00B050"},
]
NO_DATA_COLOR = "#FFFFFF"
NO_DATA_LABEL = "Data not available"


def categorize(idx):
    if idx is None or pd.isna(idx):
        return NO_DATA_LABEL
    if idx <= 20:
        return LEGEND[0]["label"]
    if idx <= 40:
        return LEGEND[1]["label"]
    if idx < 61:
        return LEGEND[2]["label"]
    if idx <= 80:
        return LEGEND[3]["label"]
    return LEGEND[4]["label"]


def color_for(idx):
    if idx is None or pd.isna(idx):
        return NO_DATA_COLOR
    if idx <= 20:
        return LEGEND[0]["color"]
    if idx <= 40:
        return LEGEND[1]["color"]
    if idx < 61:
        return LEGEND[2]["color"]
    if idx <= 80:
        return LEGEND[3]["color"]
    return LEGEND[4]["color"]


THIMPHU_LAP_GROUPS = {
    "Dechencholing I, II, IIIa, IIIb, IV": [
        "Dechencholing I", "Dechencholing II", "Dechencholing III a",
        "Dechencholing III b", "Dechencholing IV",
    ],
    "Taba 1a, 1b, 1c, IIb, IIc, IId": [
        "Taba I a", "Taba I b", "Taba I c", "Taba II b", "Taba II c", "Taba II d",
    ],
    "Hejo Samtenling I a, I b, Ic, II, III": [
        "Hejo Samtenling I a", "Hejo Samtenling I b", "Hejo Samtenling I c",
        "Hejo Samtenling II", "Hejo Samtenling III",
    ],
    "Zilukha I, II, III, IV, V": [
        "Zilukha I", "Zilukha II", "Zilukha III", "Zilukha IV", "Zilukha V",
    ],
    "Lower Motitang 1 a, 1 b, 1 c, 1 d, 1 e, II a, II b, III a, III b, III c": [
        "Lower Motithang I a", "Lower Motithang I b", "Lower Motithang I c",
        "Lower Motithang I d", "Lower Motithang I e", "Lower Motithang II a",
        "Lower Motithang II b", "Lower Motithang III a", "Lower Motithang IIIb",
        "Lower Motithang III c",
    ],
    "Upper Motithang 1 a, 1 b, 1 c,": [
        "Upper Motithang I a", "Upper Motithang I b", "Upper Motithang I c",
    ],
    "Core a,b,c,d,e,f,g": [
        "Core a", "Core b", "Core c", "Core d", "Core e", "Core f", "Core g",
    ],
    "Changangkha 1a, 1b, IIa, II b, IIc": [
        "Changangkha I a", "Changangkha I b", "Changangkha II a",
        "Changangkha II b", "Changangkha II c",
    ],
    "Changzamtog I a, Ib, IIa, IIb, IIIa, IIIb, IIIc, IIId, IV a, IV b": [
        "Changzamtok I a", "Changzamtok I b", "Changzamtok II a", "Changzamtok II b",
        "Changzamtok III a", "Changzamtok III b", "Changzamtok III c",
        "Changzamtok III d", "Changzamtok IV a", "Changzamtok IV b",
    ],
    "Yangchenphu": ["Yangchenphu"],
    "Changdangdu, Changdangdu I,": ["Changbangdu", "Changbangdu I"],
    "Lungtenphu 1 a, 1 b, 1 c, 1 d, 1 e, 1 ea, 1 f, II": [
        "Lungtenphu I a", "Lungtenphu I b", "Lungtenphu I c", "Lungtenphu I d",
        "Lungtenphu I e", "Lungtenphu I ea", "Lungtenphu I f", "Lungtenphu II",
    ],
    "Lungtenphu 1 e": ["Lungtenphu I e"],
    "Semtokha a, b, c, d": ["Semtokha a", "Semtokha b", "Semtokha c", "Semtokha d"],
    "Semtokha d": ["Semtokha d"],
    "Babesa 1 a, 1 b, 1 Ba, II": ["Babesa I a", "Babesa I b", "Babesa I Ba", "Babesa II"],
}

MONGAR_LAP_GROUPS = {f"LA {i}": [] for i in range(1, 6)}
PHUENTSHOLING_LAP_GROUPS = {
    "Toorsatar": ["Lap 1"],
    "Amo Chu lap": ["Lap 2"],
    "Dhamdara lap": ["Lap 3"],
    "Core a, b, c, d, e, f, g, h, i, j, k, l, m": [
        "Lap 4a", "Lap 4b", "Lap 4c", "Lap 4d", "Lap 4e", "Lap 4f", "Lap 4g",
        "Lap 4h", "Lap 4i", "Lap 4j", "Lap 4k", "lap 4l", "Lap 4m",
    ],
    "Kabraytar LAP": ["Lap 5"],
    "Rinchending": ["Lap 6"],
    "Kareyphu LAP": ["Lap 7"],
    "Ahlay LAP": ["Lap 8"],
    "Pasakha Lap": ["Lap 9", "Lap 10"],
    "Pekarzhing LAP": ["Lap 11"],
    "Pasakha Industrail Estate": ["Lap 11a"],
}

SAMDRUP_LAP_GROUPS = {
    "Core": ["Lap 1"],
    "Service Center": ["Lap 2", "Lap 3a"],
    "Football ground side a and b": ["Lap 3b"],
    "Behind Dzong": ["Lap 4"],
    "Deothang 5a, 5b, 5ba, 5c": ["Lap 5a", "Lap 5b", "Lap 5ba", "lap 5c"],
}

TOWN_LAP_GROUPS = {
    "Thimphu": THIMPHU_LAP_GROUPS,
    "Mongar": MONGAR_LAP_GROUPS,
    "Phuentsholing": PHUENTSHOLING_LAP_GROUPS,
    "Samdrup Jongkhar": SAMDRUP_LAP_GROUPS,
}


def load_liveability_data():
    path = "/home/kwangyel/Downloads/Liveability Data for heatmaps (1).xlsx"
    df = pd.read_excel(path, sheet_name="Visualization Pla", header=None)

    def clean(val):
        if pd.isna(val):
            return None
        s = str(val).strip()
        return s if s else None

    def parse_index(val):
        if pd.isna(val):
            return None
        try:
            return round(float(val), 4)
        except (ValueError, TypeError):
            return None

    records = []
    for i in range(4, 20):
        la, div, idx = clean(df.iloc[i, 1]), clean(df.iloc[i, 2]), parse_index(df.iloc[i, 3])
        if la:
            records.append({"town": "Thimphu", "local_area": la, "division": div, "index": idx})
    for i in range(5, 10):
        la, idx = clean(df.iloc[i, 5]), parse_index(df.iloc[i, 6])
        if la and la not in ("Local Areas Combined", "INDEX"):
            records.append({"town": "Mongar", "local_area": la, "division": None, "index": idx})
    for i in range(12, 19):
        la, idx = clean(df.iloc[i, 5]), parse_index(df.iloc[i, 6])
        if la and la not in ("Local Areas", "INDEX", "Samdrup Jongkhar"):
            records.append({"town": "Samdrup Jongkhar", "local_area": la, "division": None, "index": idx})
    for i in range(23, 34):
        la, idx = clean(df.iloc[i, 1]), parse_index(df.iloc[i, 2])
        if la and la not in ("Local Areas Combined", "INDEX"):
            records.append({"town": "Phuentsholing", "local_area": la, "division": None, "index": idx})

    heatmap_df = pd.DataFrame(records)
    heatmap_df["has_data"] = heatmap_df["index"].notna()
    heatmap_df["category"] = heatmap_df["index"].apply(categorize)
    heatmap_df["color"] = heatmap_df["index"].apply(color_for)
    heatmap_df.to_csv(DATA_DIR / "liveability_heatmap_data.csv", index=False)
    return heatmap_df


def fetch_boundaries(conn):
    query = """
        SELECT
            d.name AS dzongkhag,
            az.name AS town,
            saz.id AS saz_id,
            saz.name AS lap_name,
            saz."areaCode" AS area_code,
            saz.type AS zone_type,
            ST_AsGeoJSON(ST_SimplifyPreserveTopology(ST_MakeValid(saz.geom), 0.00005))::json AS geometry
        FROM "SubAdministrativeZones" saz
        JOIN "AdministrativeZones" az ON az.id = saz."administrativeZoneId"
        JOIN "Dzongkhags" d ON d.id = az."dzongkhagId"
        WHERE az.name = ANY(%(towns)s)
          AND az.name <> 'Thimphu Thromde'
          AND saz.geom IS NOT NULL
        ORDER BY az.name, saz."areaCode"
    """
    towns = list(TOWN_DB_NAMES.values())
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, {"towns": towns})
        return cur.fetchall()


# Thimphu is visualised as the three TSP divisions, each dissolved from its LAPs.
THIMPHU_DIVISION_CASE = """
    CASE
      WHEN saz.name ILIKE 'Dechencholing%%' OR saz.name ILIKE 'Taba%%' OR saz.name ILIKE 'Hejo%%'
        THEN 'Northern Thimphu'
      WHEN saz.name ILIKE 'Lungtenphu%%' OR saz.name ILIKE 'Semtokha%%' OR saz.name ILIKE 'Babesa%%'
        THEN 'Southern Thimphu'
      ELSE 'Central Thimphu'
    END
"""


def fetch_thimphu_divisions(conn):
    """Dissolve Thimphu LAPs into 3 TSP divisions that tile with no gaps.

    1. Union LAPs per division.
    2. Build a solid city footprint (buffer-close small gaps, fill interior rings).
    3. Compute leftover gap areas and assign each to the nearest division,
       so no white space remains inside the city boundary.
    """
    query = f"""
        WITH laps AS (
            SELECT {THIMPHU_DIVISION_CASE} AS division,
                   ST_MakeValid(saz.geom) AS geom
            FROM "SubAdministrativeZones" saz
            JOIN "AdministrativeZones" az ON az.id = saz."administrativeZoneId"
            WHERE az.name = 'Thimphu Thromde'
              AND saz.geom IS NOT NULL
        ),
        counts AS (
            SELECT division, count(*) AS lap_count FROM laps GROUP BY division
        ),
        divs AS (
            SELECT division, ST_UnaryUnion(ST_Collect(geom)) AS geom
            FROM laps GROUP BY division
        ),
        allgeom AS (
            SELECT ST_UnaryUnion(ST_Collect(geom)) AS geom FROM laps
        ),
        solid AS (
            -- close gaps up to ~160 m between LAPs/divisions
            SELECT ST_Buffer(ST_Buffer(geom, 0.0008), -0.0008) AS geom FROM allgeom
        ),
        hull AS (
            -- fill any remaining interior rings: keep exterior rings only
            SELECT ST_UnaryUnion(ST_Collect(ST_MakePolygon(ST_ExteriorRing((dp).geom)))) AS geom
            FROM (SELECT ST_Dump(geom) AS dp FROM solid) t
        ),
        gaps AS (
            SELECT ST_CollectionExtract(
                       ST_MakeValid(ST_Difference(h.geom, a.geom)), 3
                   ) AS geom
            FROM hull h, allgeom a
        ),
        n AS (
            SELECT ST_UnaryUnion(ST_Collect(x.geom)) AS geom FROM (
                SELECT geom FROM divs WHERE division = 'Northern Thimphu'
                UNION ALL
                SELECT ST_CollectionExtract(
                           ST_Intersection(g.geom, ST_Buffer(d.geom, 0.002)), 3)
                FROM gaps g, divs d WHERE d.division = 'Northern Thimphu'
            ) x
        ),
        c AS (
            SELECT ST_UnaryUnion(ST_Collect(x.geom)) AS geom FROM (
                SELECT geom FROM divs WHERE division = 'Central Thimphu'
                UNION ALL
                SELECT ST_CollectionExtract(ST_MakeValid(ST_Difference(
                           ST_Intersection(g.geom, ST_Buffer(d.geom, 0.002)),
                           n.geom)), 3)
                FROM gaps g, divs d, n WHERE d.division = 'Central Thimphu'
            ) x
        ),
        s AS (
            SELECT ST_UnaryUnion(ST_Collect(x.geom)) AS geom FROM (
                SELECT geom FROM divs WHERE division = 'Southern Thimphu'
                UNION ALL
                SELECT ST_CollectionExtract(ST_MakeValid(
                           ST_Difference(ST_Difference(g.geom, n.geom), c.geom)), 3)
                FROM gaps g, n, c
            ) x
        ),
        final AS (
            SELECT 'Northern Thimphu' AS division, geom FROM n
            UNION ALL
            SELECT 'Central Thimphu', geom FROM c
            UNION ALL
            SELECT 'Southern Thimphu', geom FROM s
        )
        SELECT
            'Thimphu' AS dzongkhag,
            f.division,
            ct.lap_count,
            ST_AsGeoJSON(
                -- ~1 m outward buffer: zones overlap microscopically instead of
                -- leaving snap-artifact slivers along shared borders
                ST_CollectionExtract(
                    ST_MakeValid(ST_SnapToGrid(ST_Buffer(f.geom, 0.00001), 0.000005)), 3)
            )::json AS geometry
        FROM final f
        JOIN counts ct ON ct.division = f.division
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query)
        return cur.fetchall()


def build_thimphu_features(liveability_df, division_rows):
    thimphu = liveability_df[liveability_df["town"] == "Thimphu"]
    index_by_division = {
        row["division"]: float(row["index"])
        for _, row in thimphu.iterrows()
        if pd.notna(row.get("division")) and pd.notna(row["index"])
    }

    order = {"Northern Thimphu": "01", "Central Thimphu": "02", "Southern Thimphu": "03"}
    features = []
    for row in sorted(division_rows, key=lambda r: order.get(r["division"], "99")):
        division = row["division"]
        idx = index_by_division.get(division)
        features.append({
            "type": "Feature",
            "geometry": row["geometry"],
            "properties": {
                "saz_id": None,
                "town": "Thimphu",
                "db_town": "Thimphu Thromde",
                "dzongkhag": row["dzongkhag"],
                "lap_name": division,
                "area_code": order.get(division),
                "zone_type": f"division · {row['lap_count']} LAPs",
                "local_area_group": division,
                "division": division,
                "index": idx,
                "has_data": idx is not None,
                "category": categorize(idx),
                "color": color_for(idx),
            },
        })
    return features


def resolve_mongar_groups(rows):
    by_code = sorted(rows, key=lambda r: r["area_code"])
    for i in range(1, 6):
        if i <= len(by_code):
            MONGAR_LAP_GROUPS[f"LA {i}"] = [by_code[i - 1]["lap_name"]]


def build_lap_lookup(liveability_df, boundaries):
    resolve_mongar_groups([r for r in boundaries if r["town"] == TOWN_DB_NAMES["Mongar"]])

    lookup = {}
    for _, row in liveability_df.iterrows():
        town = row["town"]
        local_area = row["local_area"]
        groups = TOWN_LAP_GROUPS.get(town, {})
        lap_names = groups.get(local_area, [])
        for lap_name in lap_names:
            lookup[(town, lap_name)] = {
                "local_area": local_area,
                "division": row["division"] if pd.notna(row.get("division")) else None,
                "index": None if pd.isna(row["index"]) else float(row["index"]),
                "has_data": bool(row["has_data"]),
                "category": row["category"],
                "color": row["color"],
            }
    return lookup


def town_from_db_name(db_town):
    for town, db_name in TOWN_DB_NAMES.items():
        if db_name == db_town:
            return town
    return db_town


def build_geojson(boundaries, lap_lookup):
    town_display = {v: k for k, v in TOWN_DB_NAMES.items()}
    features = []
    for row in boundaries:
        town = town_display.get(row["town"], row["town"])
        lap_name = row["lap_name"]
        stats = lap_lookup.get((town, lap_name), {
            "local_area": None,
            "division": None,
            "index": None,
            "has_data": False,
            "category": NO_DATA_LABEL,
            "color": NO_DATA_COLOR,
        })
        features.append({
            "type": "Feature",
            "geometry": row["geometry"],
            "properties": {
                "saz_id": row["saz_id"],
                "town": town,
                "db_town": row["town"],
                "dzongkhag": row["dzongkhag"],
                "lap_name": lap_name,
                "area_code": row["area_code"],
                "zone_type": row["zone_type"],
                "local_area_group": stats["local_area"],
                "division": stats["division"],
                "index": stats["index"],
                "has_data": stats["has_data"],
                "category": stats["category"],
                "color": stats["color"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


def clean_geometry(geometry):
    """Remove interior rings (white holes inside polygons).

    Parts are never dropped: tiny fragments may be filling seams between
    adjacent features, and removing them would open hairline gaps.
    """
    holes_removed = 0
    if geometry["type"] == "Polygon":
        holes_removed = len(geometry["coordinates"]) - 1
        geometry["coordinates"] = [geometry["coordinates"][0]]
    elif geometry["type"] == "MultiPolygon":
        kept = []
        for polygon in geometry["coordinates"]:
            holes_removed += len(polygon) - 1
            kept.append([polygon[0]])
        geometry["coordinates"] = kept
    return holes_removed


def clean_geojson(geojson_data):
    total_holes = 0
    for feature in geojson_data["features"]:
        total_holes += clean_geometry(feature["geometry"])
    return total_holes


def write_assets(geojson_data):
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    with open(OUT_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(geojson_data, f)

    town_files = {}
    for town in sorted({f["properties"]["town"] for f in geojson_data["features"]}):
        slug = town.lower().replace(" ", "_")
        path = ASSETS_DIR / f"{slug}.geojson"
        town_fc = {
            "type": "FeatureCollection",
            "features": [f for f in geojson_data["features"] if f["properties"]["town"] == town],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(town_fc, f)
        town_files[town] = path
    return town_files


def build_html(geojson_data):
    """Render the dashboard HTML from scripts/template.html."""
    template = (Path(__file__).resolve().parent / "template.html").read_text(encoding="utf-8")

    preferred_order = ["Thimphu", "Phuentsholing", "Samdrup Jongkhar", "Mongar"]
    present = {f["properties"]["town"] for f in geojson_data["features"]}
    towns = [t for t in preferred_order if t in present] + sorted(present - set(preferred_order))

    no_data = {"color": NO_DATA_COLOR, "label": NO_DATA_LABEL}
    return (
        template
        .replace("__LEGEND__", json.dumps(LEGEND))
        .replace("__NO_DATA__", json.dumps(no_data))
        .replace("__TOWNS__", json.dumps(towns))
    )


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    liveability_df = load_liveability_data()

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        boundaries = fetch_boundaries(conn)
        thimphu_divisions = fetch_thimphu_divisions(conn)
    finally:
        conn.close()

    lap_lookup = build_lap_lookup(liveability_df, boundaries)
    geojson_data = build_geojson(boundaries, lap_lookup)
    geojson_data["features"].extend(build_thimphu_features(liveability_df, thimphu_divisions))

    holes = clean_geojson(geojson_data)
    town_files = write_assets(geojson_data)

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(build_html(geojson_data))

    matched = sum(1 for f in geojson_data["features"] if f["properties"]["local_area_group"])
    with_data = sum(1 for f in geojson_data["features"] if f["properties"]["has_data"])
    print(f"Boundaries: {len(geojson_data['features'])}")
    print(f"Mapped to liveability groups: {matched}")
    print(f"With index data: {with_data}")
    print(f"Cleanup: removed {holes} interior holes")
    print(f"Combined GeoJSON: {OUT_GEOJSON}")
    for town, path in town_files.items():
        print(f"  {town}: {path.relative_to(ROOT)}")
    print(f"HTML map: {OUT_HTML}")


if __name__ == "__main__":
    main()
