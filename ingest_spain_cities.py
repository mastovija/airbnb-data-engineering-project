"""
INGESTA COMPLETA — 9 ciudades españolas de Inside Airbnb → Snowflake Bronze
============================================================================
Requisitos: pip install -r requirements.txt

Pasos:
  1. Descarga CSV.gz de Inside Airbnb para cada ciudad
  2. Listings: carga por nombre de columna (pandas) — robusto ante cambios de esquema
  3. Reviews:  carga posicional con PUT + COPY INTO (esquema estable de 6 columnas)
  4. Valida recuento de filas por ciudad

CREDENCIALES — archivo .env en la raíz del proyecto:
    SNOWFLAKE_ACCOUNT=abc12345.eu-west-1
    SNOWFLAKE_USER=tu_usuario
    SNOWFLAKE_PASSWORD=tu_contraseña
"""

import os
import sys
import urllib.request
import urllib.parse
from pathlib import Path

import gzip
import pandas as pd
from dotenv import load_dotenv
from snowflake.connector.pandas_tools import write_pandas

load_dotenv(Path(__file__).parent / ".env")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG SNOWFLAKE
# ─────────────────────────────────────────────────────────────────────────────

SNOWFLAKE_ACCOUNT   = os.getenv("SNOWFLAKE_ACCOUNT",  "TU_ACCOUNT_AQUI")
SNOWFLAKE_USER      = os.getenv("SNOWFLAKE_USER",     "TU_USUARIO_AQUI")
SNOWFLAKE_PASSWORD  = os.getenv("SNOWFLAKE_PASSWORD", "TU_PASSWORD_AQUI")
SNOWFLAKE_WAREHOUSE = "AIRBNB_WH"
SNOWFLAKE_DATABASE  = "AIRBNB_DEV_BRONZE"
SNOWFLAKE_SCHEMA    = "BRONZE"
SNOWFLAKE_STAGE     = "AIRBNB_STAGE"

# ─────────────────────────────────────────────────────────────────────────────
# COLUMNAS ESPERADAS EN RAW_LISTINGS (las 79 originales de Inside Airbnb)
# Se seleccionan por nombre — el orden en el CSV no importa.
# Columnas extra en CSVs nuevos se ignoran automáticamente.
# ─────────────────────────────────────────────────────────────────────────────

RAW_LISTINGS_COLUMNS = [
    "id", "listing_url", "scrape_id", "last_scraped", "source", "name",
    "description", "neighborhood_overview", "picture_url", "host_id",
    "host_url", "host_name", "host_since", "host_location", "host_about",
    "host_response_time", "host_response_rate", "host_acceptance_rate",
    "host_is_superhost", "host_thumbnail_url", "host_picture_url",
    "host_neighbourhood", "host_listings_count", "host_total_listings_count",
    "host_verifications", "host_has_profile_pic", "host_identity_verified",
    "neighbourhood", "neighbourhood_cleansed", "neighbourhood_group_cleansed",
    "latitude", "longitude", "property_type", "room_type", "accommodates",
    "bathrooms", "bathrooms_text", "bedrooms", "beds", "amenities", "price",
    "minimum_nights", "maximum_nights", "minimum_minimum_nights",
    "maximum_minimum_nights", "minimum_maximum_nights", "maximum_maximum_nights",
    "minimum_nights_avg_ntm", "maximum_nights_avg_ntm", "calendar_updated",
    "has_availability", "availability_30", "availability_60", "availability_90",
    "availability_365", "calendar_last_scraped", "number_of_reviews",
    "number_of_reviews_ltm", "number_of_reviews_l30d", "availability_eoy",
    "number_of_reviews_ly", "estimated_occupancy_l365d", "estimated_revenue_l365d",
    "first_review", "last_review", "review_scores_rating", "review_scores_accuracy",
    "review_scores_cleanliness", "review_scores_checkin",
    "review_scores_communication", "review_scores_location", "review_scores_value",
    "license", "instant_bookable", "calculated_host_listings_count",
    "calculated_host_listings_count_entire_homes",
    "calculated_host_listings_count_private_rooms",
    "calculated_host_listings_count_shared_rooms", "reviews_per_month",
]

# ─────────────────────────────────────────────────────────────────────────────
# CIUDADES
# ─────────────────────────────────────────────────────────────────────────────

