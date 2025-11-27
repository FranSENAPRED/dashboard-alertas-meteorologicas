# app.py
# Dashboad de Alertas Meteorológicas DMC en Streamlit
# Requisitos:
#   pip install streamlit geopandas pandas requests pydeck

import io
import requests
import pandas as pd
import geopandas as gpd
import pydeck as pdk
import streamlit as st

# ------------------------------------------------------------------
# CONFIGURACIÓN BÁSICA
# ------------------------------------------------------------------
st.set_page_config(
    page_title="Sistema de Monitoreo Meteorológico - DMC",
    layout="wide",
    page_icon="🌦️",
)

st.title("Sistema de Monitoreo Meteorológico - DMC")
st.caption("Visualización de Avisos, Alertas y Alarmas meteorológicas a partir de datos GeoJSON oficiales.")

DATA_URL = "https://storage.googleapis.com/geodata-dmc-events-bucket/eventos_AAA_fusionados_ordenados.geojson"

# ------------------------------------------------------------------
# FUNCIONES AUXILIARES
# ------------------------------------------------------------------
def find_column(df: pd.DataFrame, candidates: list[str], default: str | None = None) -> str | None:
    """
    Busca la primera columna existente en el DataFrame dentro de la lista 'candidates'.
    Devuelve el nombre de la columna o 'default' si no encuentra ninguna.
    """
    for c in candidates:
        if c in df.columns:
            return c
    return default


@st.cache_data(show_spinner=True)
def load_data(url: str) -> gpd.GeoDataFrame:
    """
    Descarga el GeoJSON y lo carga como GeoDataFrame.
    """
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    buffer = io.BytesIO(resp.content)
    gdf = gpd.read_file(buffer)

    # Normalización ligera de nombres de columnas (opcional)
    gdf.columns = [c.strip() for c in gdf.columns]

    return gdf


# ------------------------------------------------------------------
# CARGA DE DATOS
# ------------------------------------------------------------------
with st.spinner("Cargando datos meteorológicos desde la DMC..."):
    try:
        gdf = load_data(DATA_URL)
    except Exception as e:
        st.error(f"No fue posible cargar el GeoJSON.\n\nDetalle técnico: {e}")
        st.stop()

if gdf.empty:
    st.warning("El archivo GeoJSON se cargó correctamente pero no contiene registros.")
    st.stop()

# ------------------------------------------------------------------
# DETECCIÓN DE CAMPOS (ADÁPTALO SI LO REQUIERES)
# ------------------------------------------------------------------
# NOTA: ajusta las listas de candidatos si tus campos tienen otros nombres.
col_tipo = find_column(gdf, ["tipoEvento", "tipo", "tipoAviso", "tipo_aaa"])
col_region = find_column(gdf, ["region", "Region", "region_nombre", "glosa_region"])
col_codigo = find_column(gdf, ["codigo", "codigoEvento", "idEvento", "codigo_aaa"])
col_fenomeno = find_column(gdf, ["fenomeno", "Fenomeno", "evento", "titulo", "nombreEvento"])
col_fecha_emision = find_column(gdf, ["fechaEmision", "fecha_emision", "fecha", "fecha_publicacion"])
col_estado = find_column(gdf, ["estado", "estadoEvento", "estado_aaa"])

# Conversión de fecha
if col_fecha_emision:
    gdf[col_fecha_emision] = pd.to_datetime(gdf[col_fecha_emision], errors="coerce")

# Orden lógico de tipo de aviso
tipo_order = ["Aviso", "Alerta", "Alarma"]
if col_tipo:
    gdf[col_tipo] = gdf[col_tipo].astype(str).str.title()
    gdf[col_tipo] = pd.Categorical(gdf[col_tipo], categories=tipo_order, ordered=True)

# ------------------------------------------------------------------
# BARRA LATERAL DE FILTROS
# ------------------------------------------------------------------
st.sidebar.header("Filtros")

# Filtro por tipo
if col_tipo:
    tipos_disponibles = [t for t in tipo_order if t in gdf[col_tipo].unique()]
    tipos_seleccionados = st.sidebar.multiselect(
        "Tipo de evento",
        options=tipos_disponibles,
        default=tipos_disponibles,
    )
else:
    tipos_seleccionados = None

# Filtro por región
if col_region:
    regiones = sorted(gdf[col_region].dropna().astype(str).unique())
    region_sel = st.sidebar.selectbox(
        "Región",
        options=["Todas"] + regiones,
        index=0,
    )
else:
    region_sel = "Todas"

