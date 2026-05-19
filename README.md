# Presión del alquiler turístico sobre el mercado residencial en Andalucía

**Proyecto Final — Data Engineering Bootcamp**

Análisis de la presión que ejerce Airbnb sobre el mercado de vivienda residencial en **Sevilla y Málaga**, usando datos públicos de Inside Airbnb y un pipeline completo de data engineering.

---

## La pregunta

> *¿Está Airbnb presionando el mercado de vivienda en Sevilla y Málaga? Medido desde tres ángulos: cuánta vivienda está siendo capturada, quién la captura y cuánto dinero genera hacerlo.*

---

## Stack tecnológico

| Herramienta | Uso |
|---|---|
| **Inside Airbnb** | Fuente de datos — scraping trimestral de Airbnb |
| **Snowflake** | Data warehouse — Bronze, Silver y Gold |
| **dbt Cloud** | Transformaciones SQL, tests y documentación |
| **PowerBI Desktop** | Dashboards y visualizaciones |
| **GitHub** | Control de versiones — ramas dev y main |

---

## Arquitectura — Medallion Architecture

```
Inside Airbnb (CSV)
        │
        ▼
┌─────────────┐
│   BRONZE    │  Dato crudo · Todo TEXT · Sin transformaciones
│             │  RAW_LISTINGS (80 col · ~18K filas/trimestre)
│             │  RAW_REVIEWS  (~1.1M filas)
└──────┬──────┘
       │ dbt
       ▼
┌─────────────┐
│   SILVER    │  Dato limpio · Views · 6 modelos temáticos
│             │  Tipos casteados · Columnas calculadas
│             │  Winsorización P95 · host_profile · is_entire_home
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
   PowerBI
```

### Arquitectura de entornos

El mismo código dbt se ejecuta contra distintas databases según el entorno, controlado mediante variables de entorno en dbt Cloud:

| Entorno | Databases Snowflake | Branch GitHub |
|---|---|---|
| DEV | AIRBNB_DEV_BRONZE / SILVER / GOLD | dev |
| PROD | AIRBNB_PROD_BRONZE / SILVER / GOLD | main |

**Flujo:** desarrollar en `dev` → `dbt run` en DEV → validar → PR a `main` → job PROD.

---

## Datos