CITIES = {
    "barcelona": {
        "date": "2026-06-24",
        "path": "spain/catalonia/barcelona",
    },
    "girona": {
        "date": "2026-06-30",
        "path": "spain/catalonia/girona",
    },
    "euskadi": {
        "date": "2026-06-30",
        "path": "spain/pv/euskadi",
    },
    "valencia": {
        "date": "2026-06-26",
        "path": "spain/vc/valencia",
    },
    "madrid": {
        "date": "2026-06-20",
        "path": "spain/comunidad-de-madrid/madrid",
    },
    "mallorca": {
        "date": "2026-06-23",
        "path": "spain/islas-baleares/mallorca",
    },
    "menorca": {
        "date": "2026-06-30",
        "path": "spain/islas-baleares/menorca",
    },
    "malaga": {
        "date": "2026-06-30",
        "path": "spain/andalucía/malaga",
    },
    "sevilla": {
        "date": "2026-06-30",
        "path": "spain/andalucía/sevilla",
    },
}

BASE_URL   = "https://data.insideairbnb.com"
OUTPUT_DIR = Path("data/raw")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    )
}

COPY_REVIEWS_SQL = """
COPY INTO {db}.{schema}.RAW_REVIEWS
FROM (
    SELECT $1,$2,$3,$4,$5,$6,'{city}'
    FROM @{db}.{schema}.{stage}/{filename}
)
FILE_FORMAT = (TYPE='CSV' FIELD_OPTIONALLY_ENCLOSED_BY='"'
               SKIP_HEADER=1 NULL_IF=('','NULL','null','NA')
               EMPTY_FIELD_AS_NULL=TRUE);
"""

# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES
# ─────────────────────────────────────────────────────────────────────────────

