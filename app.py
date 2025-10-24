# FILE: app.py
# -*- coding: utf-8 -*-
"""
Herramienta de Mapeo Participativo — Streamlit
------------------------------------------------
Tabs:
- Mapa: muestra puntos provenientes de Google Sheets.
- Registrarse: formulario, geocodifica dirección y guarda en Google Sheets.
- Intranet: acceso con clave simple "mau" para editar/borrar.

▶ Configuración requerida:
1) Crear una Google Sheet vacía y obtener su ID (lo que va en la URL entre /d/ y /edit).
2) Crear una cuenta de servicio en GCP y descargar el JSON de credenciales.
3) En Streamlit, cargar ese JSON en st.secrets como se indica en `.streamlit/secrets.toml.example`.
4) Compartir la hoja con el email de la cuenta de servicio (Editor).
"""

from __future__ import annotations
import uuid
import time
from datetime import datetime
from typing import Tuple, Optional

import pandas as pd
import streamlit as st
import pydeck as pdk

# Geocodificación
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials

APP_TITLE = "Herramienta de Mapeo Participativo [DEMO]"
SHEET_WORKSHEET = "registros"

# -------------------------
# Utilidades Google Sheets
# -------------------------

@st.cache_resource(show_spinner=False)
def get_gs_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    info = st.secrets["gcp_service_account"]
    credentials = Credentials.from_service_account_info(info, scopes=scopes)
    client = gspread.authorize(credentials)
    return client

@st.cache_resource(show_spinner=False)
def open_or_init_sheet():
    """Abre la hoja por SHEET_ID y garantiza la worksheet con headers mínimos."""
    sheet_id = st.secrets.get("SHEET_ID", "").strip()
    if not sheet_id:
        st.error("Falta `SHEET_ID` en `st.secrets`. Revisa README.")
        st.stop()
    client = get_gs_client()
    sh = client.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(SHEET_WORKSHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHEET_WORKSHEET, rows=1000, cols=30)
        ws.append_row(get_headers())
    # Si la primera fila está vacía, setear headers
    first_row = ws.row_values(1)
    if not first_row:
        ws.append_row(get_headers())
    elif first_row != get_headers():
        # Asegura que existan todas las columnas (agrega faltantes al final)
        current = first_row
        needed = get_headers()
        if current != needed:
            # Fusionar preservando el orden base
            cols = list(dict.fromkeys(current + [c for c in needed if c not in current]))
            # Actualizar encabezados
            ws.delete_rows(1)
            ws.insert_row(cols, 1)
    return sh, ws


def get_headers() -> list:
    return [
        "record_id",
        "timestamp",
        "rep_name",
        "email",
        "space_name",
        "year_established",
        # Dirección desglosada (mínimos para geocodificación robusta en Chile)
        "street_and_number",  # Calle y número
        "unit_or_sector",     # Depto/sector (opcional)
        "comuna",
        "city",
        "region",
        "country",
        "postal_code",
        "full_address",       # concatenado para geocodificar
        # Geocodificación
        "latitude",
        "longitude",
        "geocode_provider",
        "geocode_status",
        "notes",
    ]


def read_df() -> pd.DataFrame:
    _, ws = open_or_init_sheet()
    values = ws.get_all_records()
    df = pd.DataFrame(values)
    if df.empty:
        df = pd.DataFrame(columns=get_headers())
    # Tipos
    if "latitude" in df.columns:
        df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    if "longitude" in df.columns:
        df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    return df


def overwrite_df(df: pd.DataFrame) -> None:
    sh, ws = open_or_init_sheet()
    # Limpia y reescribe todo (simple y robusto para volúmenes bajos/medios)
    ws.clear()
    ws.update([df.columns.tolist()] + df.fillna("").astype(str).values.tolist())


def append_record(row: dict) -> None:
    _, ws = open_or_init_sheet()
    # Garantiza el orden de columnas
    data = [row.get(col, "") for col in get_headers()]
    ws.append_row(list(map(str, data)))

# -------------------------
# Geocodificación
# -------------------------

@st.cache_resource(show_spinner=False)
def get_geocoder():
    geolocator = Nominatim(user_agent="herramienta-mapeo-participativo")
    # Respetar rate limit por conveniencia
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.0)
    return geocode


def build_full_address(street_and_number: str,
                       unit_or_sector: str,
                       comuna: str,
                       city: str,
                       region: str,
                       country: str,
                       postal_code: str) -> str:
    parts = [street_and_number]
    if unit_or_sector:
        parts.append(unit_or_sector)
    # En Chile, "comuna" es clave, incluir ciudad si aplica
    for p in [comuna, city, region, country, postal_code]:
        if p:
            parts.append(p)
    return ", ".join(parts)


