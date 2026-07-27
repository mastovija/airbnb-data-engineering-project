-- =============================================================
-- fact_reviews_monthly
-- Agregación de reviews por mes y ciudad.
-- Una fila por combinación de city + año + mes.
--
-- Propósito: responde al caso de uso 1.3 — evolución temporal
-- de la actividad turística. Tiene un GRANO DISTINTO a
-- fact_listings (que tiene una fila por listing con métricas
-- anuales). Esta fact tiene una fila por mes con el volumen
-- de actividad de ese mes — no hay solapamiento.
--
-- distinct_listings cuenta los listings únicos que recibieron
-- al menos una review ese mes, lo que sirve como proxy del
-- número de alojamientos activos en cada momento histórico.
-- =============================================================

SELECT
    city,
    review_year,
    review_month,

    -- Primer día del mes: eje temporal en Streamlit.
    -- Permite ordenar cronológicamente sin ambigüedad.
    review_month_start,

    COUNT(*)                        AS total_reviews,

    -- Listings únicos con actividad ese mes.
    -- Muestra cómo ha crecido la base activa de Airbnb
    -- en cada ciudad a lo largo del tiempo.
    COUNT(DISTINCT listing_id)      AS distinct_listings

FROM {{ ref('stg_reviews') }}
WHERE review_date IS NOT NULL   -- filtra las pocas reviews con fecha nula en Bronze
GROUP BY
    city,
    review_year,
    review_month,
    review_month_start