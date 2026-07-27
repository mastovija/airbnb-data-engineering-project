-- =============================================================
-- dim_listing
-- Una fila por listing con información descriptiva del inmueble.
-- Combina datos de dos tablas Silver (details + location) y
-- añade las FKs hacia dim_neighbourhood y dim_room_type para
-- construir el esquema estrella.
-- latitude y longitude son necesarias para los mapas de Streamlit.
-- =============================================================

WITH details AS (
    SELECT * FROM {{ ref('stg_listings__details') }}
),

location AS (
    SELECT * FROM {{ ref('stg_listings__location') }}
),

-- dim_neighbourhood aporta el surrogate key neighbourhood_id
-- que se usa como FK en fact_listings
neighbourhood AS (
    SELECT * FROM {{ ref('dim_neighbourhood') }}
),

-- dim_room_type aporta room_type_id — tabla seed de 4 filas
room_type AS (
    SELECT * FROM {{ ref('dim_room_type') }}
)

SELECT
    d.listing_id,

    -- FKs hacia las dimensiones de lookup
    r.room_type_id,
    n.neighbourhood_id,

    -- Atributos descriptivos del inmueble
    d.name,
    d.property_type,
    d.room_type,
    d.is_entire_home,   -- KPI central: vivienda completa capturada por Airbnb
    d.accommodates,     -- Necesario para interpretar price_per_person en fact

    -- Geografía: neighbourhood_cleansed como texto para filtros en Streamlit,
    -- neighbourhood_id como FK para joins eficientes en el esquema estrella
    l.neighbourhood_cleansed,
    l.latitude,
    l.longitude,

    d.city

FROM details d
-- LEFT JOIN para conservar todos los listings aunque falte
-- información geográfica o de lookup
LEFT JOIN location l
    ON d.listing_id = l.listing_id
LEFT JOIN neighbourhood n
    ON l.neighbourhood_cleansed = n.neighbourhood_cleansed
    AND l.city = n.city     -- city es parte de la NK de dim_neighbourhood
LEFT JOIN room_type r
    ON d.room_type = r.room_type
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY d.listing_id
    ORDER BY d.listing_id
) = 1