-- =============================================================
-- stg_listings__availability
-- Precio, disponibilidad y ocupación de cada listing.
-- Es la tabla más importante de Silver: contiene los datos
-- económicos que alimentan todos los KPIs del proyecto.
-- Transformación clave: winsorización del precio al P95 por
-- ciudad para neutralizar outliers sin eliminar filas.
-- =============================================================

-- Carga el dato crudo desde Bronze (todo en tipo TEXT)
WITH source AS (
    SELECT * FROM {{ source('bronze', 'raw_listings') }}
),

-- Limpia el campo price: elimina el símbolo $ y las comas de
-- miles, y convierte a FLOAT. TRY_CAST evita que un valor
-- inesperado rompa la pipeline — devuelve NULL en su lugar.
price_cleaned AS (
    SELECT
        *,
        TRY_CAST(
            REPLACE(REPLACE(price, '$', ''), ',', '') AS FLOAT
        ) AS price_numeric
    FROM source
),

-- Calcula el percentil 95 de precio por ciudad.
-- Se usa para la winsorización: los listings por encima de este
-- valor tienen precios erróneos o atípicos extremos (ej: 92.150€
-- detectado en Málaga). Calcular por ciudad evita que los precios
-- de una ciudad distorsionen el P95 de otra: el nivel de precios
-- de Madrid o Mallorca no es comparable al de Menorca o Euskadi.
percentiles AS (
    SELECT
        city,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY price_numeric) AS p95_price
    FROM price_cleaned
    WHERE price_numeric IS NOT NULL
    GROUP BY city
),

final AS (
    SELECT
        TRY_CAST(pc.id AS INTEGER)                              AS listing_id,

        -- Precio original conservado para trazabilidad y auditoría
        pc.price                                                AS price_raw,
        pc.price_numeric,

        -- Winsorización: si el precio supera el P95, se capea al P95.
        -- El listing NO se elimina — solo se neutraliza el outlier en
        -- el campo de precio. Esto permite análisis de concentración
        -- geográfica con todos los listings.
        LEAST(pc.price_numeric, p.p95_price)                   AS price_winsorized,

        -- Precio por persona: normaliza listings de distinta capacidad.
        -- Un piso de 8 personas a 400€ es más barato que un estudio a
        -- 120€. NULLIF evita división por cero en listings sin capacidad.
        LEAST(pc.price_numeric, p.p95_price)
            / NULLIF(TRY_CAST(pc.accommodates AS INTEGER), 0)  AS price_per_person,

        TRY_CAST(pc.minimum_nights AS INTEGER)                  AS minimum_nights,
        TRY_CAST(pc.maximum_nights AS INTEGER)                  AS maximum_nights,

        -- Bronze almacena booleanos como 't'/'f' en texto
        CASE
            WHEN pc.has_availability = 't' THEN TRUE
            ELSE FALSE
        END                                                     AS has_availability,

        -- Disponibilidad en ventanas de 30, 60, 90 y 365 días
        TRY_CAST(pc.availability_30 AS INTEGER)                 AS availability_30,
        TRY_CAST(pc.availability_60 AS INTEGER)                 AS availability_60,
        TRY_CAST(pc.availability_90 AS INTEGER)                 AS availability_90,
        TRY_CAST(pc.availability_365 AS INTEGER)                AS availability_365,

        -- Flag: listing disponible más de 180 días al año.
        -- Un particular que alquila ocasionalmente no supera 180 días.
        -- Por encima de ese umbral se considera operación profesional
        -- (caso de uso 1.2 — proxy de profesionalización).
        CASE
            WHEN TRY_CAST(pc.availability_365 AS INTEGER) > 180 THEN TRUE
            ELSE FALSE
        END                                                     AS is_high_availability,

        -- Categorización legible de la disponibilidad anual.
        -- Convierte el número crudo en una etiqueta interpretable
        -- para Streamlit y para el análisis del Bloque 1.
        CASE
            WHEN TRY_CAST(pc.availability_365 AS INTEGER) < 60
                THEN 'Casi sin disponibilidad'
            WHEN TRY_CAST(pc.availability_365 AS INTEGER) < 180
                THEN 'Uso parcial'
            ELSE 'Alta disponibilidad'
        END                                                     AS availability_profile,

        -- Ocupación e ingresos estimados calculados por Inside Airbnb.
        -- Son columnas de alto valor: evitan tener que estimar ocupación
        -- mediante proxies como el número de reviews.
        TRY_CAST(pc.estimated_occupancy_l365d AS FLOAT)         AS estimated_occupancy_l365d,

        -- estimated_revenue también viene con formato "$X,XXX.XX"
        TRY_CAST(
            REPLACE(REPLACE(pc.estimated_revenue_l365d, '$', ''), ',', '')
            AS FLOAT)                                           AS estimated_revenue_l365d,

        -- Revenue ajustado: precio winsorizado × ocupación estimada
        -- Más fiable que estimated_revenue_l365d de Inside Airbnb
        -- que usa el precio original sin limpiar
        LEAST(pc.price_numeric, p.p95_price)
        * NULLIF(TRY_CAST(pc.estimated_occupancy_l365d AS FLOAT), 0)
                                        AS estimated_revenue_adjusted,

        -- Fecha del scraping: usada como snapshot_date en fact_listings
        -- para la materialización incremental en Gold
        TRY_TO_DATE(pc.last_scraped, 'YYYY-MM-DD')             AS last_scraped,
        pc.city

    FROM price_cleaned pc
    -- LEFT JOIN para conservar todos los listings aunque no tengan precio
    LEFT JOIN percentiles p ON pc.city = p.city
)

SELECT * FROM final