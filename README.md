# Presión del alquiler turístico sobre el mercado residencial en España

Pipeline de data engineering que monitoriza el impacto de Airbnb sobre el mercado
de vivienda en las **9 ciudades españolas** disponibles en Inside Airbnb, con
actualización trimestral automática y dashboard público.

---

## La pregunta

> *¿Está Airbnb presionando el mercado de vivienda en España?*
> *Medido desde tres ángulos: cuánta vivienda está siendo capturada,*
> *quién la captura y cuánto dinero genera hacerlo.*

---

## Stack tecnológico

| Herramienta | Uso |
|---|---|
| **Inside Airbnb** | Fuente de datos — snapshots trimestrales |
| **Python** | Ingesta automatizada — descarga y carga en Snowflake |
| **Snowflake** | Data warehouse — Bronze, Silver y Gold |
| **dbt Cloud** | Transformaciones SQL, tests y documentación |
| **Streamlit** | Dashboard público interactivo *(en desarrollo)* |
| **GitHub** | Control de versiones — ramas dev y main |

---

## Ciudades cubiertas (9)

| Ciudad | Región | Listings aprox. |
|---|---|---|
| Madrid | Comunidad de Madrid | 25.000 |
| Málaga | Andalucía | 19.000 |
| Girona | Cataluña | 17.000 |
| Sevilla | Andalucía | 16.500 |
| Barcelona | Cataluña | 16.000 |
| Mallorca | Islas Baleares | 15.000 |
| Valencia | Comunitat Valenciana | 7.800 |
| Euskadi | País Vasco | 6.300 |
| Menorca | Islas Baleares | 3.700 |

**Total: ~126.000 listings · ~5.3M reviews**

---

## Arquitectura — Medallion Architecture

```
Inside Airbnb (CSV.gz)
        │
        ▼ ingest_spain_cities.py
┌─────────────┐
│   BRONZE    │  Dato crudo · Todo TEXT · Sin transformaciones
│             │  RAW_LISTINGS (80 col · ~126K filas)
│             │  RAW_REVIEWS  (~5.3M filas)
└──────┬──────┘
       │ dbt
       ▼
┌─────────────┐
│   SILVER    │  Dato limpio · Views · 6 modelos temáticos
│             │  Tipos casteados · Columnas calculadas
│             │  Winsorización P95 por ciudad · host_profile
└──────┬──────┘
       │ dbt
       ▼
┌─────────────┐
│    GOLD     │  Dato analítico · Tables · Esquema estrella
│             │  3 dims + 2 facts + 3 marts
│             │  Incremental · SCD Tipo 2 · Seeds
└──────┬──────┘
       │
       ▼
   Streamlit (dashboard público)
```

### Arquitectura de entornos

| Entorno | Databases Snowflake | Branch GitHub |
|---|---|---|
| DEV | AIRBNB_DEV_BRONZE / SILVER / GOLD | dev |
| PROD | AIRBNB_PROD_BRONZE / SILVER / GOLD | main |

---

## Estructura del proyecto

```
spain-airbnb-housing-pressure/
├── ingest_spain_cities.py       ← descarga + carga en Snowflake
├── requirements.txt
├── models/
│   ├── silver/
│   │   ├── sources.yml
│   │   ├── schema.yml
│   │   ├── stg_listings__details.sql
│   │   ├── stg_listings__host.sql
│   │   ├── stg_listings__location.sql
│   │   ├── stg_listings__availability.sql
│   │   ├── stg_listings__reviews_scores.sql
│   │   └── stg_reviews.sql
│   └── gold/
│       ├── schema.yml
│       ├── dims/
│       │   ├── dim_listing.sql
│       │   ├── dim_host.sql
│       │   └── dim_neighbourhood.sql
│       ├── facts/
│       │   ├── fact_listings.sql        ← incremental
│       │   └── fact_reviews_monthly.sql
│       └── marts/
│           ├── mart_neighbourhood_pressure.sql
│           ├── mart_host_profile.sql
│           └── mart_city_comparison.sql
├── seeds/
│   └── dim_room_type.csv
├── snapshots/
│   └── dim_host_snapshot.sql            ← SCD Tipo 2
└── macros/
    └── generate_schema_name.sql
```