def geocode_address(full_address: str) -> Tuple[Optional[float], Optional[float], str]:
    geocode = get_geocoder()
    try:
        loc = geocode(full_address)
        if loc:
            return loc.latitude, loc.longitude, "ok"
        return None, None, "not_found"
    except Exception as e:
        return None, None, f"error: {e}"

# -------------------------
# UI Helpers
# -------------------------

def success_notice(msg: str):
    st.success(msg, icon="✅")

def warn_notice(msg: str):
    st.warning(msg, icon="⚠️")

def error_notice(msg: str):
    st.error(msg, icon="❌")

# -------------------------
# PÁGINA
# -------------------------

st.set_page_config(page_title=APP_TITLE, page_icon="🗺️", layout="wide")

st.logo("images/logo_livlin.png", size="large")


st.title(APP_TITLE)
st.caption(
    "Herramienta personalizable para organizaciones que requieran mapear espacios, proyectos o iniciativas con datos georreferenciados. "
    "Contáctanos en [www.livlin.cl](https://www.livlin.cl) para diseñar una solución adaptada y colaborativa."
)

# Tabs
map_tab, register_tab, intranet_tab = st.tabs(["🗺️ Mapa", "📝 Registrarse", "🔐 Intranet"])


# --------------
# TAB: MAPA — versión final estable con Streamlit nativo
# --------------
with map_tab:
    st.subheader("Mapa de espacios registrados")

    if st.button("🔄 Recargar datos desde la hoja"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

    df = read_df()

    if df.empty:
        st.warning("Aún no hay registros en la base de datos.")
        st.stop()

    # Convertir a numérico y limpiar
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    valid_points = df.dropna(subset=["latitude", "longitude"]).copy()

    if valid_points.empty:
        st.warning("No hay coordenadas válidas para mostrar en el mapa.")
        st.info("Usa la pestaña 📝 Registrarse para agregar una dirección completa.")
        st.map(pd.DataFrame({"lat": [-33.45], "lon": [-70.66]}))  # centro Chile
        st.stop()

    st.success(f"Se encontraron {len(valid_points)} registros con coordenadas válidas.")

    # Vista previa
    with st.expander("Ver coordenadas cargadas"):
        st.dataframe(valid_points[["space_name", "latitude", "longitude"]], use_container_width=True)

    # Convertir a formato correcto
    map_df = valid_points.rename(columns={"latitude": "lat", "longitude": "lon"})[["lat", "lon"]]

    # Mostrar mapa nativo de Streamlit (sin pydeck ni tokens)
    st.caption("🗺️ Mapa interactivo (base libre de Streamlit)")
    st.map(map_df, zoom=8, size=50)

    # Tabla completa
    with st.expander("Ver tabla completa de registros"):
        st.dataframe(
            valid_points[
                [
                    "space_name",
                    "rep_name",
                    "email",
                    "year_established",
                    "full_address",
                    "latitude",
                    "longitude",
                    "geocode_status",
                ]
            ].sort_values("space_name"),
            use_container_width=True,
        )

# ------------------
# TAB: REGISTRARSE
# ------------------
with register_tab:
    st.subheader("Inscribir un nuevo espacio")
    st.markdown("**Campos mínimos para georreferenciar en Chile:** Calle y número, Comuna, Región y País. Ciudad y Código Postal ayudan a mejorar la precisión (si aplica).")

    with st.form("registro_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            rep_name = st.text_input("Nombre de persona representante*", placeholder="Jane Doe")
        with col2:
            email = st.text_input("Email*", placeholder="nombre@dominio.cl")

        space_name = st.text_input("Nombre del espacio*", placeholder="Huerta Comunitaria X")
        year_established = st.number_input("Año de creación del espacio*", min_value=1900, max_value=datetime.now().year, value=2020, step=1)

        st.markdown("### Dirección del espacio (para georreferenciar)")
        c1, c2 = st.columns([2, 1])
        with c1:
            street_and_number = st.text_input("Calle y número*", placeholder="Av. Ejemplo 1234")
            unit_or_sector = st.text_input("Depto/Sector (opcional)", placeholder="Depto 402 / Sector El Molino")
            comuna = st.text_input("Comuna*", placeholder="Talagante")
        with c2:
            city = st.text_input("Ciudad/Localidad (opcional)", placeholder="Talagante")
            region = st.text_input("Región*", placeholder="Región Metropolitana")
            country = st.text_input("País*", value="Chile")
            postal_code = st.text_input("Código Postal (opcional)", placeholder="Número postal")

        notes = st.text_area("Notas (opcional)", placeholder="Información adicional relevante…")

        submitted = st.form_submit_button("Registrar")

    if submitted:
        # Validación mínima
        mandatory = [rep_name, email, space_name, street_and_number, comuna, region, country]
        if any(not x for x in mandatory):
            error_notice("Por favor completa todos los campos obligatorios marcados con *.")
        else:
            full_address = build_full_address(
                street_and_number, unit_or_sector, comuna, city, region, country, postal_code
            )
            with st.spinner("Geocodificando dirección…"):
                lat, lon, status = geocode_address(full_address)
            if status != "ok" or lat is None or lon is None:
                error_notice("No se pudo geocodificar la dirección. Revisa los datos o intenta agregando ciudad/código postal.")
                st.info(f"Dirección consultada: {full_address}")
            else:
                record = {
                    "record_id": str(uuid.uuid4()),
                    "timestamp": datetime.utcnow().isoformat(),
                    "rep_name": rep_name.strip(),
                    "email": email.strip(),
                    "space_name": space_name.strip(),
                    "year_established": int(year_established),
                    "street_and_number": street_and_number.strip(),
                    "unit_or_sector": unit_or_sector.strip(),
                    "comuna": comuna.strip(),
                    "city": city.strip(),
                    "region": region.strip(),
                    "country": country.strip(),
                    "postal_code": postal_code.strip(),
                    "full_address": full_address,
                    "latitude": lat,
                    "longitude": lon,
                    "geocode_provider": "Nominatim (OSM)",
                    "geocode_status": status,
                    "notes": notes.strip(),
                }
                try:
                    append_record(record)
                    success_notice("Registro guardado correctamente y georreferenciado.")
                    st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}))
                except Exception as e:
                    error_notice(f"Error al guardar en Google Sheets: {e}")

