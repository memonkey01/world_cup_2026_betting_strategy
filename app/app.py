"""
Monitor Streamlit del sistema Elo + Bayes del Mundial.

Correr:
    streamlit run app.py

Modos:
  - "Backtest Qatar 2022": usa el fixture incluido (offline, sin red).
  - "En vivo 2026": scrapea ESPN via Playwright y actualiza al cerrar jornada.

Vistas:
  - Tabla combinada (Elo rating + media bayesiana + intervalo de credibilidad)
  - Evolucion de Elo por jornada (line chart)
  - Distribucion bayesiana por equipo (media + intervalo)
  - Calibracion: Brier, LogLoss y curva de fiabilidad
"""

from __future__ import annotations
import streamlit as st
import pandas as pd

from src.pipeline import Pipeline
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE, load_fifa_ranking
from src.qatar_fixture import QATAR_2022_SAMPLE

st.set_page_config(page_title="Mundial Elo + Bayes", layout="wide")

# ---- estilo PyPro-ish dark tech ----
st.markdown("""
<style>
  .stApp { background:#0F1117; }
  h1,h2,h3 { color:#22D3EE; }
  .metric-card { background:#1A1D27; border-radius:12px; padding:16px; }
</style>
""", unsafe_allow_html=True)

st.title("⚽ Mundial — Elo + Bayes Monitor")

# ----------------------------------------------------------------------
# Sidebar: configuracion
# ----------------------------------------------------------------------
with st.sidebar:
    st.header("Configuración")
    mode = st.radio("Modo", ["Backtest Qatar 2022", "En vivo 2026"])
    k_factor = st.slider("Factor K (Elo)", 10, 80, 40, 5)
    prior_strength = st.slider("Fuerza del prior Bayes", 1.0, 12.0, 4.0, 1.0)
    use_margin = st.checkbox("Multiplicador por margen de gol", value=True)

    fifa_source = st.radio("Ranking FIFA inicial", ["Snapshot incluido", "Subir JSON"])
    fifa_points = FIFA_SNAPSHOT_EXAMPLE
    if fifa_source == "Subir JSON":
        up = st.file_uploader("JSON {equipo: puntos}", type="json")
        if up:
            import json
            fifa_points = {k: float(v) for k, v in json.load(up).items()}

    if mode == "En vivo 2026":
        date_range = st.text_input("Rango de fechas ESPN", "20260611-20260710")
        engine = st.selectbox("Scraper", ["Playwright", "requests (fallback)"])
        run_scrape = st.button("Actualizar jornada (scrape ESPN)")


# ----------------------------------------------------------------------
# Carga de partidos
# ----------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def get_qatar_matches():
    return QATAR_2022_SAMPLE


def scrape_live(date_range: str, engine: str):
    from src.scraper import fetch_via_playwright, fetch_via_requests
    fn = fetch_via_playwright if engine == "Playwright" else fetch_via_requests
    raw = fn(date_range, league="fifa.world")
    return [(m.date, m.stage, m.home, m.away, m.home_goals, m.away_goals)
            for m in raw if m.finished]


if mode == "Backtest Qatar 2022":
    matches = get_qatar_matches()
else:
    matches = []
    if "live_matches" in st.session_state:
        matches = st.session_state["live_matches"]
    if "run_scrape" in dir() and run_scrape:
        with st.spinner("Scrapeando ESPN…"):
            matches = scrape_live(date_range, engine)
            st.session_state["live_matches"] = matches
        st.success(f"{len(matches)} partidos finalizados cargados.")

if not matches:
    st.info("Sin partidos cargados todavía. (En vivo: pulsa «Actualizar jornada».)")
    st.stop()

# ----------------------------------------------------------------------
# Ejecutar pipeline
# ----------------------------------------------------------------------
from src.elo import EloSystem
pipe = Pipeline(elo=EloSystem(k=float(k_factor), use_margin=use_margin))
pipe.seed(fifa_points)
# re-seed bayes con la fuerza elegida
pipe.bayes.seed_from_elo(pipe.initial_elo, strength=float(prior_strength))
pipe.process_all(matches)

lb = pd.DataFrame(pipe.combined_leaderboard())

# ----------------------------------------------------------------------
# KPIs
# ----------------------------------------------------------------------
rep = pipe.calibration_report()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Partidos procesados", rep["n_matches"])
c2.metric("Brier score", f'{rep["brier"]:.4f}', help="0 = perfecto · 0.25 = azar")
c3.metric("Log loss", f'{rep["log_loss"]:.4f}')
c4.metric("Líder Elo", lb.iloc[0]["team"])

tab1, tab2, tab3, tab4 = st.tabs(["🏆 Tabla", "📈 Evolución Elo", "🎲 Bayes", "🎯 Calibración"])

# ---- Tab 1: tabla combinada ----
with tab1:
    st.subheader("Ranking combinado Elo + Bayes")
    show = lb.copy()
    show.columns = ["Equipo", "Elo", "Elo inicial", "Δ Elo",
                    "Bayes media", "Bayes inf", "Bayes sup"]
    st.dataframe(show, use_container_width=True, height=600)

# ---- Tab 2: evolucion Elo por jornada ----
with tab2:
    st.subheader("Evolución de Elo por partido")
    top_n = st.slider("Mostrar top N equipos", 4, 16, 8)
    top_teams = [r["team"] for r in pipe.combined_leaderboard()[:top_n]]
    rows = []
    for i, snap in enumerate(pipe.snapshots):
        for t in top_teams:
            if t in snap["elo"]:
                rows.append({"paso": i, "Equipo": t, "Elo": snap["elo"][t]})
    evo = pd.DataFrame(rows)
    if not evo.empty:
        pivot = evo.pivot(index="paso", columns="Equipo", values="Elo").ffill()
        st.line_chart(pivot)

# ---- Tab 3: distribucion bayesiana ----
with tab3:
    st.subheader("Fuerza latente (Beta-Bernoulli) — media e intervalo 95%")
    bdf = lb[["team", "bayes_mean", "bayes_lo", "bayes_hi"]].head(16).copy()
    bdf["err_low"] = bdf["bayes_mean"] - bdf["bayes_lo"]
    bdf["err_high"] = bdf["bayes_hi"] - bdf["bayes_mean"]
    st.caption("Empate = 0.5 éxito. Intervalos anchos = pocos partidos (alta incertidumbre).")
    chart_df = bdf.set_index("team")[["bayes_lo", "bayes_mean", "bayes_hi"]]
    chart_df.columns = ["Inferior", "Media", "Superior"]
    st.bar_chart(chart_df[["Media"]])
    st.dataframe(bdf[["team", "bayes_mean", "bayes_lo", "bayes_hi"]],
                 use_container_width=True)

# ---- Tab 4: calibracion ----
with tab4:
    st.subheader("Validación de la distribución predicha (calibración)")
    st.caption("Si el modelo está bien calibrado, prob. predicha ≈ frecuencia observada.")
    rel = pd.DataFrame(rep["reliability"])
    if not rel.empty:
        rel_idx = rel.set_index("bin")[["avg_pred", "avg_obs"]]
        rel_idx.columns = ["Predicho", "Observado"]
        st.line_chart(rel_idx)
        st.dataframe(rel, use_container_width=True)
    st.markdown(
        f"**Brier {rep['brier']:.4f}** · **LogLoss {rep['log_loss']:.4f}** · "
        f"{rep['n_matches']} partidos."
    )
