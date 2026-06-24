-- =============================================================
-- mart_neighbourhood_pressure
-- La tabla más importante del proyecto. Una fila por barrio
-- con todos los KPIs de presión sobre el mercado de vivienda.
-- Es lo que alimenta el mapa de calor principal de PowerBI.
-- Responde a los casos de uso 1.1, 1.2, 2.1, 2.2, 3.1 y 3.2.
--
-- pressure_score: índice sintético que combina los tres
-- indicadores principales en un único número para el ranking
-- de barrios. Ponderación:
--   50% pct_entire_home    → dimensión del problema
--   30% pct_high_availability → profesionalización
--   20% pct_multihost      → concentración del mercado
-- Permite ordenar los barrios de mayor a menor presión
-- en una sola métrica para el dashboard.
-- =============================================================

WITH fact AS (
    SELECT * FROM {{ ref('fact_listings') }}
    QUALIFY snapshot_date = MAX(snapshot_date) OVER (PARTITION BY city)
)

SELECT
    -- neighbourhood_cleansed viene de dim_listing para tener
    -- el nombre limpio del barrio (con TRIM aplicado en Silver)
    dl.neighbourhood_cleansed,
    f.city,

    -- Volumen total y activo
    COUNT(*)                                                AS total_listings,
    COUNT(CASE WHEN f.is_active_listing THEN 1 END)        AS total_active_listings,

    -- BLOQUE 1: ¿Cuánta vivienda está siendo capturada?
    COUNT(CASE WHEN f.is_entire_home THEN 1 END)           AS total_entire_home,
    ROUND(
        COUNT(CASE WHEN f.is_entire_home THEN 1 END)
        / NULLIF(COUNT(*), 0) * 100, 2)                    AS pct_entire_home,  -- CU 1.1

    -- Proxy de profesionalización: listings disponibles >180 días
    -- no son particulares que alquilan ocasionalmente
    COUNT(CASE WHEN f.is_high_availability THEN 1 END)     AS total_high_availability,
    ROUND(
        COUNT(CASE WHEN f.is_high_availability THEN 1 END)
        / NULLIF(COUNT(*), 0) * 100, 2)                    AS pct_high_availability,  -- CU 1.2

    -- BLOQUE 3: ¿Cuánto dinero genera?
    ROUND(MEDIAN(f.price_winsorized), 2)                   AS median_price_winsorized,
    ROUND(AVG(f.price_per_person), 2)                      AS avg_price_per_person,    -- CU 3.2
    ROUND(AVG(f.estimated_occupancy_l365d), 1)             AS avg_occupancy_days,      -- CU 1.1
    ROUND(AVG(f.estimated_revenue_adjusted), 2)            AS avg_estimated_revenue,   -- CU 3.1

    -- BLOQUE 2: ¿Quién captura la vivienda?
    -- Listings de hosts con más de 1 propiedad (Multipropiedad + Operador profesional)
    COUNT(CASE WHEN f.host_profile != 'Host individual'
               THEN 1 END)                                 AS total_multihost_listings,
    ROUND(
        COUNT(CASE WHEN f.host_profile != 'Host individual'
                   THEN 1 END)
        / NULLIF(COUNT(*), 0) * 100, 2)                    AS pct_multihost_listings,  -- CU 2.2

    -- Solo operadores profesionales (5+ viviendas completas)
    ROUND(
        COUNT(CASE WHEN f.host_profile = 'Operador profesional'
                   THEN 1 END)
        / NULLIF(COUNT(*), 0) * 100, 2)                    AS pct_professional_operators,  -- CU 2.1

    ROUND(AVG(f.review_scores_rating), 2)                  AS avg_review_score,

    -- Índice de presión compuesto: combina los tres indicadores
    -- principales en un único número para el ranking de barrios.
    ROUND(
        (COUNT(CASE WHEN f.is_entire_home THEN 1 END)
            / NULLIF(COUNT(*), 0) * 100 * 0.5)    -- 50% peso vivienda capturada
        + (COUNT(CASE WHEN f.is_high_availability THEN 1 END)
            / NULLIF(COUNT(*), 0) * 100 * 0.3)    -- 30% peso profesionalización
        + (COUNT(CASE WHEN f.host_profile != 'Host individual' THEN 1 END)
            / NULLIF(COUNT(*), 0) * 100 * 0.2)    -- 20% peso concentración
    , 2)                                                   AS pressure_score

FROM fact f
LEFT JOIN {{ ref('dim_listing') }} dl
    ON f.listing_id = dl.listing_id
WHERE dl.neighbourhood_cleansed IS NOT NULL
    AND dl.neighbourhood_cleansed != 'no asignado'  -- filtra barrios sin asignar
GROUP BY
    dl.neighbourhood_cleansed,
    f.city