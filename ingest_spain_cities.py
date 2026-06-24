"""
INGESTA COMPLETA — 9 ciudades españolas de Inside Airbnb → Snowflake Bronze
============================================================================
Requisito: pip install snowflake-connector-python

Hace las 3 cosas en orden:
  1. Descarga los CSV.gz de Inside Airbnb
  2. Los sube al stage interno de Snowflake (PUT)
  3. Ejecuta los COPY INTO para cargar en RAW_LISTINGS y RAW_REVIEWS

Sevilla y Málaga ya están en Snowflake — este script carga las 7 nuevas.
Al final valida el recuento de filas por ciudad.

USO:
  python ingest_spain_cities.py

CREDENCIALES:
  Edita el archivo .env en la raíz del proyecto (ya creado con plantilla):
    SNOWFLAKE_ACCOUNT=abc12345.eu-west-1
    SNOWFLAKE_USER=tu_usuario
    SNOWFLAKE_PASSWORD=tu_contraseña

  El script lo carga automáticamente. El .env está en .gitignore — seguro.
"""

import os
import sys
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

# Carga automática de .env si existe en el directorio del proyecto
load_dotenv(Path(__file__).parent / ".env")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG SNOWFLAKE
# ─────────────────────────────────────────────────────────────────────────────
# Tu account identifier lo encuentras en Snowflake → esquina inferior izquierda
# o ejecutando SELECT CURRENT_ACCOUNT() en una worksheet.
# Formato típico: "abc12345" o "abc12345.eu-west-1"

SNOWFLAKE_ACCOUNT  = os.getenv("SNOWFLAKE_ACCOUNT",  "TU_ACCOUNT_AQUI")
SNOWFLAKE_USER     = os.getenv("SNOWFLAKE_USER",     "TU_USUARIO_AQUI")
SNOWFLAKE_PASSWORD = os.getenv("SNOWFLAKE_PASSWORD", "TU_PASSWORD_AQUI")
SNOWFLAKE_WAREHOUSE = "AIRBNB_WH"
SNOWFLAKE_DATABASE  = "AIRBNB_DEV_BRONZE"
SNOWFLAKE_SCHEMA    = "BRONZE"
SNOWFLAKE_STAGE     = "AIRBNB_STAGE"

# ─────────────────────────────────────────────────────────────────────────────
# CIUDADES NUEVAS (Sevilla y Málaga ya están cargadas, se omiten)
#
# URLs CONFIRMADAS: barcelona, girona, euskadi, valencia
# PENDIENTES DE VERIFICAR: madrid, mallorca, menorca
#   → Ve a https://insideairbnb.com/get-the-data/
#     Busca cada ciudad y reemplaza la fecha en la URL.
# ─────────────────────────────────────────────────────────────────────────────

