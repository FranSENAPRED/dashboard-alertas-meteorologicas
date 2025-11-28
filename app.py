# app.py
# Dashboard de Alertas Meteorológicas DMC en Streamlit

import io
import re
import unicodedata
from datetime import datetime

import requests
import pandas as pd
import geopandas as gpd
import pydeck as pdk
import streamlit as st
import altair as alt
from streamlit_autorefresh import st_autorefresh

# ------------------------------------------------------------------
# CONFIGURACIÓN BÁSICA
# ------------------------------------------------------------------
st.set_page_config(
    page_title="Sistema de Monitoreo Meteorológico - DMC",
    layout="wide",
    page_icon="🌦️",
)

# Auto-refresh cada 60 segundos (1 minuto)
st_autorefresh(interval=60 * 1000, key="alertas-refresh")

st.title("Sistema de Monitoreo Meteorológico - DMC")
st.caption("Visualización de Avisos, Alertas y Alarmas meteorológicas a partir de datos GeoJSON oficiales.")

DATA_URL = "https://storage.googleapis.com/geodata-dmc-events-bucket/eventos_AAA_fusionados_ordenados.geojson"

# Nombres de columnas en tu GeoJSON
COL_CODIGO = "codigoMeteo"
COL_TIPO = "tipo"
COL_REGION = "reg"
COL_ORDEN = "orden"
COL_FECHA = "emision"        # aquí viene la fecha como texto
COL_ESTADO = "estado"        # opcional
COL_FENOMENO = "fenomeno"    # opcional