# Filtro por rango de fechas
if col_fecha_emision and gdf[col_fecha_emision].notna().any():
    min_date = gdf[col_fecha_emision].min().date()
    max_date = gdf[col_fecha_emision].max().date()
    rango_fechas = st.sidebar.date_input(
        "Rango de fecha de emisión",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
else:
    rango_fechas = None

# ------------------------------------------------------------------
# APLICAR FILTROS
# ------------------------------------------------------------------
gdf_filtrado = gdf.copy()

# Tipo
if col_tipo and tipos_seleccionados:
    gdf_filtrado = gdf_filtrado[gdf_filtrado[col_tipo].isin(tipos_seleccionados)]

# Región
if col_region and region_sel != "Todas":
    gdf_filtrado = gdf_filtrado[gdf_filtrado[col_region].astype(str) == region_sel]

# Rango de fechas
if col_fecha_emision and isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 2:
    desde, hasta = rango_fechas
    mask = (gdf_filtrado[col_fecha_emision].dt.date >= desde) & (
        gdf_filtrado[col_fecha_emision].dt.date <= hasta
    )
    gdf_filtrado = gdf_filtrado[mask]

st.caption(f"Registros visualizados: {len(gdf_filtrado)} (de {len(gdf)})")

# ------------------------------------------------------------------
# TARJETAS KPI (Aviso / Alerta / Alarma)
# ------------------------------------------------------------------
def kpi_card(title: str, value: int, bg_color: str):
    st.markdown(
        f"""
        <div style="
            background-color:{bg_color};
            padding:1.5rem;
            border-radius:0.75rem;
            text-align:center;
            font-family:system-ui, sans-serif;
            box-shadow:0 2px 4px rgba(0,0,0,0.1);
        ">
            <div style="font-size:1.25rem;font-weight:600;margin-bottom:0.25rem;">{title}</div>
            <div style="font-size:3rem;font-weight:800;margin-bottom:0.5rem;">{value}</div>
            <div style="font-size:0.9rem;">a nivel nacional</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


col_k1, col_k2, col_k3 = st.columns(3)

if col_tipo:
    count_aviso = gdf_filtrado[gdf_filtrado[col_tipo] == "Aviso"].shape[0]
    count_alerta = gdf_filtrado[gdf_filtrado[col_tipo] == "Alerta"].shape[0]
    count_alarma = gdf_filtrado[gdf_filtrado[col_tipo] == "Alarma"].shape[0]
else:
    count_aviso = count_alerta = count_alarma = 0

with col_k1:
    kpi_card("Aviso(s)", count_aviso, "#f7e86e")
with col_k2:
    kpi_card("Alerta(s)", count_alerta, "#f6a623")
with col_k3:
    kpi_card("Alarma(s)", count_alarma, "#e74c3c")

st.markdown("---")

# ------------------------------------------------------------------
# DISTRIBUCIÓN POR REGIÓN + TABLA DE EVENTOS
# ------------------------------------------------------------------
left_col, right_col = st.columns([1.2, 1.8])

with left_col:
    st.subheader("Avisos, Alertas y Alarmas por región")

    if col_region and col_tipo and not gdf_filtrado.empty:
        df_region = (
            gdf_filtrado.groupby(col_region)[col_tipo]
            .count()
            .sort_values(ascending=False)
            .rename("Total")
            .reset_index()
        )
        st.bar_chart(
            df_region.set_index(col_region)["Total"],
            use_container_width=True,
        )
    else:
        st.info("No hay información suficiente para agrupar por región.")

    # Tabla resumida de eventos
    st.subheader("Detalle de eventos")

    columnas_tabla = {}
    if col_tipo:
        columnas_tabla["Tipo"] = col_tipo
    if col_region:
        columnas_tabla["Región"] = col_region
    if col_codigo:
        columnas_tabla["Código"] = col_codigo
    if col_fenomeno:
        columnas_tabla["Fenómeno"] = col_fenomeno
    if col_fecha_emision:
        columnas_tabla["Emisión"] = col_fecha_emision
    if col_estado:
        columnas_tabla["Estado"] = col_estado

    if columnas_tabla:
        df_tabla = gdf_filtrado[list(columnas_tabla.values())].rename(columns={v: k for k, v in columnas_tabla.items()})
        st.dataframe(df_tabla, use_container_width=True, height=420)
    else:
        st.info("No se encontraron columnas estándar para mostrar la tabla de eventos.")

with right_col:
    st.subheader("Mapa de eventos activos")

    if not gdf_filtrado.empty and gdf_filtrado.geometry.notna().any():
        # Centro aproximado en Chile
        view_state = pdk.ViewState(latitude=-30.5, longitude=-71.0, zoom=3.4)

        # Color por tipo de evento
        def get_color(tipo: str) -> list[int]:
            if tipo == "Aviso":
                return [255, 230, 128, 160]
            if tipo == "Alerta":
                return [255, 165, 0, 180]
            if tipo == "Alarma":
                return [255, 0, 0, 200]
            return [150, 150, 150, 140]

        # Construir lista de features para el layer
        data_geojson = []
        for _, row in gdf_filtrado.iterrows():
            feature = {
                "type": "Feature",
                "properties": {
                    "tipo": str(row[col_tipo]) if col_tipo else "",
                    "region": str(row[col_region]) if col_region else "",
                    "codigo": str(row[col_codigo]) if col_codigo else "",
                    "fenomeno": str(row[col_fenomeno]) if col_fenomeno else "",
                },
                "geometry": row.geometry.__geo_interface__,
            }
            data_geojson.append(feature)

        layer = pdk.Layer(
            "GeoJsonLayer",
            data={"type": "FeatureCollection", "features": data_geojson},
            opacity=0.6,
            stroked=True,
            filled=True,
            get_fill_color="properties.tipo === 'Aviso' ? [255,230,128,160] : "
                           "properties.tipo === 'Alerta' ? [255,165,0,180] : "
                           "properties.tipo === 'Alarma' ? [255,0,0,200] : [150,150,150,140]",
            get_line_color=[80, 80, 80, 200],
            line_width_min_pixels=1,
            pickable=True,
        )

        tooltip = {
            "html": "<b>{tipo}</b><br/>Región: {region}<br/>Código: {codigo}<br/>Fenómeno: {fenomeno}",
            "style": {"backgroundColor": "rgba(0,0,0,0.8)", "color": "white"},
        }

        deck = pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            tooltip=tooltip,
            map_style="mapbox://styles/mapbox/dark-v10",
        )

        st.pydeck_chart(deck, use_container_width=True)
    else:
        st.info("No hay geometrías disponibles para mostrar en el mapa.")

# ------------------------------------------------------------------
# DATOS BRUTOS (OPCIONAL)
# ------------------------------------------------------------------
with st.expander("Ver datos en bruto (GeoDataFrame)"):
    st.write(gdf.head())
    st.text("Columnas disponibles:")
    st.write(list(gdf.columns))
