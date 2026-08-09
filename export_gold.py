"""
EXPORTACIÓN GOLD → PARQUET
==========================
Exporta las tablas de Gold de Snowflake a archivos Parquet locales.
Estos archivos son los que leerá el dashboard de Streamlit,
sin necesidad de que Snowflake esté activo.

Los archivos se guardan en data/gold/ y se commitean al repo.

USO:
    python3 export_gold.py

Ejecutar cada vez que se actualicen los datos en Snowflake
(después de un nuevo snapshot de Inside Airbnb).
"""

import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

SNOWFLAKE_ACCOUNT   = os.getenv("SNOWFLAKE_ACCOUNT",  "TU_ACCOUNT_AQUI")
SNOWFLAKE_USER      = os.getenv("SNOWFLAKE_USER",     "TU_USUARIO_AQUI")
SNOWFLAKE_PASSWORD  = os.getenv("SNOWFLAKE_PASSWORD", "TU_PASSWORD_AQUI")
SNOWFLAKE_WAREHOUSE = "AIRBNB_WH"
SNOWFLAKE_SCHEMA    = "GOLD"

# Database de origen. Por defecto PROD, que es lo habitual para publicar el
# dashboard. Para exportar desde DEV (p.ej. validar un cambio antes de
# promocionarlo a main) basta con:
#     DBT_DATABASE_GOLD=AIRBNB_DEV_GOLD python3 export_gold.py
SNOWFLAKE_DATABASE  = os.getenv("DBT_DATABASE_GOLD", "AIRBNB_PROD_GOLD")

OUTPUT_DIR = Path("data/gold")

# ─────────────────────────────────────────────────────────────────────────────
# TABLAS A EXPORTAR
# Solo las que necesita el dashboard — no exportamos fact_listings completo
# para mantener el repo ligero.
# ─────────────────────────────────────────────────────────────────────────────

TABLES = {
    # Marts — agregaciones por barrio, host y ciudad (filas pequeñas)
    "mart_neighbourhood_pressure": "SELECT * FROM {db}.{schema}.mart_neighbourhood_pressure",
    "mart_city_comparison":        "SELECT * FROM {db}.{schema}.mart_city_comparison",
    "mart_host_profile":           "SELECT * FROM {db}.{schema}.mart_host_profile",

    # Fact de reviews — serie temporal (pocos cientos de filas)
    "fact_reviews_monthly":        "SELECT * FROM {db}.{schema}.fact_reviews_monthly",

    # Dimensiones de referencia
    "dim_neighbourhood":           "SELECT * FROM {db}.{schema}.dim_neighbourhood",
    "dim_room_type":               "SELECT * FROM {db}.{schema}.dim_room_type",

    # fact_listings filtrado — solo columnas necesarias para el dashboard
    # (coordenadas para el mapa, precio, ocupación, tipo)
    "fact_listings_dashboard": """
        SELECT
            f.listing_id,
            f.city,
            f.is_entire_home,
            f.is_high_availability,
            f.is_active_listing,
            f.price_winsorized,
            f.price_per_person,
            f.estimated_occupancy_l365d,
            f.estimated_revenue_adjusted,
            f.availability_365,
            f.availability_profile,
            f.host_profile,
            f.number_of_reviews_ltm,
            f.review_scores_rating,
            f.snapshot_date,
            n.neighbourhood_cleansed,
            l.latitude,
            l.longitude
        FROM {db}.{schema}.fact_listings f
        LEFT JOIN {db}.{schema}.dim_neighbourhood n
            ON f.neighbourhood_id = n.neighbourhood_id
        LEFT JOIN {db}.{schema}.dim_listing l
            ON f.listing_id = l.listing_id
        WHERE f.is_active_listing = TRUE
    """,
}


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES
# ─────────────────────────────────────────────────────────────────────────────

def snowflake_connect():
    import snowflake.connector
    missing = [k for k, v in {
        "SNOWFLAKE_ACCOUNT":  SNOWFLAKE_ACCOUNT,
        "SNOWFLAKE_USER":     SNOWFLAKE_USER,
        "SNOWFLAKE_PASSWORD": SNOWFLAKE_PASSWORD,
    }.items() if v.startswith("TU_")]
    if missing:
        print(f"✗  Faltan credenciales: {', '.join(missing)}")
        sys.exit(1)

    print(f"🔌 Conectando a Snowflake ({SNOWFLAKE_ACCOUNT} → {SNOWFLAKE_DATABASE})...")
    conn = snowflake.connector.connect(
        account=SNOWFLAKE_ACCOUNT,
        user=SNOWFLAKE_USER,
        password=SNOWFLAKE_PASSWORD,
        warehouse=SNOWFLAKE_WAREHOUSE,
        database=SNOWFLAKE_DATABASE,
        schema=SNOWFLAKE_SCHEMA,
    )
    print("  ✓  Conexión establecida\n")
    return conn


def export_table(conn, name: str, sql: str, output_dir: Path):
    query = sql.format(db=SNOWFLAKE_DATABASE, schema=SNOWFLAKE_SCHEMA)
    print(f"── {name}")
    print(f"   Ejecutando query...")

    cursor = conn.cursor()
    cursor.execute(query)
    df = cursor.fetch_pandas_all()

    rows, cols = df.shape
    print(f"   {rows:,} filas × {cols} columnas")

    # Columnas en minúsculas para consistencia en Streamlit
    df.columns = [c.lower() for c in df.columns]

    out_path = output_dir / f"{name}.parquet"
    df.to_parquet(out_path, index=False, compression="snappy")

    size_kb = out_path.stat().st_size / 1024
    print(f"   ✓  Guardado: {out_path.name} ({size_kb:.0f} KB)\n")
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = snowflake_connect()

    print("══ EXPORTANDO TABLAS GOLD ══════════════════════════════\n")
    total_rows = 0
    for name, sql in TABLES.items():
        try:
            rows = export_table(conn, name, sql, OUTPUT_DIR)
            total_rows += rows
        except Exception as e:
            print(f"  ✗  Error en {name}: {e}\n")

    conn.close()

    print("══ RESUMEN ═════════════════════════════════════════════")
    files = list(OUTPUT_DIR.glob("*.parquet"))
    total_size = sum(f.stat().st_size for f in files) / 1024 / 1024
    print(f"  Archivos generados : {len(files)}")
    print(f"  Tamaño total       : {total_size:.1f} MB")
    print(f"  Total filas        : {total_rows:,}")
    print(f"  Directorio         : {OUTPUT_DIR.resolve()}")

    print("""
✅ Exportación completada.

SIGUIENTE PASO:
  git add data/gold/
  git commit -m "data: export Gold tables to Parquet for Streamlit"
  git push origin dev
""")


if __name__ == "__main__":
    main()
