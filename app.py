import os
import re
import csv
import zipfile
import math
import pdfplumber
import geopandas as gpd
import streamlit as st
import folium
from shapely.geometry import Polygon
from streamlit_folium import st_folium

# ==============================
# 📌 Encabezado
# ==============================
st.set_page_config(page_title="GeorreferenciaciónTH", layout="wide")
st.title("🌍 GeorreferenciaciónTH")
st.markdown("""
### Victor Enrique Mendoza Astopilco  
**Especialista en Gestión del Catastro Forestal - BPS**
---
""")

# ==============================
# 🔹 Extraer vértices
# ==============================
def extraer_vertices(pdf_path):
    vertices = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    for row in table:
                        cleaned_row = [re.sub(r"[^\d\.Pp]", "", str(cell)) if cell else "" for cell in row]
                        p_matches = [c for c in cleaned_row if re.match(r"^P?\d+$", c, re.IGNORECASE)]
                        e_matches = [c for c in cleaned_row if re.match(r"^\d{6,}\.?\d*$", c)]
                        n_matches = [c for c in cleaned_row if re.match(r"^\d{7,}\.?\d*$", c)]

                        if len(p_matches) >= 1 and len(e_matches) >= 1 and len(n_matches) >= 1:
                            v_str = p_matches[0].replace("P", "").replace("p", "")
                            v = int(v_str) if v_str.isdigit() else len(vertices) + 1
                            e = float(e_matches[0])
                            n = float(n_matches[0])
                            vertices.append((v, e, n))
    except Exception as e:
        st.error(f"⚠️ Error en extracción: {e}")
    return vertices

# ==============================
# 🔹 Separar en bloques
# ==============================
def split_into_blocks(vertices, distance_threshold=2000, salto_max=50):
    if not vertices:
        return []
    reinicios = sum(1 for (prev, cur) in zip(vertices, vertices[1:]) if cur[0] <= prev[0])
    if len(vertices) > 300 and reinicios == 0:
        return [vertices]

    blocks = []
    current = [vertices[0]]
    for prev, cur in zip(vertices, vertices[1:]):
        prev_id, prev_e, prev_n = prev
        cur_id, cur_e, cur_n = cur
        dist = math.hypot(cur_e - prev_e, cur_n - prev_n)

        if cur_id <= prev_id or (cur_id - prev_id) > salto_max or dist > distance_threshold:
            blocks.append(current)
            current = [cur]
            continue
        current.append(cur)
    if current:
        blocks.append(current)
    return [blk for blk in blocks if len(blk) >= 3]

# ==============================
# 🔹 Procesar PDF
# ==============================
def procesar_pdf(pdf_path, zona_utm=18, distance_threshold=2000):
    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    out_dir = basename + "_out"
    os.makedirs(out_dir, exist_ok=True)

    vertices = extraer_vertices(pdf_path)
    if not vertices or len(vertices) < 3:
        st.warning(f"⚠️ No se detectaron suficientes vértices en {basename}")
        return None, None, None

    st.write(f"🔎 **Vértices detectados:** {len(vertices)}")
    blocks = split_into_blocks(vertices, distance_threshold=distance_threshold)
    st.write(f"🔎 **Bloques detectados (posibles polígonos):** {len(blocks)}")

    geoms, pids, areas = [], [], []
    for pid, blk in enumerate(blocks, start=1):
        coords = [(e, n) for v, e, n in blk]
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        if len(coords) < 4:
            continue
        poly = Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_valid and not poly.is_empty:
            geoms.append(poly)
            pids.append(pid)
            areas.append(poly.area / 10000)  # hectáreas

    if not geoms:
        st.error("❌ No se pudieron construir polígonos válidos.")
        return None, None, None

    crs_utm = f"EPSG:327{zona_utm}"
    gdf = gpd.GeoDataFrame({"PoligonoID": pids, "Area_ha": areas}, geometry=geoms, crs=crs_utm)

    # 📊 Reporte de áreas
    st.subheader("📊 Áreas por polígono (ha)")
    total_area = sum(areas)
    for pid, area in zip(pids, areas):
        st.write(f"   Polígono {pid}: {area:.2f} ha")
    st.success(f"🔹 Área total: {total_area:.2f} ha")

    # Exportar CSV
    csv_path = os.path.join(out_dir, f"{basename}_vertices.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["PoligonoID", "Vertice", "Este", "Norte"])
        for pid, blk in enumerate(blocks, start=1):
            for v, e, n in blk:
                writer.writerow([pid, v, e, n])

    # Guardar GeoJSON
    geojson_path = os.path.join(out_dir, f"{basename}_poligonos.geojson")
    gdf.to_file(geojson_path, driver="GeoJSON")

    # Guardar Shapefile (y zip)
    shp_path = os.path.join(out_dir, f"{basename}_poligonos.shp")
    gdf.to_file(shp_path, driver="ESRI Shapefile")
    shp_base = os.path.splitext(shp_path)[0]
    zip_name = os.path.join(out_dir, f"{basename}_shapefile.zip")
    with zipfile.ZipFile(zip_name, "w") as zf:
        for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
            p = shp_base + ext
            if os.path.exists(p):
                zf.write(p, arcname=os.path.basename(p))

    return gdf, csv_path, geojson_path, zip_name

# ==============================
# 🔹 Interfaz Streamlit
# ==============================
uploaded_file = st.file_uploader("📂 Sube tu PDF", type=["pdf"])
zona = st.selectbox("🌍 Selecciona zona UTM", [17, 18, 19], index=1)

if uploaded_file is not None:
    with open(uploaded_file.name, "wb") as f:
        f.write(uploaded_file.getbuffer())

    gdf, csv_path, geojson_path, zip_name = procesar_pdf(uploaded_file.name, zona_utm=zona)

    if gdf is not None:
        # 🌍 Mapa interactivo con Folium
        m = folium.Map(location=[gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()], zoom_start=12)
        for _, row in gdf.iterrows():
            coords = [(y, x) for x, y in row.geometry.exterior.coords]
            folium.Polygon(
                coords,
                color="blue",
                fill=True,
                fill_opacity=0.4,
                popup=f"Polígono {row['PoligonoID']} - {row['Area_ha']:.2f} ha"
            ).add_to(m)
        st_folium(m, width=800, height=500)

        # 📥 Descargas
        st.download_button("⬇️ Descargar CSV", open(csv_path, "rb"), file_name=os.path.basename(csv_path))
        st.download_button("⬇️ Descargar GeoJSON", open(geojson_path, "rb"), file_name=os.path.basename(geojson_path))
        st.download_button("⬇️ Descargar Shapefile (ZIP)", open(zip_name, "rb"), file_name=os.path.basename(zip_name))

