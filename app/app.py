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
import altair as alt
from sqlmodel import Session, select

from src.pipeline import Pipeline
from src.elo import EloSystem
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE
from src.db import get_engine, init_db
from src.models import Match, Tournament
from src.ingest import ingest_qatar_backtest, ingest_live, load_matches
from src.scraper import fetch_via_playwright, fetch_via_requests

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
        scraper_engine = st.selectbox("Scraper", ["Playwright", "requests (fallback)"])
        run_scrape = st.button("Actualizar jornada (scrape ESPN)")


# ----------------------------------------------------------------------
# Engine de la base de datos (cacheado por sesión)
# ----------------------------------------------------------------------
@st.cache_resource
def get_db():
    eng = get_engine()
    init_db(eng)
    return eng

db_engine = get_db()


# ----------------------------------------------------------------------
# Carga de partidos (DB = fuente de verdad)
# ----------------------------------------------------------------------
if mode == "Backtest Qatar 2022":
    with Session(db_engine) as s:
        t = s.exec(select(Tournament).where(
            Tournament.name == "Qatar 2022")).first()
        has_matches = t and s.exec(select(Match).where(
            Match.tournament_id == t.id)).first()
        if not has_matches:
            with st.spinner("Sembrando DB con Qatar 2022…"):
                t = ingest_qatar_backtest(s, fifa_points=fifa_points,
                                          prefer_scrape=False)
        matches = load_matches(s, t)
else:
    matches = []
    if run_scrape:
        fn = (fetch_via_playwright if scraper_engine == "Playwright"
              else fetch_via_requests)
        with st.spinner("Scrapeando ESPN y guardando en DB…"):
            with Session(db_engine) as s:
                t = ingest_live(s, date_range, scrape_fn=fn,
                                fifa_points=fifa_points)
                matches = load_matches(s, t)
        st.success(f"{len(matches)} partidos finalizados guardados.")
    else:
        with Session(db_engine) as s:
            t = s.exec(select(Tournament).where(
                Tournament.name == "World Cup 2026")).first()
            matches = load_matches(s, t) if t else []

if not matches:
    st.info("Sin partidos cargados todavía. (En vivo: pulsa «Actualizar jornada».)")
    st.stop()

# ----------------------------------------------------------------------
# Ejecutar pipeline
# ----------------------------------------------------------------------
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

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["🏆 Tabla", "📈 Evolución Elo", "🎲 Bayes", "🎯 Calibración",
     "📉 Evolución combinada"])

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

# ---- Tab 5: evolucion combinada Elo + Bayes (doble eje Y) ----
with tab5:
    st.subheader("Evolución combinada — Elo y probabilidad bayesiana")
    st.caption(
        "Eje X = partido jugado por el equipo. "
        "**Línea sólida = Elo** (eje izq, ~1500) · "
        "**línea punteada = prob. Bayes** (eje der, 0–1). Color = equipo."
    )
    all_teams = [r["team"] for r in pipe.combined_leaderboard()]
    sel = st.multiselect("Selecciones a comparar", all_teams,
                         default=all_teams[:3])
    evo_df = pd.DataFrame(pipe.team_evolution())
    plot_df = evo_df[evo_df["team"].isin(sel)] if sel else evo_df.iloc[0:0]

    if plot_df.empty:
        st.info("Elige al menos una selección.")
    else:
        base = alt.Chart(plot_df).encode(
            x=alt.X("match_no:Q", title="Partido del equipo",
                    axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("team:N", title="Equipo"),
            tooltip=["team:N", "match_no:Q",
                     alt.Tooltip("elo:Q", format=".0f"),
                     alt.Tooltip("bayes:Q", format=".3f")],
        )
        elo_line = base.mark_line(point=True).encode(
            y=alt.Y("elo:Q", title="Elo",
                    scale=alt.Scale(zero=False)),
        )
        bayes_line = base.mark_line(point=True, strokeDash=[4, 4]).encode(
            y=alt.Y("bayes:Q", title="Prob. Bayes",
                    scale=alt.Scale(domain=[0, 1])),
        )
        chart = alt.layer(elo_line, bayes_line).resolve_scale(
            y="independent").properties(height=520)
        st.altair_chart(chart, use_container_width=True)
