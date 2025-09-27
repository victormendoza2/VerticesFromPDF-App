import streamlit as st
import pdfplumber
import geopandas as gpd
import zipfile, os, re, csv, math
from shapely.geometry import Polygon

# ==============================
# Función para extraer vértices
# ==============================
def extraer_vertices(pdf_file):
    vertices = []
    with pdfplumber.open(pdf_file) as pdf:
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
                        e = float(e_matches[0]); n = float(n_matches[0])
                        vertices.append((v, e, n))
    return vertices

# ==============================
# Función para dividir en bloques
# ==============================
def split_into_blocks(vertices, distance_threshold=2000, salto_max=50):
    if not vertices: return []
    reinicios = sum(1 for (prev, cur) in zip(vertices, vertices[1:]) if cur[0] <= prev[0])
    if len(vertices) > 300 and reinicios == 0:
        return [vertices]
    blocks, current = [], [vertices[0]]
    for prev, cur in zip(vertices, vertices[1:]):
        prev_id, prev_e, prev_n = prev
        cur_id, cur_e, cur_n = cur
        dist = math.hypot(cur_e - prev_e, cur_n - prev_n)
        if cur_id <= prev_id or (cur_id - prev_id) > salto_max or dist > distance_threshold:
            blocks.append(current); current = [cur]; continue
        current.append(cur)
    if current: blocks.append(current)
    return [blk for blk in blocks if len(blk) >= 3]

# ==============================
# Interfaz Streamlit
# ==============================
st.title("📐 Georreferenciación de RA")
st.write("Desarrollado por **Victor Enrique Mendoza Astopilco**")
st.write("Especialista en Gestión del Catastro Forestal - BPS")

pdf_file = st.file_uploader("📂 Sube tu PDF con coordenadas", type="pdf")
zona = st.selectbox("🌍 Selecciona la zona UTM", [17, 18, 19])

if pdf_file and st.button("Procesar PDF"):
    vertices = extraer_vertices(pdf_file)
    if not vertices or len(vertices) < 3:
        st.error("⚠️ No se detectaron suficientes vértices.")
    else:
        st.success(f"🔎 vértices detectados: {len(vertices)}")
        blocks = split_into_blocks(vertices)
        st.info(f"🔎 bloques detectados: {len(blocks)}")

        geoms, pids, areas = [], [], []
        for pid, blk in enumerate(blocks, start=1):
            coords = [(e, n) for v, e, n in blk]
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            poly = Polygon(coords)
            if not poly.is_valid: poly = poly.buffer(0)
            if poly.is_valid and not poly.is_empty:
                geoms.append(poly); pids.append(pid); areas.append(poly.area / 10000)

        if geoms:
            crs_utm = f"EPSG:327{zona}"
            gdf = gpd.GeoDataFrame({"PoligonoID": pids, "Area_ha": areas}, geometry=geoms, crs=crs_utm)

            st.success(f"✅ polígonos válidos: {len(geoms)}")
            st.write("📊 Áreas por polígono (ha):")
            for pid, area in zip(pids, areas):
                st.write(f"   Polígono {pid}: {area:.2f} ha")

            # Exportar resultados
            basename = os.path.splitext(pdf_file.name)[0]
            out_dir = basename + "_out"
            os.makedirs(out_dir, exist_ok=True)

            # CSV
            csv_path = os.path.join(out_dir, f"{basename}_vertices.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f); writer.writerow(["PoligonoID","Vertice","Este","Norte"])
                for pid, blk in enumerate(blocks, start=1):
                    for v, e, n in blk:
                        writer.writerow([pid, v, e, n])
            st.download_button("⬇️ Descargar CSV", open(csv_path,"rb"), file_name=f"{basename}_vertices.csv")

            # GeoJSON
            geojson_path = os.path.join(out_dir, f"{basename}_poligonos.geojson")
            gdf.to_file(geojson_path, driver="GeoJSON")
            st.download_button("⬇️ Descargar GeoJSON", open(geojson_path,"rb"), file_name=f"{basename}_poligonos.geojson")

            # Shapefile (ZIP)
            shp_path = os.path.join(out_dir, f"{basename}_poligonos.shp")
            gdf.to_file(shp_path, driver="ESRI Shapefile")
            shp_base = os.path.splitext(shp_path)[0]
            zip_name = os.path.join(out_dir, f"{basename}_shapefile.zip")
            with zipfile.ZipFile(zip_name, "w") as zf:
                for ext in [".shp",".shx",".dbf",".prj",".cpg"]:
                    p = shp_base + ext
                    if os.path.exists(p): zf.write(p, arcname=os.path.basename(p))
            st.download_button("⬇️ Descargar Shapefile (ZIP)", open(zip_name,"rb"), file_name=f"{basename}_shapefile.zip")
