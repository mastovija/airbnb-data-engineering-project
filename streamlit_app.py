"""
Presión del alquiler turístico sobre el mercado residencial en España
Dashboard de monitorización — Inside Airbnb · 9 ciudades españolas
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE PÁGINA
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Airbnb y Vivienda en España",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────

CITY_LABELS = {
    "barcelona": "Barcelona",
    "euskadi":   "Euskadi",
    "girona":    "Girona",
    "madrid":    "Madrid",
    "malaga":    "Málaga",
    "mallorca":  "Mallorca",
    "menorca":   "Menorca",
    "sevilla":   "Sevilla",
    "valencia":  "Valencia",
}

COLOR_PRIMARY   = "#E8433A"
COLOR_WARNING   = "#F4A832"
COLOR_OK        = "#3AE87A"
COLOR_NEUTRAL   = "#4A90D9"
COLOR_SEQUENCE  = [
    "#E8433A", "#F4A832", "#4A90D9",
    "#3AE87A", "#A855F7", "#F97316",
    "#06B6D4", "#84CC16", "#EC4899",
]

# ─────────────────────────────────────────────────────────────────────────────
# CARGA DE DATOS
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data
def load_data():
    neighbourhood = pd.read_parquet("data/gold/mart_neighbourhood_pressure.parquet")
    city          = pd.read_parquet("data/gold/mart_city_comparison.parquet")
    host          = pd.read_parquet("data/gold/mart_host_profile.parquet")
    reviews       = pd.read_parquet("data/gold/fact_reviews_monthly.parquet")
    listings      = pd.read_parquet("data/gold/fact_listings_dashboard.parquet")
    return neighbourhood, city, host, reviews, listings

neighbourhood_df, city_df, host_df, reviews_df, listings_df = load_data()

# Añadir etiquetas legibles de ciudad
for df in [neighbourhood_df, city_df, host_df, reviews_df, listings_df]:
    if "city" in df.columns:
        df["ciudad"] = df["city"].map(CITY_LABELS).fillna(df["city"].str.title())

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — FILTROS
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/home.png", width=60)
    st.title("Filtros")
    st.markdown("---")

    ciudades_disponibles = sorted(CITY_LABELS.values())
    ciudad_sel = st.selectbox(
        "Ciudad",
        options=["Todas las ciudades"] + ciudades_disponibles,
        index=0,
    )

    st.markdown("---")
    st.caption(
        "Datos: [Inside Airbnb](https://insideairbnb.com) · "
        "9 ciudades españolas · Snapshots 2025-2026"
    )
    st.caption("Pipeline: Snowflake · dbt · Python")

# Filtrar datos según selección
def filtrar(df, columna_ciudad="ciudad"):
    if ciudad_sel == "Todas las ciudades":
        return df
    return df[df[columna_ciudad] == ciudad_sel]

nb   = filtrar(neighbourhood_df)
ct   = filtrar(city_df)
ht   = filtrar(host_df)
rv   = filtrar(reviews_df)
ls   = filtrar(listings_df)

# ─────────────────────────────────────────────────────────────────────────────
# CABECERA
# ─────────────────────────────────────────────────────────────────────────────

st.markdown(
    "<h1 style='font-size:2rem; margin-bottom:0'>🏠 Airbnb y la vivienda en España</h1>",
    unsafe_allow_html=True,
)
subtitulo = ciudad_sel if ciudad_sel != "Todas las ciudades" else "9 ciudades españolas"
st.markdown(
    f"<p style='color:#888; font-size:1rem; margin-top:4px'>"
    f"Monitorización de la presión turística sobre el mercado residencial · {subtitulo}"
    f"</p>",
    unsafe_allow_html=True,
)
st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# BLOQUE 1 — ¿CUÁNTA VIVIENDA ESTÁ SIENDO CAPTURADA?
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("## 🏚️ Bloque 1 — ¿Cuánta vivienda está siendo capturada?")

# KPIs
total_listings     = int(ct["total_listings"].sum()) if not ct.empty else 0
pct_entire         = ct["pct_entire_home"].mean() if not ct.empty else 0
pct_high_avail     = ct["avg_occupancy_days"].mean() if not ct.empty else 0
total_barrios      = nb["neighbourhood_cleansed"].nunique() if not nb.empty else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total listings", f"{total_listings:,}")
c2.metric("% Viviendas completas", f"{pct_entire:.1f}%",
          help="Inmuebles completos retirados del mercado residencial")
c3.metric("Barrios analizados", f"{total_barrios:,}")
c4.metric("Ocupación media (días/año)", f"{pct_high_avail:.0f}",
          help="Días ocupados estimados por listing al año")

st.markdown("<br>", unsafe_allow_html=True)

col_left, col_right = st.columns([1.2, 1])

# Gráfico: Presión por barrio — volumen vs. % vivienda completa
with col_left:
    st.markdown("#### Presión por barrio: volumen vs. % vivienda completa")
    if not nb.empty:
        min_listings = st.slider(
            "Mínimo de listings por barrio", min_value=10, max_value=150,
            value=50, step=5,
            help=(
                "Los municipios turísticos pequeños alcanzan fácilmente el 100% "
                "de vivienda completa porque apenas tienen mercado de alquiler "
                "residencial de partida. Sube el mínimo para centrar el análisis "
                "en barrios con volumen real de listings."
            ),
        )
        nb_ctx = nb[nb["total_listings"] >= min_listings].copy()
        if not nb_ctx.empty:
            fig = px.scatter(
                nb_ctx,
                x="total_listings",
                y="pct_entire_home",
                size="total_entire_home",
                color="ciudad",
                color_discrete_sequence=COLOR_SEQUENCE,
                hover_name="neighbourhood_cleansed",
                hover_data={
                    "total_listings": True,
                    "pct_entire_home": ":.1f",
                    "pressure_score": ":.1f",
                    "ciudad": False,
                },
                labels={
                    "total_listings": "Nº de listings en el barrio",
                    "pct_entire_home": "% Viviendas completas",
                    "ciudad": "Ciudad",
                },
                size_max=32,
                log_x=True,
            )
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                showlegend=ciudad_sel == "Todas las ciudades",
                margin=dict(l=0, r=20, t=20, b=20),
                height=380,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            fig.add_hline(
                y=pct_entire, line_dash="dot",
                line_color="#888", annotation_text=f"Media: {pct_entire:.1f}%",
                annotation_font_color="#888",
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                f"Cada punto es un barrio con ≥{min_listings} listings. El tamaño "
                "del punto es el número de viviendas completas capturadas. Los "
                "puntos pequeños cerca del 100% suelen ser municipios turísticos "
                "con escaso mercado residencial de partida — los puntos grandes "
                "son donde la presión afecta a más vecinos reales."
            )
        else:
            st.info(f"Ningún barrio supera el mínimo de {min_listings} listings con la selección actual.")
    else:
        st.info("Sin datos para la selección actual.")

# Gráfico: Evolución temporal de reviews
with col_right:
    st.markdown("#### Evolución de la actividad turística")
    if not rv.empty:
        rv_año = (
            rv.groupby(["review_year", "ciudad"])["total_reviews"]
            .sum()
            .reset_index()
        )
        rv_año = rv_año[rv_año["review_year"] >= 2015]

        if ciudad_sel == "Todas las ciudades":
            vista_evol = st.radio(
                "Vista",
                ["Tendencia nacional", "Top 5 ciudades", "Todas apiladas"],
                horizontal=True, index=0, label_visibility="collapsed",
            )
        else:
            vista_evol = "Ciudad seleccionada"

        if vista_evol == "Tendencia nacional":
            nacional = rv_año.groupby("review_year")["total_reviews"].sum().reset_index()
            fig2 = px.area(
                nacional, x="review_year", y="total_reviews",
                labels={"review_year": "Año", "total_reviews": "Reviews (9 ciudades)"},
                color_discrete_sequence=[COLOR_PRIMARY],
            )
            fig2.update_traces(line=dict(width=2), fillcolor="rgba(232,67,58,0.15)")
            fig2.add_vrect(
                x0=2019.5, x1=2020.5, fillcolor="#888", opacity=0.12, line_width=0,
                annotation_text="COVID-19", annotation_position="top left",
                annotation_font_color="#888",
            )
        elif vista_evol == "Top 5 ciudades":
            top5_ciudades = (
                rv_año.groupby("ciudad")["total_reviews"].sum()
                .nlargest(5).index.tolist()
            )
            fig2 = px.line(
                rv_año[rv_año["ciudad"].isin(top5_ciudades)],
                x="review_year", y="total_reviews", color="ciudad",
                color_discrete_sequence=COLOR_SEQUENCE,
                labels={"review_year": "Año", "total_reviews": "Reviews", "ciudad": "Ciudad"},
                markers=True,
            )
        elif vista_evol == "Todas apiladas":
            orden_ciudades = (
                rv_año.groupby("ciudad")["total_reviews"].sum()
                .sort_values(ascending=False).index.tolist()
            )
            fig2 = px.bar(
                rv_año, x="review_year", y="total_reviews", color="ciudad",
                color_discrete_sequence=COLOR_SEQUENCE,
                category_orders={"ciudad": orden_ciudades},
                labels={"review_year": "Año", "total_reviews": "Reviews", "ciudad": "Ciudad"},
            )
            fig2.update_layout(barmode="stack")
        else:  # ciudad seleccionada individualmente en el sidebar
            fig2 = px.area(
                rv_año, x="review_year", y="total_reviews",
                labels={"review_year": "Año", "total_reviews": "Reviews"},
                color_discrete_sequence=[COLOR_PRIMARY],
            )
            fig2.update_traces(line=dict(width=2), fillcolor="rgba(232,67,58,0.15)")

        fig2.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=20, t=20, b=20),
            height=380,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            showlegend=vista_evol in ("Top 5 ciudades", "Todas apiladas"),
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Sin datos para la selección actual.")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# BLOQUE 2 — ¿QUIÉN CAPTURA LA VIVIENDA?
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("## 👥 Bloque 2 — ¿Quién captura la vivienda?")

# KPIs
total_hosts      = ht["host_id"].nunique() if not ht.empty else 0
pct_pro          = (
    ht[ht["host_profile"] == "Operador profesional"]["host_id"].nunique()
    / max(total_hosts, 1) * 100
)
pct_multi        = (
    ht[ht["host_profile"] != "Host individual"]["host_id"].nunique()
    / max(total_hosts, 1) * 100
)
listings_por_pro = (
    ht[ht["host_profile"] == "Operador profesional"]["total_listings"].sum()
    / max(ht["total_listings"].sum(), 1) * 100
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total hosts", f"{total_hosts:,}")
c2.metric("Operadores profesionales", f"{pct_pro:.1f}%",
          help="Hosts con 5+ viviendas completas")
c3.metric("Inversores (multi + pro)", f"{pct_multi:.1f}%",
          help="Hosts con más de 1 vivienda completa")
c4.metric("Listings en manos de profesionales", f"{listings_por_pro:.1f}%",
          help="% del mercado controlado por operadores profesionales")

st.markdown("<br>", unsafe_allow_html=True)

col_left, col_right = st.columns([1, 1.4])

# Gráfico: Donut de perfiles de host
with col_left:
    st.markdown("#### ¿Quién gestiona los alojamientos?")
    if not ht.empty:
        perfil_counts = (
            ht.groupby("host_profile")["host_id"]
            .nunique()
            .reset_index()
            .rename(columns={"host_id": "num_hosts"})
        )
        colores_perfil = {
            "Host individual":      COLOR_OK,
            "Multipropiedad":       COLOR_WARNING,
            "Operador profesional": COLOR_PRIMARY,
        }
        fig3 = px.pie(
            perfil_counts,
            values="num_hosts",
            names="host_profile",
            hole=0.55,
            color="host_profile",
            color_discrete_map=colores_perfil,
        )
        fig3.update_traces(textposition="outside", textinfo="percent+label")
        fig3.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
            margin=dict(l=20, r=20, t=40, b=20),
            height=360,
        )
        st.plotly_chart(fig3, use_container_width=True)
        st.caption(
            "🟢 Host individual: < 2 viviendas completas  "
            "🟡 Multipropiedad: 2–4  "
            "🔴 Operador profesional: ≥ 5"
        )
    else:
        st.info("Sin datos para la selección actual.")

# Gráfico: Listings controlados por perfil y ciudad
with col_right:
    st.markdown("#### ¿Quién controla las viviendas completas?")
    if not ht.empty:
        listings_perfil = (
            ht.groupby(["ciudad", "host_profile"])["total_listings"]
            .sum()
            .reset_index()
        )
        orden_perfil = ["Host individual", "Multipropiedad", "Operador profesional"]
        colores_perfil = {
            "Host individual":      COLOR_OK,
            "Multipropiedad":       COLOR_WARNING,
            "Operador profesional": COLOR_PRIMARY,
        }
        fig4 = px.bar(
            listings_perfil,
            x="total_listings",
            y="ciudad",
            color="host_profile",
            orientation="h",
            barmode="stack",
            color_discrete_map=colores_perfil,
            category_orders={"host_profile": orden_perfil},
            labels={
                "total_listings": "Número de listings",
                "ciudad": "",
                "host_profile": "Perfil",
            },
        )
        fig4.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=20, t=20, b=20),
            height=360,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig4, use_container_width=True)
    else:
        st.info("Sin datos para la selección actual.")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# BLOQUE 3 — ¿CUÁNTO DINERO GENERA?
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("## 💰 Bloque 3 — ¿Cuánto dinero genera?")

# KPIs
precio_mediano  = ct["median_price_winsorized"].mean() if not ct.empty else 0
ingreso_medio   = ct["avg_estimated_revenue"].mean() if not ct.empty else 0
ingreso_pro     = (
    ht[ht["host_profile"] == "Operador profesional"]["estimated_annual_revenue"].mean()
    if not ht.empty else 0
)
pct_multihost   = ct["pct_multihost_listings"].mean() if not ct.empty else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Precio mediano/noche", f"${precio_mediano:,.0f}",
          help="Precio con winsorización P95 para eliminar outliers")
c2.metric("Ingresos medios/listing/año", f"${ingreso_medio:,.0f}")
c3.metric("Ingresos medios operador pro", f"${ingreso_pro:,.0f}/año",
          help="Media de ingresos anuales de operadores profesionales")
c4.metric("% listings en inversores", f"{pct_multihost:.1f}%")

st.markdown("<br>", unsafe_allow_html=True)

col_left, col_right = st.columns([1.2, 1])

# Gráfico: Top barrios por ingresos
with col_left:
    st.markdown("#### Barrios más rentables para Airbnb")
    if not nb.empty:
        top_rev = (
            nb[nb["total_listings"] >= 20]
            .nlargest(15, "avg_estimated_revenue")
            [["neighbourhood_cleansed", "ciudad", "avg_estimated_revenue",
              "median_price_winsorized", "total_listings"]]
        )
        fig5 = px.bar(
            top_rev,
            x="avg_estimated_revenue",
            y="neighbourhood_cleansed",
            color="ciudad" if ciudad_sel == "Todas las ciudades" else "avg_estimated_revenue",
            color_continuous_scale="Oranges" if ciudad_sel != "Todas las ciudades" else None,
            color_discrete_sequence=COLOR_SEQUENCE,
            orientation="h",
            labels={
                "avg_estimated_revenue": "Ingresos medios anuales ($)",
                "neighbourhood_cleansed": "",
                "ciudad": "Ciudad",
            },
            hover_data=["median_price_winsorized", "total_listings"],
        )
        fig5.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            yaxis={"categoryorder": "total ascending"},
            showlegend=ciudad_sel == "Todas las ciudades",
            coloraxis_showscale=False,
            margin=dict(l=0, r=20, t=20, b=20),
            height=420,
        )
        st.plotly_chart(fig5, use_container_width=True)
    else:
        st.info("Sin datos para la selección actual.")

# Tabla: Comparativa entre ciudades
with col_right:
    st.markdown("#### Comparativa entre ciudades")
    if not ct.empty:
        tabla = ct[[
            "ciudad", "total_listings", "pct_entire_home",
            "median_price_winsorized", "avg_estimated_revenue",
            "pct_professional_operators",
        ]].copy()
        tabla.columns = [
            "Ciudad", "Listings", "% Vivienda completa",
            "Precio mediano/noche ($)", "Ingresos medios/año ($)",
            "% Operadores pro",
        ]
        tabla = tabla.sort_values("Listings", ascending=False)
        tabla["Listings"] = tabla["Listings"].apply(lambda x: f"{x:,}")
        tabla["% Vivienda completa"] = tabla["% Vivienda completa"].apply(lambda x: f"{x:.1f}%")
        tabla["Precio mediano/noche ($)"] = tabla["Precio mediano/noche ($)"].apply(lambda x: f"${x:,.0f}")
        tabla["Ingresos medios/año ($)"] = tabla["Ingresos medios/año ($)"].apply(lambda x: f"${x:,.0f}")
        tabla["% Operadores pro"] = tabla["% Operadores pro"].apply(lambda x: f"{x:.1f}%")
        st.dataframe(tabla, hide_index=True, use_container_width=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### Top operadores profesionales")
        top_pro = (
            ht[ht["host_profile"] == "Operador profesional"]
            .nlargest(10, "estimated_annual_revenue")
            [["host_name", "ciudad", "total_listings",
              "entire_home_listings", "estimated_annual_revenue"]]
            .copy()
        )
        top_pro.columns = ["Host", "Ciudad", "Listings", "Viviendas completas", "Ingresos/año ($)"]
        top_pro["Ingresos/año ($)"] = top_pro["Ingresos/año ($)"].apply(lambda x: f"${x:,.0f}")
        st.dataframe(top_pro, hide_index=True, use_container_width=True)
    else:
        st.info("Sin datos para la selección actual.")

# ─────────────────────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("---")
st.caption(
    "Fuente: [Inside Airbnb](https://insideairbnb.com) · "
    "Datos estimados — los ingresos son aproximaciones basadas en precio × ocupación estimada · "
    "Precios en USD"
)
