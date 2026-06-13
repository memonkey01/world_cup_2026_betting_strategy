"""
Página Backtest del sistema Elo + Bayes del Mundial (Qatar 2022, offline).

Correr (desde app/):
    uv run streamlit run app.py

Vistas: tabla combinada, evolución de Elo, distribución bayesiana, calibración
y evolución combinada Elo+Bayes. La página "Mundial en vivo" y el "Simulador de
apuestas" están en pages/. Los parámetros del modelo se comparten entre páginas
vía session_state (ver ui_common).
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
from src.ingest import (ingest_qatar_backtest, load_matches, clear_snapshots,
                        persist_snapshots)
from ui_common import model_controls, fifa_ranking

st.set_page_config(page_title="Backtest — Mundial Elo+Bayes", layout="wide")

# ---- estilo PyPro-ish dark tech ----
st.markdown("""
<style>
  .stApp { background:#0F1117; }
  h1,h2,h3 { color:#22D3EE; }
  .metric-card { background:#1A1D27; border-radius:12px; padding:16px; }
</style>
""", unsafe_allow_html=True)

st.title("📊 Backtest — Mundial (Qatar 2022)")

# Panel explicativo: cómo funciona el sistema completo (visible en la UI).
with st.expander("ℹ️ ¿Cómo funciona este monitor?", expanded=False):
    st.markdown("""
El sistema procesa los partidos **en orden** y mantiene dos modelos en paralelo:

1. **Semilla FIFA → Elo.** El ranking FIFA se re-centra a la escala Elo clásica
   (~1500 de media) para dar el *rating inicial* de cada selección.
2. **Elo por partido.** Tras cada juego: `R' = R + K·(S − E)`, donde
   `S ∈ {1, 0.5, 0}` (victoria / empate / derrota) y `E` es la probabilidad
   esperada (curva logística por diferencia de rating). **K** (barra lateral)
   controla la reactividad; el **multiplicador por margen** amplifica K cuando
   la goleada es amplia.
3. **Bayes (Beta-Bernoulli).** Cada equipo tiene una *fuerza latente*
   `θ ~ Beta(a, b)` con prior anclado a su Elo inicial. Cada partido es un
   ensayo (empate = 0.5 éxito) → posterior conjugado, que da una **media** y un
   **intervalo de credibilidad** (incertidumbre: se estrecha con más partidos).
4. **Calibración.** La probabilidad que el Elo emite *antes* de cada partido se
   compara con el resultado real → **Brier**, **LogLoss** y curva de fiabilidad.

**Datos:** la base SQLite es la fuente de verdad. Esta página siembra Qatar 2022
(offline) y lee de la DB. Para datos en vivo usa la página **Mundial en vivo**.

Mueve los controles de la izquierda y todo se recalcula al instante.
""")

# Parámetros del modelo (compartidos entre páginas vía session_state).
k_factor, prior_strength, use_margin = model_controls()
fifa_points = fifa_ranking()


# ----------------------------------------------------------------------
# Engine de la base de datos (cacheado por sesión)
# ----------------------------------------------------------------------
@st.cache_resource
def get_db():
    eng = get_engine()
    init_db(eng)
    return eng


db_engine = get_db()

# Backtest: siembra la DB con Qatar 2022 la primera vez y luego lee de ella.
with Session(db_engine) as s:
    t = s.exec(select(Tournament).where(Tournament.name == "Qatar 2022")).first()
    has_matches = t and s.exec(select(Match).where(Match.tournament_id == t.id)).first()
    if not has_matches:
        with st.spinner("Sembrando DB con Qatar 2022…"):
            t = ingest_qatar_backtest(s, fifa_points=fifa_points, prefer_scrape=False)
    matches = load_matches(s, t)

if not matches:
    st.info("Sin partidos en la DB todavía.")
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

# Persistir la evolución (borra y reescribe los snapshots del torneo).
with Session(db_engine) as s:
    tq = s.exec(select(Tournament).where(Tournament.name == "Qatar 2022")).first()
    if tq:
        clear_snapshots(s, tq)
        persist_snapshots(s, tq, pipe)

# ----------------------------------------------------------------------
# KPIs
# ----------------------------------------------------------------------
rep = pipe.calibration_report()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Partidos procesados", rep["n_matches"],
          help="Total de partidos que alimentaron el modelo.")
c2.metric("Brier score", f'{rep["brier"]:.4f}',
          help="Error cuadrático medio de la probabilidad. 0 = perfecto · 0.25 = azar. Menor es mejor.")
c3.metric("Log loss", f'{rep["log_loss"]:.4f}',
          help="Penaliza fuerte la confianza equivocada. Menor es mejor.")
c4.metric("Líder Elo", lb.iloc[0]["team"],
          help="Selección con mayor rating Elo tras procesar todos los partidos.")

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["🏆 Tabla", "📈 Evolución Elo", "🎲 Bayes", "🎯 Calibración",
     "📉 Evolución combinada"])

# ---- Tab 1: tabla combinada ----
with tab1:
    st.subheader("Ranking combinado Elo + Bayes")
    st.caption(
        "Cada fila es una selección. **Elo** = fuerza actual; **Δ Elo** = cuánto "
        "subió/bajó respecto a su semilla FIFA. **Bayes media/inf/sup** = fuerza "
        "latente estimada y su intervalo de credibilidad 95%. Ordenado por Elo."
    )
    show = lb.copy()
    show.columns = ["Equipo", "Elo", "Elo inicial", "Δ Elo",
                    "Bayes media", "Bayes inf", "Bayes sup"]
    st.dataframe(show, use_container_width=True, height=600)

# ---- Tab 2: evolucion Elo por jornada ----
with tab2:
    st.subheader("Evolución de Elo por partido")
    st.caption(
        "Cómo cambió el rating Elo de los mejores equipos a lo largo del torneo. "
        "El eje X es el paso (partido procesado); las líneas se mantienen planas "
        "cuando ese equipo no jugó en ese paso."
    )
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