- **Fuente:** [Inside Airbnb](https://insideairbnb.com/get-the-data/) — datos públicos, sin registro
- **Ciudades:** Sevilla y Málaga
- **Snapshots:** Junio 2025 + Septiembre 2025
- **Volumen:** ~18.000 listings por trimestre · ~1.1M reviews

> Los archivos CSV.gz no están en este repositorio por su tamaño. Descárgalos desde Inside Airbnb buscando los snapshots de Sevilla y Málaga.

---

## Estructura del proyecto dbt

```
airbnb_andalucia/
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
├── macros/
│   └── generate_schema_name.sql
└── dbt_project.yml
```

---

## Modelado de datos

### Silver — 6 tablas temáticas (views)

| Tabla | Contenido | Columnas clave calculadas |
|---|---|---|
| `stg_listings__details` | Información del inmueble | `is_entire_home` |
| `stg_listings__host` | Información del host | `host_profile`, `host_seniority_years` |
| `stg_listings__location` | Geografía del listing | `neighbourhood_cleansed` (TRIM) |
| `stg_listings__availability` | Precio y disponibilidad | `price_winsorized` (P95), `estimated_revenue_adjusted`, `is_high_availability` |
| `stg_listings__reviews_scores` | Puntuaciones | `days_since_last_review` |
| `stg_reviews` | Reseñas individuales | `review_month_start` |

### Gold — Esquema estrella (tables)

```
dim_listing ──┐
dim_host ─────┤
              ├──► fact_listings (incremental)
dim_neighbourhood ─┤
dim_room_type ─┘

stg_reviews ──► fact_reviews_monthly

fact_listings ──► mart_neighbourhood_pressure
              ──► mart_host_profile
              ──► mart_city_comparison
```

### Decisiones técnicas destacadas

**Winsorización P95:** el precio viene con outliers graves (listing a 21.911$/noche que realmente costaba 170€). Se aplica winsorización al percentil 95 por ciudad (368$ Sevilla · 395$ Málaga) y se recalcula `estimated_revenue_adjusted = price_winsorized × estimated_occupancy_l365d`.

**Carga incremental:** `fact_listings` usa `materialized='incremental'` con `unique_key=['listing_id', 'snapshot_date']`. Solo inserta filas con `snapshot_date` posterior al máximo ya cargado.

**SCD Tipo 2:** `dim_host_snapshot` rastrea cambios en `calculated_host_listings_count` y `host_profile` entre snapshots. Columnas: `dbt_valid_from`, `dbt_valid_to` (NULL = registro actual), `dbt_scd_id`.

**Degenerate dimensions:** `city`, `host_profile` e `is_entire_home` están desnormalizadas en `fact_listings` para evitar joins frecuentes en PowerBI.

**QUALIFY deduplicación:** los JOINs en `fact_listings` generaban producto cartesiano con múltiples snapshots. Solucionado con `QUALIFY ROW_NUMBER() OVER (PARTITION BY listing_id, snapshot_date) = 1`.

---

## Clasificación de hosts

| Perfil | Criterio | Sevilla | Málaga |
|---|---|---|---|
| Host individual | < 2 viviendas completas | 74,8% | 72,0% |
| Multipropiedad | 2-4 viviendas completas | 16,9% | 20,2% |
| Operador profesional | ≥ 5 viviendas completas | 8,3% | 7,8% |

---

## Hallazgos principales

| Métrica | Sevilla | Málaga |
|---|---|---|
| % viviendas completas | 85% | 88% |
| Barrio más presionado (>20 listings) | Huerta de Santa Teresa 96,97% | — |
| Top 10% hosts controla | 52,7% listings | 54,5% listings |
| Ingresos medios por listing/año | 15.273 $ | 10.405 $ |
| Ingresos medios por operador profesional | 206.000 $ | 128.000 $ |
| Mayor crecimiento histórico | 2021→2022 +124% | 2015→2016 +132% |

> Los precios están en USD — Inside Airbnb usa dólares aunque los alojamientos sean en España.

---

## Dashboard PowerBI

3 páginas siguiendo el hilo narrativo:

1. **Vivienda Capturada** — % viviendas completas por barrio, evolución histórica de reviews
2. **Quién Captura** — clasificación de hosts, concentración del mercado
3. **Rentabilidad** — ingresos por barrio y por operador, comparativa Sevilla vs Málaga

Conexión a `AIRBNB_PROD_GOLD` en Snowflake · Modo Importar · Tabla `Ciudades` como dimensión de filtrado centralizado.

---

## Limitaciones documentadas

- Precios en USD — Inside Airbnb no convierte a EUR
- Málaga tiene baja granularidad geográfica: el 65,8% de listings está bajo el barrio 'Centro'
- El barrio 'an Roque' en Sevilla es un error del dataset original (debería ser 'San Roque')
- `estimated_revenue_adjusted` es una estimación calculada, no el ingreso real del propietario

---

## Cómo reproducir el proyecto

### 1. Configurar Snowflake

```sql
-- Crear warehouse
CREATE WAREHOUSE AIRBNB_WH WAREHOUSE_SIZE='X-SMALL'
    AUTO_SUSPEND=60 AUTO_RESUME=TRUE INITIALLY_SUSPENDED=TRUE;

-- Crear databases (DEV y PROD)
CREATE DATABASE AIRBNB_DEV_BRONZE;
CREATE DATABASE AIRBNB_DEV_SILVER;
CREATE DATABASE AIRBNB_DEV_GOLD;
CREATE DATABASE AIRBNB_PROD_BRONZE;
CREATE DATABASE AIRBNB_PROD_SILVER;
CREATE DATABASE AIRBNB_PROD_GOLD;
```

### 2. Cargar datos en Bronze

Descargar `listings.csv.gz` y `reviews.csv.gz` para Sevilla y Málaga desde Inside Airbnb y cargar con `COPY INTO` usando un stage interno de Snowflake.

### 3. Configurar dbt Cloud

- Conectar a la cuenta de Snowflake
- Conectar al repositorio GitHub
- Configurar variables de entorno DEV y PROD
- Ejecutar `dbt deps` para instalar `dbt_utils`

### 4. Ejecutar el pipeline

```bash
dbt seed          # carga dim_room_type
dbt run           # ejecuta todos los modelos
dbt snapshot      # actualiza dim_host_snapshot
dbt test          # verifica calidad de datos
```

---

## Documentación

Los documentos explicativos del proyecto (Fases 1-6) están disponibles aparte:

- `proyecto_airbnb_fases123_v3.docx` — Exploración, Snowflake y Modelado
- `proyecto_airbnb_doc2_fases45.docx` — dbt y Análisis SQL
- `proyecto_airbnb_fase6.docx` — PowerBI

El linaje completo de datos está disponible en `dbt docs generate`.
