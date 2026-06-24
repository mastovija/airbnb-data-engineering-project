-- =============================================================
-- mart_host_profile
-- Una fila por host con su clasificación y métricas agregadas.
-- Responde a los casos de uso 2.1 y 2.2.
--
-- La fuente principal es dim_host (atributos del host) enriquecida
-- con métricas de fact_listings (precio, ocupación, ingresos).
-- El join por host_sk garantiza que se usan los datos actuales
-- del host (sin historial SCD2).
--
-- Permite en PowerBI mostrar el ranking de hosts por ingresos,
-- la distribución por tipo de host, y la concentración del mercado
-- (cuántos listings controlan los operadores profesionales).
-- =============================================================

WITH fact AS (
    SELECT * FROM {{ ref('fact_listings') }}
    QUALIFY snapshot_date = MAX(snapshot_date) OVER (PARTITION BY city)
),

host AS (
    SELECT * FROM {{ ref('dim_host') }}
)

SELECT
    h.host_id,
    h.host_name,
    h.host_profile,         -- 'Host individual' / 'Multipropiedad' / 'Operador profesional'
    h.host_seniority_years, -- años desde que se registró en Airbnb
    h.city,

    -- Número de listings totales y de viviendas completas del host.
    -- Vienen de dim_host (calculados por Inside Airbnb) porque son
    -- más fiables que agregar fact_listings, donde un host podría
    -- tener listings sin datos de precio o inactivosaños.
    h.calculated_host_listings_count           AS total_listings,
    h.calc_listings_entire_homes               AS entire_home_listings,

    -- % del portfolio del host que son viviendas completas.
    -- Un operador profesional con 10 listings todos entire_home
    -- tiene mayor impacto en el mercado residencial que uno con
    -- 10 listings mixtos.
    ROUND(
        h.calc_listings_entire_homes
        / NULLIF(h.calculated_host_listings_count, 0) * 100
    , 2)                                       AS pct_entire_home,

    -- Métricas económicas agregadas desde fact_listings
    ROUND(AVG(f.price_per_person), 2)          AS avg_price_per_person,
    ROUND(AVG(f.estimated_occupancy_l365d), 1) AS avg_occupancy,

    -- Ingresos anuales totales estimados del host (suma de todos sus listings)
    ROUND(SUM(f.estimated_revenue_adjusted), 2) AS estimated_annual_revenue,

    h.host_is_superhost                        AS is_superhost

FROM host h
LEFT JOIN fact f
    ON h.host_sk = f.host_sk
GROUP BY
    h.host_id,
    h.host_name,
    h.host_profile,
    h.host_seniority_years,
    h.city,
    h.calculated_host_listings_count,
    h.calc_listings_entire_homes,
    h.host_is_superhost