# ------------------
# TAB: INTRANET
# ------------------
with intranet_tab:
    st.subheader("Administración de registros")
    pwd = st.text_input("Clave de acceso", type="password")
    if pwd != "demo":
        st.info("Ingresa la clave para ver y editar la base de datos.")
        st.stop()

    df = read_df()
    if df.empty:
        warn_notice("No hay registros aún.")
        st.stop()

    st.markdown("**Editar registros** (haz clic en una celda para modificarla). Luego presiona Guardar cambios.")

    # Editor con columna auxiliar para borrar
    edit_df = df.copy()
    if "delete" not in edit_df.columns:
        edit_df.insert(0, "delete", False)

    edited = st.data_editor(
        edit_df,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "delete": st.column_config.CheckboxColumn("Borrar", help="Marca para borrar este registro"),
            "record_id": st.column_config.TextColumn(disabled=True),
            "timestamp": st.column_config.TextColumn(disabled=True),
        },
        hide_index=True,
    )

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Guardar cambios"):
            try:
                # Borrar los marcados
                keep = edited[~edited["delete"]].drop(columns=["delete"]) if "delete" in edited.columns else edited
                # Asegurar headers y tipos
                for col in get_headers():
                    if col not in keep.columns:
                        keep[col] = ""
                keep = keep[get_headers()]  # reordenar
                overwrite_df(keep)
                success_notice("Cambios guardados en Google Sheets.")
            except Exception as e:
                error_notice(f"Error al guardar cambios: {e}")
    with c2:
        if st.button("Recargar desde hoja"):
            st.rerun()




# ## Requisitos
# - Python 3.10+
# - Cuenta de servicio de Google Cloud con acceso a Google Sheets y Drive.
# - Una Google Sheet vacía (la app la inicializa con columnas si no existen).

# ## Configuración
# 1. Crea una Google Sheet vacía y copia su **ID** (lo que aparece en la URL: `https://docs.google.com/spreadsheets/d/ID_AQUI/edit`).
# 2. Crea una **Cuenta de Servicio** en GCP y descarga el JSON.
# 3. En tu proyecto Streamlit, crea el archivo `.streamlit/secrets.toml` a partir de `.streamlit/secrets.toml.example` y pega el JSON bajo `[gcp_service_account]`. Define `SHEET_ID` con el ID de tu hoja.
# 4. Comparte la Google Sheet con el `client_email` de la cuenta de servicio (permiso **Editor**).
# 5. Instala dependencias: `pip install -r requirements.txt`.
# 6. Ejecuta: `streamlit run app.py`.

# ## Uso
# - **Mapa**: muestra puntos usando `latitude/longitude` guardados.
# - **Registrarse**: completa el formulario; la app geocodifica con Nominatim (OSM) y guarda el registro en la hoja.
# - **Intranet**: usa la clave `mau` para editar/borrar registros (se reescribe la hoja al guardar cambios).

# ## Campos mínimos para geocodificar (recomendado en Chile)
# - Calle y número (obligatorio)
# - Comuna (obligatorio)
# - Región (obligatorio)
# - País (obligatorio)
# - Ciudad/Localidad (opcional, ayuda)
# - Código Postal (opcional, ayuda)

# ## Notas
# - Para geocodificación masiva o con SLA, considera un proveedor con API dedicada (ej. Google Maps Geocoding) y cache local.
# - Esta app es 100% personalizable: campos, validaciones, y vistas pueden adaptarse a las necesidades de cualquier organización.
