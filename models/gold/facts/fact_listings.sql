-- =============================================================
-- fact_listings
-- Tabla central del esquema estrella. Una fila por listing
-- con todas las métricas numéricas y las 4 FKs a dimensiones.
--
-- Materialización incremental: en cargas sucesivas solo se
-- insertan las combinaciones (city, snapshot_date) que aún no
-- están en la tabla. Esto permite añadir nuevos snapshots de
-- Inside Airbnb sin recargar el histórico completo.
--
-- POR QUÉ LA COMPROBACIÓN ES POR CIUDAD Y NO UN MAX GLOBAL:
-- Inside Airbnb scrapea cada ciudad en fechas distintas. Un
-- MAX(snapshot_date) global descartaría en silencio una ciudad
-- publicada con fecha anterior al máximo de otra ciudad ya
-- cargada (p.ej. Euskadi scrapeado el 2026-06-28 no superaría
-- el 2026-07-02 de Madrid y se perdería entero). El NOT EXISTS
-- sobre (city, snapshot_date) trae cualquier snapshot que aún no
-- tengamos sin depender de que las fechas vengan ordenadas.
--
-- Columnas desnormalizadas (degenerate dimensions):
-- is_entire_home, host_profile y city se repiten desde las dims
-- para evitar joins frecuentes en PowerBI y en los marts.
-- Es una decisión de rendimiento deliberada y justificada.
--
-- is_active_listing se calcula aquí (no en Silver) porque
-- combina columnas de dos tablas Silver distintas:
-- stg_listings__availability y stg_listings__reviews_scores.
-- Silver no hace joins entre tablas — esa lógica va en Gold.
-- =============================================================

{{
    config(
        materialized='incremental',
        unique_key=['listing_id', 'snapshot_date']
        )
}}

-- Métricas de precio, disponibilidad y ocupación
WITH availability AS (
    SELECT * FROM {{ ref('stg_listings__availability') }}
),

-- Puntuaciones y días desde última review
reviews AS (
    SELECT * FROM {{ ref('stg_listings__reviews_scores') }}
),

-- dim_host ya está deduplicada (una fila por host_id + city)
host AS (
    SELECT * FROM {{ ref('dim_host') }}
),

neighbourhood AS (
    SELECT * FROM {{ ref('dim_neighbourhood') }}
),

room_type AS (
    SELECT * FROM {{ ref('dim_room_type') }}
),

-- Atributos descriptivos del inmueble (is_entire_home, accommodates)
details AS (
    SELECT * FROM {{ ref('stg_listings__details') }}
),

-- Coordenadas y barrio para el join a dim_neighbourhood
location AS (
    SELECT * FROM {{ ref('stg_listings__location') }}
),

-- Puente entre listing y host: stg_listings__host tiene
-- host_id por listing, que necesitamos para obtener el host_sk
host_listing AS (
    SELECT DISTINCT listing_id, host_id, city
    FROM {{ ref('stg_listings__host') }}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY listing_id, city
        ORDER BY listing_id
    ) = 1
),

joined AS (
    SELECT
        a.listing_id,

        -- FKs al esquema estrella
        h.host_sk,
        n.neighbourhood_id,
        rt.room_type_id,

        -- Métricas económicas (precio winsorizaddo al P99 por ciudad)
        a.price_winsorized,
        a.price_per_person,         -- precio / accommodates

        -- Disponibilidad
        a.availability_profile,     -- 'Casi sin disponibilidad' / 'Uso parcial' / 'Alta disponibilidad'
        a.availability_365,
        a.is_high_availability,     -- TRUE si availability_365 > 180 (proxy profesionalización)

        -- KPIs de ocupación e ingresos calculados por Inside Airbnb
        a.estimated_occupancy_l365d,
        a.estimated_revenue_l365d,
        a.estimated_revenue_adjusted,

        -- Actividad de reviews
        r.number_of_reviews_ltm,    -- reviews últimos 12 meses
        r.reviews_per_month,
        r.review_scores_rating,
        r.days_since_last_review,

        -- Listing activo: tiene precio, tiene disponibilidad Y
        -- ha recibido alguna review reciente (último año o últimos 6 meses).
        -- Evita que listings "zombi" (publicados pero inactivos) distorsionen
        -- las métricas de ocupación y presión por barrio.
        CASE
            WHEN a.price_winsorized IS NOT NULL
             AND a.availability_365 > 0
             AND (
                 r.number_of_reviews_ltm > 0
                 OR r.last_review >= DATEADD('month', -6, CURRENT_DATE())
             )
            THEN TRUE
            ELSE FALSE
        END                             AS is_active_listing,

        -- Degenerate dimensions: desnormalizadas para rendimiento en PowerBI
        d.is_entire_home,               -- evita join a dim_listing en cada consulta
        h.host_profile,                 -- evita join a dim_host en cada consulta
        a.city,

        -- Clave de la materialización incremental:
        -- en la siguiente carga solo se insertan las combinaciones
        -- (city, snapshot_date) que aún no están en la tabla
        a.last_scraped                  AS snapshot_date

    FROM availability a
    LEFT JOIN reviews r
        ON a.listing_id = r.listing_id
    LEFT JOIN details d
        ON a.listing_id = d.listing_id
    LEFT JOIN location l
        ON a.listing_id = l.listing_id
    -- Primero obtenemos el host_id del listing desde Silver,
    -- luego lo usamos para obtener el host_sk de dim_host
    LEFT JOIN host_listing hl
        ON a.listing_id = hl.listing_id
    LEFT JOIN host h
        ON hl.host_id = h.host_id
        AND hl.city = h.city
    LEFT JOIN neighbourhood n
        ON l.neighbourhood_cleansed = n.neighbourhood_cleansed
        AND a.city = n.city
    LEFT JOIN room_type rt
        ON d.room_type = rt.room_type
    -- Deduplicar a una fila por listing_id + snapshot_date
    -- Los JOINs con Silver generan duplicados porque Bronze
    -- tiene múltiples snapshots y Silver los lee todos
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY a.listing_id, a.last_scraped
        ORDER BY a.listing_id
    ) = 1
)

SELECT * FROM joined

-- Bloque incremental: en la primera ejecución se carga todo.
-- En ejecuciones posteriores solo se insertan las combinaciones
-- (city, snapshot_date) que aún no existen en la tabla — comprobación
-- por ciudad para no descartar snapshots con fecha anterior al máximo
-- global (ver cabecera del modelo).
{% if is_incremental() %}
WHERE NOT EXISTS (
    SELECT 1
    FROM {{ this }} t
    WHERE t.city = joined.city
      AND t.snapshot_date = joined.snapshot_date
)
{% endif %}