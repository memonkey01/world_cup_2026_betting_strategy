"""
🏠 Inicio — guía del workflow y tablero de estado.

Esta página NO entrena ni apuesta: explica el flujo de la app y muestra en qué
punto del workflow estás (¿hay calendario?, ¿estrategia fijada?, ¿cuotas
frescas?). El trabajo vive en las otras páginas (barra lateral):

    🧪 Qatar 2022      laboratorio: configurar → ver modelo → backtest → FIJAR
    🔴 Mundial en vivo producción: consume la estrategia fijada y recomienda
    🗄️ Datos           inspección read-only de la base de datos

Correr (desde app/):  uv run streamlit run app.py
"""
from __future__ import annotations
from datetime import datetime, timedelta

import streamlit as st
from sqlmodel import Session, select

from src.db import get_engine, init_db
from src.models import Match, Tournament
from src.strategies import load_active_strategy
from src.odds_store import latest_scrape_iso

st.set_page_config(page_title="Inicio — Mundial Elo+Bayes", layout="wide")

# ---- estilo PyPro-ish dark tech ----
st.markdown("""
<style>
  .stApp { background:#0F1117; }
  h1,h2,h3 { color:#22D3EE; }
</style>
""", unsafe_allow_html=True)

st.title("🏠 Mundial 2026 — Elo + Bayes + Apuestas")
st.caption("Monitor Elo/Bayes + motor de apuestas para el Mundial. Esta es la "
           "página de inicio: explica el flujo y te dice en qué paso vas.")


@st.cache_resource
def get_db():
    eng = get_engine()
    init_db(eng)
    return eng


db_engine = get_db()

# ----------------------------------------------------------------------
# El workflow en una frase + diagrama
# ----------------------------------------------------------------------
st.markdown("""
### El workflow, en 4 pasos

La idea no es "una app con páginas", sino **un flujo Laboratorio → Producción**:
entrenas y eliges una estrategia con datos pasados (Qatar 2022), la **fijas**, y
la página en vivo la usa para recomendar apuestas en el Mundial 2026.
""")

st.code("""🧪 Qatar 2022  →  configurar K/prior/apuesta · ver el modelo Elo/Bayes ·
   (laboratorio)    correr el backtest de apuestas · FIJAR la mejor estrategia
        │
        │  (la estrategia activa se guarda en la DB = puente entre páginas)
        ▼
🔴 Mundial en vivo →  scrapear ESPN (calendario) · traer cuotas reales ·
   (producción)       recomendar lado + stake con ELO·Bayes·Kelly y la cuota elegida
        │
        ▼
🗄️ Datos          →  revisar qué hay en la base (filas, head, última actualización)
""", language="text")

st.info("💾 **La base de datos SQLite es la fuente de verdad.** El scraper la "
        "llena (calendario + resultados), el pipeline Elo/Bayes lee de ella y la "
        "estrategia fijada vive ahí. Por eso las páginas concuerdan entre sí.")

# ----------------------------------------------------------------------
# Tablero de estado: ¿en qué paso del workflow estoy?
# ----------------------------------------------------------------------
st.subheader("📍 ¿Dónde voy en el workflow?")

with Session(db_engine) as s:
    wc = s.exec(select(Tournament).where(Tournament.name == "World Cup 2026")).first()
    n_cal = n_fin = 0
    if wc:
        ms = s.exec(select(Match).where(Match.tournament_id == wc.id)).all()
        n_cal = len(ms)
        n_fin = sum(1 for m in ms if m.finished)
    active = load_active_strategy(s)
    poly_iso = latest_scrape_iso(s, wc, "polymarket") if wc else None
    cod_iso = latest_scrape_iso(s, wc, "codere") if wc else None

# ¿Cuotas frescas? (cualquier fuente con fetched_at < 24h)
fresh_iso = max([x for x in (poly_iso, cod_iso) if x], default=None)
cuotas_frescas = False
if fresh_iso:
    try:
        cuotas_frescas = datetime.fromisoformat(fresh_iso) > datetime.now() - timedelta(hours=24)
    except ValueError:
        cuotas_frescas = False


def estado(ok: bool) -> str:
    return "✅" if ok else "⬜"


col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(f"#### {estado(active is not None)} 1 · Estrategia")
    if active is not None:
        yld = (f"{active.backtest_yield*100:.1f}%"
               if active.backtest_yield is not None else "n/d")
        st.markdown(f"Fijada: **{active.label}**  \n"
                    f"sizing `{active.sizing}` · criterio `{active.side_criterion}` "
                    f"· yield Qatar {yld}")
    else:
        st.markdown("Sin estrategia fijada. Ve a **🧪 Qatar 2022**, corre el "
                    "backtest y pulsa *Guardar configuración actual*.")
with col2:
    st.markdown(f"#### {estado(n_cal > 0)} 2 · Calendario 2026")
    if n_cal:
        st.markdown(f"**{n_cal}** partidos en DB  \n"
                    f"({n_fin} finalizados · {n_cal - n_fin} programados)")
    else:
        st.markdown("Sin calendario. Ve a **🔴 Mundial en vivo** y pulsa "
                    "*Actualizar (scrape ESPN)*.")
with col3:
    st.markdown(f"#### {estado(cuotas_frescas)} 3 · Cuotas")
    if fresh_iso:
        edad = "frescas (<24h)" if cuotas_frescas else "viejas (>24h)"
        st.markdown(f"Última: `{fresh_iso}`  \n{edad}")
    else:
        st.markdown("Sin cuotas. En **🔴 Mundial en vivo → 💱 Cuotas** pulsa "
                    "*Actualizar solo cuotas*.")

# ----------------------------------------------------------------------
# Menú: enlaces directos a cada página
# ----------------------------------------------------------------------
st.subheader("🧭 Ir a")
st.page_link("pages/2_🧪_Qatar_2022.py",
             label="🧪 Qatar 2022 — laboratorio: modelo + backtest + fijar estrategia")
st.page_link("pages/1_🔴_Mundial_en_vivo.py",
             label="🔴 Mundial en vivo — calendario, cuotas y recomendaciones 2026")
st.page_link("pages/3_🗄️_Datos.py",
             label="🗄️ Datos — explorar las tablas de la base de datos")

with st.expander("ℹ️ ¿Qué hace cada pieza del modelo?", expanded=False):
    st.markdown("""
- **Semilla FIFA → Elo.** El ranking FIFA se re-centra a la escala Elo clásica
  (~1500 de media) para dar el rating inicial de cada selección.
- **Elo por partido.** `R' = R + K·(S − E)`, con `S ∈ {1, 0.5, 0}` y un
  multiplicador opcional por margen de gol. **K** controla la reactividad.
- **Bayes (Beta-Bernoulli).** Cada equipo tiene una fuerza latente `θ ~ Beta(a,b)`
  con prior anclado al Elo; cada partido es un ensayo (empate = 0.5) → posterior
  conjugado con media e intervalo de credibilidad.
- **Apuestas.** ELO elige el lado, Bayes filtra (opcional) y el *sizing*
  (flat / confianza / Kelly) decide el stake. Se calibra contra Qatar y se fija
  la mejor estrategia para usarla en vivo.

Backtest educativo, **no** consejo de apuestas.
""")