---

## Modelado de datos

### Silver — 6 tablas temáticas (views)

| Tabla | Contenido | Columnas clave calculadas |
|---|---|---|
| `stg_listings__details` | Información del inmueble | `is_entire_home` |
| `stg_listings__host` | Información del host | `host_profile`, `host_seniority_years` |
| `stg_listings__location` | Geografía del listing | `neighbourhood_cleansed` |
| `stg_listings__availability` | Precio y disponibilidad | `price_winsorized` (P95), `estimated_revenue_adjusted`, `is_high_availability` |
| `stg_listings__reviews_scores` | Puntuaciones | `days_since_last_review` |
| `stg_reviews` | Reseñas individuales | `review_month_start` |

### Gold — Esquema estrella (tables)

```
dim_listing ──┐
dim_host ─────┼──► fact_listings (incremental)
dim_neighbourhood ─┤
dim_room_type ─┘

stg_reviews ──► fact_reviews_monthly

fact_listings ──► mart_neighbourhood_pressure
              ──► mart_host_profile
              ──► mart_city_comparison
```

### Decisiones técnicas destacadas

**Winsorización P95 por ciudad:** el campo `estimated_revenue_l365d` de Inside Airbnb
contiene outliers graves causados por precios erróneos. Se aplica winsorización al
percentil 95 **por ciudad** y se recalcula
`estimated_revenue_adjusted = price_winsorized × estimated_occupancy_l365d`.

**Carga incremental:** `fact_listings` usa `materialized='incremental'` con
`unique_key=['listing_id', 'snapshot_date']`. Solo inserta filas nuevas.

**SCD Tipo 2:** `dim_host_snapshot` rastrea cambios en `calculated_host_listings_count`
y `host_profile` entre snapshots. `dbt_valid_to IS NULL` identifica el registro actual.

**Degenerate dimensions:** `city`, `host_profile` e `is_entire_home` desnormalizadas
en `fact_listings` para evitar joins frecuentes en el dashboard.

---

## Clasificación de hosts

| Perfil | Criterio |
|---|---|
| Host individual | < 2 viviendas completas |
| Multipropiedad | 2–4 viviendas completas |
| Operador profesional | ≥ 5 viviendas completas |

---

## Cómo reproducir el proyecto

### 1. Instalar dependencias

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configurar credenciales

Crea un archivo `.env` en la raíz del proyecto:

```
SNOWFLAKE_ACCOUNT=tu_account
SNOWFLAKE_USER=tu_usuario
SNOWFLAKE_PASSWORD=tu_password
```

### 3. Descargar datos y cargar en Snowflake

```bash
python ingest_spain_cities.py
```

El script descarga los CSV.gz de las 9 ciudades, los sube al stage
de Snowflake y ejecuta los COPY INTO automáticamente.

### 4. Configurar Snowflake (primera vez)

```sql
CREATE WAREHOUSE AIRBNB_WH WAREHOUSE_SIZE='X-SMALL'
    AUTO_SUSPEND=60 AUTO_RESUME=TRUE INITIALLY_SUSPENDED=TRUE;

CREATE DATABASE AIRBNB_DEV_BRONZE;   CREATE DATABASE AIRBNB_PROD_BRONZE;
CREATE DATABASE AIRBNB_DEV_SILVER;   CREATE DATABASE AIRBNB_PROD_SILVER;
CREATE DATABASE AIRBNB_DEV_GOLD;     CREATE DATABASE AIRBNB_PROD_GOLD;
```

### 5. Ejecutar el pipeline dbt

```bash
dbt deps
dbt seed
dbt run
dbt snapshot
dbt test
```

---

## Limitaciones conocidas

- Precios en USD — Inside Airbnb no convierte a EUR
- Málaga tiene baja granularidad geográfica: 65,8% de listings bajo el barrio 'Centro'
- `estimated_revenue_adjusted` es una estimación, no el ingreso real del propietario
- Los snapshots de Inside Airbnb son trimestrales, no datos en tiempo real