def download_file(url: str, dest: Path) -> bool:
    if dest.exists():
        size_mb = dest.stat().st_size / 1024 / 1024
        print(f"  ⏭  Ya existe ({size_mb:.1f} MB): {dest.name}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Codificar caracteres especiales en la URL (ej. 'andalucía')
    url = urllib.parse.quote(url, safe=":/")
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=180) as r:
            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                while chunk := r.read(256 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        mb  = downloaded / 1024 / 1024
                        print(f"\r  ↓  {dest.name}  {mb:.1f} MB ({pct:.0f}%)",
                              end="", flush=True)
        print(f"\r  ✓  {dest.name}  {downloaded/1024/1024:.1f} MB            ")
        return True
    except Exception as e:
        print(f"\n  ✗  Error: {e}")
        if dest.exists():
            dest.unlink()
        return False


def snowflake_connect():
    import snowflake.connector
    missing = [k for k, v in {
        "SNOWFLAKE_ACCOUNT":  SNOWFLAKE_ACCOUNT,
        "SNOWFLAKE_USER":     SNOWFLAKE_USER,
        "SNOWFLAKE_PASSWORD": SNOWFLAKE_PASSWORD,
    }.items() if v.startswith("TU_")]
    if missing:
        print(f"\n✗  Faltan credenciales: {', '.join(missing)}")
        sys.exit(1)

    print(f"\n🔌 Conectando a Snowflake ({SNOWFLAKE_ACCOUNT})...")
    conn = snowflake.connector.connect(
        account=SNOWFLAKE_ACCOUNT,
        user=SNOWFLAKE_USER,
        password=SNOWFLAKE_PASSWORD,
        warehouse=SNOWFLAKE_WAREHOUSE,
        database=SNOWFLAKE_DATABASE,
        schema=SNOWFLAKE_SCHEMA,
    )
    print("  ✓  Conexión establecida")
    return conn


def load_listings_pandas(conn, city: str, path: Path):
    """
    Carga listings por nombre de columna usando pandas + write_pandas.
    Robusto ante cualquier número de columnas o cambios de orden en el CSV.
    """
    print(f"  📖 Leyendo {path.name}...")
    df = pd.read_csv(path, compression="gzip", dtype=str, low_memory=False)
    print(f"     CSV: {len(df):,} filas × {len(df.columns)} columnas")

    # Seleccionar solo las columnas conocidas que existen en el CSV
    cols_presentes = [c for c in RAW_LISTINGS_COLUMNS if c in df.columns]
    cols_ausentes  = [c for c in RAW_LISTINGS_COLUMNS if c not in df.columns]
    df = df[cols_presentes].copy()

    if cols_ausentes:
        print(f"  ⚠️  Columnas ausentes en el CSV (se cargarán como NULL): {cols_ausentes}")
        for col in cols_ausentes:
            df[col] = None

    # Reordenar según el esquema de la tabla + añadir city
    df = df[RAW_LISTINGS_COLUMNS]
    df["city"] = city

    # Snowflake espera nombres de columna en MAYÚSCULAS
    df.columns = [c.upper() for c in df.columns]

    # Borrar filas previas de esta ciudad (idempotente)
    cursor = conn.cursor()
    cursor.execute(
        f"DELETE FROM {SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}.RAW_LISTINGS "
        f"WHERE CITY = '{city}'"
    )
    deleted = cursor.rowcount
    if deleted > 0:
        print(f"  🗑  Eliminadas {deleted:,} filas previas de {city}")

    # Cargar con write_pandas
    print(f"  ↑  Cargando {len(df):,} filas en RAW_LISTINGS...")
    success, nchunks, nrows, _ = write_pandas(
        conn, df,
        table_name="RAW_LISTINGS",
        database=SNOWFLAKE_DATABASE,
        schema=SNOWFLAKE_SCHEMA,
        auto_create_table=False,
        overwrite=False,
    )
    if success:
        print(f"  ✓  {nrows:,} filas cargadas ({nchunks} chunks)")
    else:
        print(f"  ✗  Error en write_pandas para {city}")
    return success


def load_reviews_copy(cursor, city: str, path: Path):
    """Carga reviews con PUT + COPY INTO (esquema estable de 6 columnas)."""
    put_sql = (
        f"PUT 'file://{path.resolve()}' "
        f"@{SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}.{SNOWFLAKE_STAGE} "
        f"AUTO_COMPRESS=FALSE OVERWRITE=TRUE"
    )
    print(f"  ↑  PUT {path.name}...")
    result = cursor.execute(put_sql).fetchone()
    print(f"     → {result[6] if result else '?'}")

    sql = COPY_REVIEWS_SQL.format(
        db=SNOWFLAKE_DATABASE, schema=SNOWFLAKE_SCHEMA,
        stage=SNOWFLAKE_STAGE, city=city, filename=path.name,
    )

    # Borrar previos de esta ciudad antes de recargar
    cursor.execute(
        f"DELETE FROM {SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}.RAW_REVIEWS "
        f"WHERE CITY = '{city}'"
    )
    deleted = cursor.rowcount
    if deleted > 0:
        print(f"  🗑  Eliminadas {deleted:,} reviews previas de {city}")

    result = cursor.execute(sql).fetchone()
    try:
        rows = int(result[0]) if result else 0
        print(f"  ✓  COPY reviews  → {rows:,} filas cargadas")
    except (ValueError, TypeError):
        print(f"  ✓  COPY reviews  → {result[0] if result else 'ok'}")


def validate(conn):
    cursor = conn.cursor()
    print("\n── VALIDACIÓN FINAL ─────────────────────────────────")
    for table, label in [("RAW_LISTINGS", "listings"), ("RAW_REVIEWS", "reviews")]:
        print(f"\n{label}:")
        rows = cursor.execute(
            f"SELECT city, COUNT(*) AS n "
            f"FROM {SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}.{table} "
            f"GROUP BY city ORDER BY n DESC"
        ).fetchall()
        for city, n in rows:
            print(f"  {city:<12}  {n:>10,}")

        # Verificar room_type en listings
    print("\nroom_type NULL por ciudad (debe ser 0 en todas):")
    rows = conn.cursor().execute(
        f"SELECT city, COUNT(*) as nulls "
        f"FROM {SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}.RAW_LISTINGS "
        f"WHERE room_type IS NULL GROUP BY city ORDER BY nulls DESC"
    ).fetchall()
    if rows:
        for city, n in rows:
            print(f"  ⚠️  {city:<12}  {n:,} NULLs")
    else:
        print("  ✓  Sin NULLs en room_type")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # ── 1. Descargas ──────────────────────────────────────────
    print("\n══ PASO 1: DESCARGA ═══════════════════════════════════")
    for city, cfg in CITIES.items():
        base = f"{BASE_URL}/{cfg['path']}/{cfg['date']}/data"
        print(f"\n── {city.upper()}")
        download_file(f"{base}/listings.csv.gz",
                      OUTPUT_DIR / city / f"{city}_listings.csv.gz")
        download_file(f"{base}/reviews.csv.gz",
                      OUTPUT_DIR / city / f"{city}_reviews.csv.gz")

    # ── 2. Snowflake ──────────────────────────────────────────
    print("\n══ PASO 2: SNOWFLAKE ═══════════════════════════════════")
    conn = snowflake_connect()
    cursor = conn.cursor()

    for city in CITIES:
        print(f"\n── {city.upper()}")
        listings_file = OUTPUT_DIR / city / f"{city}_listings.csv.gz"
        reviews_file  = OUTPUT_DIR / city / f"{city}_reviews.csv.gz"

        load_listings_pandas(conn, city, listings_file)
        load_reviews_copy(cursor, city, reviews_file)

    # ── 3. Validación ─────────────────────────────────────────
    print("\n══ PASO 3: VALIDACIÓN ══════════════════════════════════")
    validate(conn)

    conn.close()

    print("\n✅ Ingesta completada.")
    print("\nSIGUIENTE PASO en dbt Cloud (rama dev):")
    print("  dbt run --select silver")
    print("  dbt test --select silver")
    print("  dbt run --select gold")
    print("  dbt test")


if __name__ == "__main__":
    main()
