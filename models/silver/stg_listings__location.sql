-- =============================================================
-- stg_listings__location
-- Información geográfica del listing.
-- La columna más importante es neighbourhood_cleansed:
-- es el barrio normalizado por Inside Airbnb, sin nulos
-- en ninguna ciudad. Es la referencia geográfica principal
-- del proyecto. Alimenta dim_neighbourhood en Gold y los
-- mapas de Streamlit.
-- =============================================================

WITH source AS (
    SELECT * FROM {{ source('bronze', 'raw_listings') }}
)

SELECT
    TRY_CAST(id AS INTEGER)          AS listing_id,

    -- TRIM elimina espacios en blanco al inicio/final que podrían
    -- causar duplicados en dim_neighbourhood (ej: 'Triana ' != 'Triana')
    TRIM(neighbourhood_cleansed)     AS neighbourhood_cleansed,

    -- Coordenadas necesarias para los mapas de Streamlit.
    -- Permiten visualizar la densidad de Airbnb a nivel de calle.
    TRY_CAST(latitude AS FLOAT)      AS latitude,
    TRY_CAST(longitude AS FLOAT)     AS longitude,

    city

FROM source