# ------------------------------------------------------------------
# FUNCIONES PARA PARSEAR "emision"
# ------------------------------------------------------------------
def _strip_accents(s: str) -> str:
    """Elimina tildes para normalizar los nombres de meses."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )

MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

# Ejemplo de texto:
# "Viernes 28 de noviembre del 2025 a las 13:32 hrs."
EMISION_PATTERN = re.compile(
    r"""^\s*\w+\s+        # día de la semana
        (\d{1,2})\s+de\s+ # día
        ([A-Za-zÁÉÍÓÚáéíóúñÑ]+)\s+del\s+  # mes en español
        (\d{4})\s+a\s+las\s+
        (\d{1,2}):(\d{2})                 # hora:min
    """,
    re.IGNORECASE | re.VERBOSE,
)

def parse_emision_text(value: str):
    """Convierte 'Viernes 28 de noviembre del 2025 a las 13:32 hrs.' en datetime."""
    if pd.isna(value):
        return pd.NaT
    text = str(value)
    text = text.replace("hrs.", "").replace("hrs", "").strip()

    m = EMISION_PATTERN.match(text)
    if not m:
        return pd.NaT

    day = int(m.group(1))
    month_name = _strip_accents(m.group(2).lower())
    year = int(m.group(3))
    hour = int(m.group(4))
    minute = int(m.group(5))

    month = MONTHS_ES.get(month_name)
    if month is None:
        return pd.NaT

    try:
        return datetime(year, month, day, hour, minute)
    except Exception:
        return pd.NaT

# ------------------------------------------------------------------
# CARGA DE DATOS
# ------------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=True)
def load_data(url: str) -> gpd.GeoDataFrame:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    buffer = io.BytesIO(resp.content)
    gdf = gpd.read_file(buffer)

    # Asegurar CRS a WGS84 (lat/long) para el mapa
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    return gdf


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
# NORMALIZACIONES
# ------------------------------------------------------------------
# Parsear columna 'emision' a datetime
if COL_FECHA in gdf.columns:
    gdf[COL_FECHA] = gdf[COL_FECHA].apply(parse_emision_text)

if COL_TIPO in gdf.columns:
    gdf[COL_TIPO] = gdf[COL_TIPO].astype(str).str.title()

# ------------------------------------------------------------------
# FILTROS EN SIDEBAR
# ------------------------------------------------------------------
st.sidebar.header("Filtros")

# Tipo
tipos_disponibles = (
    sorted(gdf[COL_TIPO].dropna().astype(str).unique())
    if COL_TIPO in gdf.columns
    else []
)
tipos_seleccionados = st.sidebar.multiselect(
    "Tipo de evento",
    options=tipos_disponibles,
    default=tipos_disponibles,
) if tipos_disponibles else []

# Región (ordenada por 'orden')
regiones = (
    gdf[[COL_REGION, COL_ORDEN]]
    .dropna(subset=[COL_REGION])
    .drop_duplicates()
    .sort_values(COL_ORDEN)[COL_REGION]
    .astype(str)
    .tolist()
    if (COL_REGION in gdf.columns and COL_ORDEN in gdf.columns)
    else []
)

region_sel = st.sidebar.selectbox(
    "Región",
    options=["Todas"] + regiones if regiones else ["Todas"],
    index=0,
)

# Rango de fechas (ya como datetime)
if COL_FECHA in gdf.columns and gdf[COL_FECHA].notna().any():
    min_date = gdf[COL_FECHA].min().date()
    max_date = gdf[COL_FECHA].max().date()
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

if tipos_seleccionados and COL_TIPO in gdf_filtrado.columns:
    gdf_filtrado = gdf_filtrado[gdf_filtrado[COL_TIPO].isin(tipos_seleccionados)]

if region_sel != "Todas" and COL_REGION in gdf_filtrado.columns:
    gdf_filtrado = gdf_filtrado[gdf_filtrado[COL_REGION].astype(str) == region_sel]

if (
    COL_FECHA in gdf_filtrado.columns
    and isinstance(rango_fechas, (list, tuple))
    and len(rango_fechas) == 2
):
    desde, hasta = rango_fechas
    mask = (gdf_filtrado[COL_FECHA].dt.date >= desde) & (
        gdf_filtrado[COL_FECHA].dt.date <= hasta
    )
    gdf_filtrado = gdf_filtrado[mask]

st.caption(f"Registros visualizados (filas GeoJSON): {len(gdf_filtrado)}")

# ------------------------------------------------------------------
# KPI NACIONALES Y CRONÓMETRO
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
            <div style="font-size:0.9rem;">a nivel nacional (eventos únicos)</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def last_alert_card(fecha_ultima, codigo_ultimo, tipo_ultimo, fenomeno_ultimo):
    """Cuadrante con fecha/hora de última emisión, código (con color), fenómeno y tiempo transcurrido."""
    if fecha_ultima is None or pd.isna(fecha_ultima):
        contenido = """
        <div style="
            background-color:#ecf0f1;
            padding:1.2rem;
            border-radius:0.75rem;
            text-align:left;
            font-family:system-ui, sans-serif;
            box-shadow:0 2px 4px rgba(0,0,0,0.1);
        ">
            <div style="font-size:1.1rem;font-weight:600;margin-bottom:0.4rem;">
                Última emisión de alerta
            </div>
            <div style="font-size:0.95rem;">
                Sin información disponible.
            </div>
        </div>
        """
        st.markdown(contenido, unsafe_allow_html=True)
        return

    # Color del código según tipo
    tipo_norm = (tipo_ultimo or "").strip().title()
    if tipo_norm == "Aviso":
        code_color = "#d68910"   # amarillo/naranjo
    elif tipo_norm == "Alerta":
        code_color = "#e67e22"   # naranjo fuerte
    elif tipo_norm == "Alarma":
        code_color = "#c0392b"   # rojo
    else:
        code_color = "#34495e"   # neutro

    # Hora actual en Chile
    ahora_tz = pd.Timestamp.now(tz="America/Santiago")
    ahora = ahora_tz.tz_localize(None) if ahora_tz.tzinfo else ahora_tz

    delta = ahora - fecha_ultima
    dias = delta.days
    horas, resto = divmod(delta.seconds, 3600)
    minutos, _ = divmod(resto, 60)

    partes = []
    if dias > 0:
        partes.append(f"{dias} d")
    if horas > 0 or dias > 0:
        partes.append(f"{horas} h")
    partes.append(f"{minutos} min")
    delta_str = "  ".join(partes)

    fecha_str = fecha_ultima.strftime("%d-%m-%Y %H:%M")
    codigo_str = codigo_ultimo or ""
    fenomeno_str = fenomeno_ultimo or ""

    contenido = f"""
    <div style="
        background-color:#ecf0f1;
        padding:1.2rem;
        border-radius:0.75rem;
        text-align:left;
        font-family:system-ui, sans-serif;
        box-shadow:0 2px 4px rgba(0,0,0,0.1);
    ">
        <div style="font-size:1.1rem;font-weight:600;margin-bottom:0.4rem;">
            Última emisión de alerta
        </div>
        <div style="font-size:0.95rem;margin-bottom:0.15rem;">
            {fecha_str} hrs
        </div>
        <div style="font-size:0.9rem;margin-bottom:0.15rem;">
            Tipo: {tipo_norm}
        </div>
        <div style="font-size:0.9rem;margin-bottom:0.15rem;">
            Código:
            <span style="font-weight:700;color:{code_color};">
                {codigo_str}
            </span>
        </div>
        <div style="font-size:0.9rem;margin-bottom:0.35rem;">
            Fenómeno: {fenomeno_str}
        </div>
        <div style="font-size:0.85rem;color:#555;margin-bottom:0.2rem;">
            Tiempo transcurrido
        </div>
        <div style="font-size:1.3rem;font-weight:700;">
            {delta_str}
        </div>
    </div>
    """
    st.markdown(contenido, unsafe_allow_html=True)

# conteo nacional
if {COL_CODIGO, COL_TIPO}.issubset(gdf_filtrado.columns):
    eventos_nacionales = gdf_filtrado[[COL_CODIGO, COL_TIPO]].drop_duplicates()
    count_aviso = eventos_nacionales[eventos_nacionales[COL_TIPO] == "Aviso"].shape[0]
    count_alerta = eventos_nacionales[eventos_nacionales[COL_TIPO] == "Alerta"].shape[0]
    count_alarma = eventos_nacionales[eventos_nacionales[COL_TIPO] == "Alarma"].shape[0]
else:
    count_aviso = count_alerta = count_alarma = 0

# última fecha de emisión y datos asociados (dataset completo, no filtrado)
if COL_FECHA in gdf.columns and gdf[COL_FECHA].notna().any():
    idx_last = gdf[COL_FECHA].idxmax()
    ultima_fecha = gdf.at[idx_last, COL_FECHA]
    ultimo_codigo = gdf.at[idx_last, COL_CODIGO] if COL_CODIGO in gdf.columns else None
    ultimo_tipo = gdf.at[idx_last, COL_TIPO] if COL_TIPO in gdf.columns else None
    ultimo_fenomeno = gdf.at[idx_last, COL_FENOMENO] if COL_FENOMENO in gdf.columns else None
else:
    ultima_fecha = None
    ultimo_codigo = None
    ultimo_tipo = None
    ultimo_fenomeno = None

# 3 KPI + 1 cuadrante de cronómetro arriba a la derecha
col_k1, col_k2, col_k3, col_k4 = st.columns([1, 1, 1, 1.4])
with col_k1:
    kpi_card("Aviso(s)", count_aviso, "#f7e86e")
with col_k2:
    kpi_card("Alerta(s)", count_alerta, "#f6a623")
with col_k3:
    kpi_card("Alarma(s)", count_alarma, "#e74c3c")
with col_k4:
    last_alert_card(ultima_fecha, ultimo_codigo, ultimo_tipo, ultimo_fenomeno)

st.markdown("---")

# ------------------------------------------------------------------
# DISTRIBUCIÓN POR REGIÓN (EVENTO-REGIÓN ÚNICO) + TABLA
# ------------------------------------------------------------------
left_col, right_col = st.columns([1.2, 1.8])

with left_col:
    st.subheader("Avisos, Alertas y Alarmas por región (eventos únicos)")

    if {COL_REGION, COL_ORDEN, COL_CODIGO}.issubset(gdf_filtrado.columns):
        df_reg = (
            gdf_filtrado[[COL_REGION, COL_ORDEN, COL_CODIGO]]
            .dropna(subset=[COL_REGION])
            .drop_duplicates()
            .groupby([COL_REGION, COL_ORDEN])[COL_CODIGO]
            .nunique()
            .reset_index(name="Total")
            .sort_values(COL_ORDEN)
        )

        orden_regiones = df_reg.sort_values(COL_ORDEN)[COL_REGION].tolist()
        chart = (
            alt.Chart(df_reg)
            .mark_bar()
            .encode(
                x=alt.X(
                    COL_REGION,
                    sort=orden_regiones,
                    title="Región",
                ),
                y=alt.Y("Total:Q", title="Número de eventos"),
                tooltip=[COL_REGION, "Total"],
            )
            .properties(height=350, width="container")
        )
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("No hay información suficiente para agrupar por región.")

    # TABLA DETALLADA: evento–región únicos
    st.subheader("Detalle de eventos por región")

    columnas_base = []
    renombres = {}

    for col, nombre in [
        (COL_TIPO, "Tipo"),
        (COL_REGION, "Región"),
        (COL_CODIGO, "Código"),
        (COL_FENOMENO, "Fenómeno"),
        (COL_FECHA, "Emisión"),
        (COL_ESTADO, "Estado"),
    ]:
        if col in gdf_filtrado.columns:
            columnas_base.append(col)
            renombres[col] = nombre

    columnas_base = list(dict.fromkeys(columnas_base))

    if columnas_base:
        df_tabla = (
            gdf_filtrado[columnas_base]
            .drop_duplicates(subset=[COL_CODIGO, COL_REGION])
            .rename(columns=renombres)
        )
        st.dataframe(df_tabla, use_container_width=True, height=420)
    else:
        st.info("No se encontraron columnas estándar para mostrar la tabla de eventos.")

with right_col:
    st.subheader("Mapa de eventos activos")

    if "geometry" in gdf_filtrado.columns and gdf_filtrado.geometry.notna().any():
        view_state = pdk.ViewState(latitude=-34.5, longitude=-71.0, zoom=3.0)

        features = []
        for _, row in gdf_filtrado.iterrows():
            geom = row.geometry
            if geom is None:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "tipo": str(row.get(COL_TIPO, "")),
                        "region": str(row.get(COL_REGION, "")),
                        "codigo": str(row.get(COL_CODIGO, "")),
                        "fenomeno": str(row.get(COL_FENOMENO, "")),
                    },
                    "geometry": geom.__geo_interface__,
                }
            )

        if features:
            layer = pdk.Layer(
                "GeoJsonLayer",
                data={"type": "FeatureCollection", "features": features},
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
                map_style=None,
            )

            st.pydeck_chart(deck, use_container_width=True, width=500, height=700)
        else:
            st.info("No hay geometrías válidas para mostrar en el mapa.")
    else:
        st.info("No hay geometrías disponibles para mostrar en el mapa.")

# ------------------------------------------------------------------
# DATOS BRUTOS (OPCIONAL)
# ------------------------------------------------------------------
with st.expander("Ver datos en bruto (GeoDataFrame)"):
    st.write(gdf.head())
    st.text("Columnas disponibles:")
    st.write(list(gdf.columns))
    if COL_FECHA in gdf.columns:
        st.text(f"Ejemplo de valor parseado en '{COL_FECHA}': {gdf[COL_FECHA].iloc[0]}")

