-- =============================================================
-- stg_reviews
-- Una fila por reseña individual.
-- Alimenta fact_reviews_monthly en Gold para el análisis de
-- estacionalidad y crecimiento histórico (caso de uso 1.3).
-- El campo comments (texto de la reseña) se descarta: no aporta
-- valor en los casos de uso cuantitativos y ocupa ~600MB en
-- Snowflake para ~1.1M de filas.
-- =============================================================

WITH source AS (
    SELECT * FROM {{ source('bronze', 'raw_reviews') }}
)

SELECT
    TRY_CAST(id AS INTEGER)                         AS review_id,

    -- FK hacia stg_listings__details (y por ende a fact_listings)
    TRY_CAST(listing_id AS INTEGER)                 AS listing_id,

    TRY_CAST(reviewer_id AS INTEGER)                AS reviewer_id,

    -- Fecha de la review: base de todos los cálculos temporales
    TRY_TO_DATE(date, 'YYYY-MM-DD')                AS review_date,

    -- Columnas de agrupación temporal calculadas en Silver para
    -- simplificar las agregaciones en fact_reviews_monthly (Gold).
    -- Sin estas columnas, Gold tendría que recalcularlas en cada consulta.
    YEAR(TRY_TO_DATE(date, 'YYYY-MM-DD'))           AS review_year,
    MONTH(TRY_TO_DATE(date, 'YYYY-MM-DD'))          AS review_month,

    -- Primer día del mes: usado como eje temporal en Streamlit.
    -- DATE_TRUNC garantiza que todas las reviews de un mes
    -- tienen exactamente el mismo valor para agrupar correctamente.
    DATE_TRUNC('month', TRY_TO_DATE(date, 'YYYY-MM-DD')) AS review_month_start,

    city

FROM source