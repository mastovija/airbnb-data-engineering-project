-- =============================================================
-- mart_city_comparison
-- Una fila por ciudad. Comparativa directa entre las 9 ciudades.
-- Responde al caso de uso 3.3.
-- Diseñada para las tarjetas KPI del dashboard: cada fila es una
-- ciudad y cada columna es una métrica comparable directamente.
--
-- El join a dim_host permite calcular métricas a nivel de host
-- (total_hosts, pct_professional_operators) que no están
-- disponibles directamente en fact_listings.
--
-- POR QUÉ UNA VENTANA DE 30 DÍAS Y NO snapshot_date = MAX(...):
-- Inside Airbnb no scrapea una ciudad en un único día. El campo
-- last_scraped (= snapshot_date) se reparte a lo largo de varios
-- días dentro del mismo snapshot trimestral: Madrid, por ejemplo,
-- tiene 5 fechas distintas entre 2026-06-20 y 2026-07-02.
-- Filtrar por el MAX exacto se quedaba solo con los listings
-- scrapeados el último día — una muestra sesgada de ~8% (Madrid
-- aparecía con 2.966 listings en lugar de ~25.000).
-- La ventana de 30 días recoge el snapshot trimestral completo
-- y sigue excluyendo los snapshots anteriores, que están a ~90
-- días de distancia. Como cada listing se scrapea una sola vez
-- por snapshot, la ventana no duplica filas.
-- =============================================================

WITH fact AS (
    SELECT * FROM {{ ref('fact_listings') }}
    QUALIFY snapshot_date >= DATEADD('day', -30, MAX(snapshot_date) OVER (PARTITION BY city))
),

hosts AS (
    SELECT * FROM {{ ref('dim_host') }}
)

SELECT
    f.city,

    -- Volumen total y activo
    COUNT(*)                                               AS total_listings,
    COUNT(CASE WHEN f.is_active_listing THEN 1 END)       AS total_active_listings,

    -- Bloque 1: vivienda capturada
    ROUND(
        COUNT(CASE WHEN f.is_entire_home THEN 1 END)
        / NULLIF(COUNT(*), 0) * 100, 2)                   AS pct_entire_home,

    -- Bloque 3: precio
    ROUND(MEDIAN(f.price_winsorized), 2)                  AS median_price_winsorized,
    ROUND(AVG(f.price_per_person), 2)                     AS avg_price_per_person,

    -- Bloque 3: ocupación e ingresos
    ROUND(AVG(f.estimated_occupancy_l365d), 1)            AS avg_occupancy_days,
    ROUND(AVG(f.estimated_revenue_adjusted), 2)           AS avg_estimated_revenue,

    -- Bloque 2: concentración de hosts
    -- COUNT DISTINCT sobre dim_host para métricas a nivel de host,
    -- no de listing (evita contar el mismo host varias veces)
    COUNT(DISTINCT h.host_id)                             AS total_hosts,
    ROUND(
        COUNT(DISTINCT CASE
            WHEN h.host_profile = 'Operador profesional'
            THEN h.host_id END)
        / NULLIF(COUNT(DISTINCT h.host_id), 0) * 100, 2) AS pct_professional_operators,

    -- pct_multihost_listings: % de listings (no hosts) en manos
    -- de multipropietarios — métrica distinta a pct_professional_operators
    ROUND(
        COUNT(CASE WHEN f.host_profile != 'Host individual' THEN 1 END)
        / NULLIF(COUNT(*), 0) * 100, 2)                   AS pct_multihost_listings,

    ROUND(AVG(f.review_scores_rating), 2)                 AS avg_review_score

FROM fact f
LEFT JOIN hosts h
    ON f.host_sk = h.host_sk
GROUP BY f.city