CITIES = {
    "barcelona": {
        "date": "2026-03-21",
        "path": "spain/catalonia/barcelona",
        "verified": True,
    },
    "girona": {
        "date": "2025-12-31",
        "path": "spain/catalonia/girona",
        "verified": True,
    },
    "euskadi": {
        "date": "2025-09-29",
        "path": "spain/pv/euskadi",
        "verified": True,
    },
    "valencia": {
        "date": "2025-09-23",
        "path": "spain/vc/valencia",
        "verified": True,
    },
    "madrid": {
        "date": "2025-09-14",       # ← VERIFICAR en insideairbnb.com/get-the-data
        "path": "spain/comunidad-de-madrid/madrid",
        "verified": True,
    },
    "mallorca": {
        "date": "2025-09-21",       # ← VERIFICAR en insideairbnb.com/get-the-data
        "path": "spain/islas-baleares/mallorca",
        "verified": True,
    },
    "menorca": {
        "date": "2025-09-30",       # ← VERIFICAR en insideairbnb.com/get-the-data
        "path": "spain/islas-baleares/menorca",
        "verified": True,
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

# ─────────────────────────────────────────────────────────────────────────────
# SQL — columnas 1..79 del CSV + literal de ciudad
# ─────────────────────────────────────────────────────────────────────────────

COLS_79 = ",".join(f"${i}" for i in range(1, 80))

COPY_LISTINGS_SQL = """
COPY INTO {db}.{schema}.RAW_LISTINGS
FROM (
    SELECT {cols}, '{city}'
    FROM @{db}.{schema}.{stage}/{filename}
)
FILE_FORMAT = (TYPE='CSV' FIELD_OPTIONALLY_ENCLOSED_BY='"'
               SKIP_HEADER=1 NULL_IF=('','NULL','null','NA')
               EMPTY_FIELD_AS_NULL=TRUE);
"""

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
        print("   Edita las variables al inicio del script o usa variables de entorno.")
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


def put_file(cursor, local_path: Path):
    """Sube un archivo al stage interno de Snowflake."""
    put_sql = (
        f"PUT 'file://{local_path.resolve()}' "
        f"@{SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}.{SNOWFLAKE_STAGE} "
        f"AUTO_COMPRESS=FALSE OVERWRITE=FALSE"
    )
    print(f"  ↑  PUT {local_path.name}...")
    result = cursor.execute(put_sql).fetchone()
    status = result[6] if result else "?"
    print(f"     → {status}")
    return "UPLOADED" in str(status).upper() or "SKIPPED" in str(status).upper()


def copy_into(cursor, city: str, file_type: str, filename: str):
    """Ejecuta el COPY INTO correspondiente."""
    if file_type == "listings":
        sql = COPY_LISTINGS_SQL.format(
            db=SNOWFLAKE_DATABASE, schema=SNOWFLAKE_SCHEMA,
            stage=SNOWFLAKE_STAGE, cols=COLS_79,
            city=city, filename=filename,
        )
    else:
        sql = COPY_REVIEWS_SQL.format(
            db=SNOWFLAKE_DATABASE, schema=SNOWFLAKE_SCHEMA,
            stage=SNOWFLAKE_STAGE,
            city=city, filename=filename,
        )
    result = cursor.execute(sql).fetchone()
    try:
        rows = int(result[0]) if result else 0
    except (ValueError, TypeError):
        # Snowflake devuelve un string cuando el archivo ya fue cargado antes
        rows = 0
    msg = f"{rows:,} filas" if rows > 0 else "ya cargado (skipped)"
    print(f"  ✓  COPY {file_type:8} → {msg}")
    return rows


def validate(cursor):
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


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # Aviso ciudades sin verificar
    unverified = [c for c, d in CITIES.items() if not d["verified"]]
    if unverified:
        print(f"\n⚠️  Ciudades con fecha por verificar: {', '.join(unverified)}")
        print("   Comprueba las URLs en https://insideairbnb.com/get-the-data/")
        resp = input("   ¿Continuar igualmente? (s/n): ").strip().lower()
        if resp != "s":
            print("Edita las fechas en el script y vuelve a ejecutar.")
            sys.exit(0)

    # ── 1. Descargas ──────────────────────────────────────────
    print("\n══ PASO 1: DESCARGA ═══════════════════════════════════")
    download_results = {}
    for city, cfg in CITIES.items():
        base = f"{BASE_URL}/{cfg['path']}/{cfg['date']}/data"
        print(f"\n── {city.upper()}")
        ok_l = download_file(f"{base}/listings.csv.gz",
                             OUTPUT_DIR / city / f"{city}_listings.csv.gz")
        ok_r = download_file(f"{base}/reviews.csv.gz",
                             OUTPUT_DIR / city / f"{city}_reviews.csv.gz")
        download_results[city] = ok_l and ok_r

    failed = [c for c, ok in download_results.items() if not ok]
    if failed:
        print(f"\n✗  Descarga fallida para: {', '.join(failed)}")
        print("   Verifica las URLs y vuelve a ejecutar.")
        sys.exit(1)
    print("\n✅ Todas las descargas completadas.")

    # ── 2 & 3. PUT + COPY INTO ────────────────────────────────
    print("\n══ PASO 2-3: SNOWFLAKE — PUT + COPY INTO ══════════════")
    conn = snowflake_connect()
    cursor = conn.cursor()

    try:
        for city in CITIES:
            print(f"\n── {city.upper()}")
            listings_file = OUTPUT_DIR / city / f"{city}_listings.csv.gz"
            reviews_file  = OUTPUT_DIR / city / f"{city}_reviews.csv.gz"

            put_file(cursor, listings_file)
            put_file(cursor, reviews_file)
            copy_into(cursor, city, "listings", f"{city}_listings.csv.gz")
            copy_into(cursor, city, "reviews",  f"{city}_reviews.csv.gz")

        # ── 4. Validación ─────────────────────────────────────
        print("\n══ PASO 4: VALIDACIÓN ══════════════════════════════")
        validate(cursor)

        print("\n✅ Ingesta completada.")
        print("\nSIGUIENTE PASO:")
        print("  1. Actualiza accepted_values en models/silver/schema.yml (ver dbt_changes_9_cities.md)")
        print("  2. En dbt Cloud → rama dev:")
        print("       dbt run --select silver")
        print("       dbt test --select silver")
        print("       dbt run --select gold")
        print("       dbt test")

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
