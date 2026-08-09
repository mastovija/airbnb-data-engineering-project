-- =============================================================
-- Test singular: coherencia entre fact_listings y los tres marts, por ciudad.
--
-- ES EL TEST QUE HABRÍA DETECTADO EL BUG DE LA FASE 1: cuando los marts
-- filtraban por snapshot_date = MAX(...) en vez de la ventana de 30 días,
-- sus conteos por ciudad caían a ~8% del real (Madrid 2.966 vs 22.708,
-- un -87%). El test recalcula el baseline desde fact_listings con la MISMA
-- ventana, así que es independiente de la lógica interna de los marts:
-- si alguien revierte un mart a MAX(...), la divergencia salta aquí.
--
-- Grano por mart (no todos exponen "listings por ciudad" igual):
--   · mart_city_comparison        → grano listing: COUNT(*) por ciudad.
--   · mart_neighbourhood_pressure → grano listing: SUM(total_listings) por
--     ciudad. El mart excluye barrios NULL / 'no asignado', así que el
--     baseline aplica la misma exclusión para comparar manzanas con manzanas.
--   · mart_host_profile           → grano HOST, no listing. El síntoma del
--     bug aquí no era de conteo (el LEFT JOIN conservaba los hosts) sino de
--     cobertura: revenue NULL para 37.956 de 38.989 hosts. Se comprueba el
--     % de hosts con estimated_annual_revenue no nulo por ciudad.
--
-- Un test singular devuelve las filas que INCUMPLEN: 0 filas = pasa.
-- =============================================================

{% set max_pct_diff = 5 %}              -- tolerancia de conteo (marts de grano listing)
{% set min_revenue_coverage_pct = 40 %} -- cobertura mínima de revenue (mart_host_profile)

with

-- Baseline: listings por ciudad en fact_listings dentro de la ventana de 30
-- días (idéntica a la de los marts), con el mismo dedup defensivo por listing.
fact_window as (
    select city, listing_id
    from {{ ref('fact_listings') }}
    qualify snapshot_date >= dateadd('day', -30, max(snapshot_date) over (partition by city))
        and row_number() over (partition by city, listing_id order by snapshot_date desc) = 1
),

fact_by_city as (
    select city, count(*) as fact_listings
    from fact_window
    group by city
),

-- Mismo baseline pero excluyendo barrios sin asignar, para comparar con
-- mart_neighbourhood_pressure (que aplica esa exclusión).
fact_by_city_nbh as (
    select fw.city, count(*) as fact_listings
    from fact_window fw
    left join {{ ref('dim_listing') }} dl on fw.listing_id = dl.listing_id
    where dl.neighbourhood_cleansed is not null
      and dl.neighbourhood_cleansed != 'no asignado'
    group by fw.city
),

-- ── Fallos de conteo: mart_city_comparison ──────────────────
fail_city_comparison as (
    select
        'mart_city_comparison' as mart,
        c.city,
        'listings: fact=' || f.fact_listings || ' vs mart=' || c.total_listings
            || ' (diff '
            || round(abs(c.total_listings - f.fact_listings) / nullif(f.fact_listings, 0) * 100, 1)
            || '% > {{ max_pct_diff }}%)' as detail
    from {{ ref('mart_city_comparison') }} c
    join fact_by_city f on c.city = f.city
    where abs(c.total_listings - f.fact_listings) / nullif(f.fact_listings, 0) * 100 > {{ max_pct_diff }}
),

-- ── Fallos de conteo: mart_neighbourhood_pressure ───────────
fail_neighbourhood_pressure as (
    select
        'mart_neighbourhood_pressure' as mart,
        n.city,
        'listings: fact=' || f.fact_listings || ' vs mart=' || sum(n.total_listings)
            || ' (diff '
            || round(abs(sum(n.total_listings) - f.fact_listings) / nullif(f.fact_listings, 0) * 100, 1)
            || '% > {{ max_pct_diff }}%)' as detail
    from {{ ref('mart_neighbourhood_pressure') }} n
    join fact_by_city_nbh f on n.city = f.city
    group by n.city, f.fact_listings
    having abs(sum(n.total_listings) - f.fact_listings) / nullif(f.fact_listings, 0) * 100 > {{ max_pct_diff }}
),

-- ── Fallos de cobertura: mart_host_profile ──────────────────
fail_host_profile as (
    select
        'mart_host_profile' as mart,
        city,
        'cobertura revenue: ' || count(estimated_annual_revenue) || '/' || count(*) || ' hosts ('
            || round(count(estimated_annual_revenue) / nullif(count(*), 0) * 100, 1)
            || '% < {{ min_revenue_coverage_pct }}%)' as detail
    from {{ ref('mart_host_profile') }}
    group by city
    having count(estimated_annual_revenue) / nullif(count(*), 0) * 100 < {{ min_revenue_coverage_pct }}
)

select mart, city, detail from fail_city_comparison
union all
select mart, city, detail from fail_neighbourhood_pressure
union all
select mart, city, detail from fail_host_profile
