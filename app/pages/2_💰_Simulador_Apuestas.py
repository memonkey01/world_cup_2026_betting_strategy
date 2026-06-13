"""
Simulador de apuestas (backtest estilo Winners) sobre el Mundial.

Carga Qatar 2022 de la DB, arma el Pipeline (foto pre-partido en match_log) y
simula dos estrategias con la misma meta-estrategia configurable:
  - "Apostar a todos"  (sin filtro Bayes)
  - "Solo Bayes > umbral"
"""
from __future__ import annotations
import pandas as pd
import altair as alt
import streamlit as st
from sqlmodel import Session, select

from src.pipeline import Pipeline
from src.elo import EloSystem
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE
from src.db import get_engine, init_db
from src.models import Match, Tournament
from src.ingest import ingest_qatar_backtest, load_matches
from src.betting import BetParams, simulate

st.set_page_config(page_title="Simulador de apuestas", layout="wide")
st.title("💰 Simulador de apuestas — Mundial (backtest)")
st.caption("Mercado: gana el equipo elegido (empate o derrota = apuesta perdida). "
           "Cuotas sintéticas fijas. Esto es un backtest educativo, no consejo de apuestas.")


@st.cache_resource
def get_db():
    eng = get_engine()
    init_db(eng)
    return eng


db_engine = get_db()

with st.sidebar:
    st.header("Modelo")
    k_factor = st.slider("Factor K (Elo)", 10, 80, 40, 5)
    prior_strength = st.slider("Fuerza del prior Bayes", 1.0, 12.0, 4.0, 1.0)
    use_margin = st.checkbox("Multiplicador por margen de gol", value=True)

    st.header("Apuestas")
    bankroll0 = st.number_input("Bankroll inicial", 100.0, 1_000_000.0, 1000.0, 100.0)
    odds = st.number_input("Cuota decimal fija", 1.01, 10.0, 2.0, 0.05)
    start_match_no = st.slider("Apostar desde la jornada (nº de partido del equipo)",
                               1, 5, 2)
    sizing = st.selectbox("Bet sizing",
                          ["flat", "confidence", "kelly"],
                          format_func={"flat": "Flat (% fijo)",
                                       "confidence": "Proporcional a confianza",
                                       "kelly": "Kelly fraccional"}.get)
    base_fraction = st.slider("Fracción base del bankroll", 0.01, 0.50, 0.05, 0.01)
    kelly_fraction = st.slider("Fracción de Kelly", 0.05, 1.0, 0.25, 0.05)

    st.header("Meta-estrategia (criterio de lado)")
    side_criterion = st.selectbox("Criterio para elegir el lado",
                                  ["elo", "bayes", "blend"],
                                  format_func={"elo": "Elo (favorito)",
                                               "bayes": "Mayor media Bayes",
                                               "blend": "Mezcla Elo/Bayes"}.get)
    blend_weight = st.slider("Peso de Elo en la mezcla (blend)", 0.0, 1.0, 0.5, 0.05)
    bayes_threshold = st.slider("Umbral de Bayes (estrategia filtrada)",
                                0.30, 0.80, 0.50, 0.01)

# --- datos + pipeline ---
with Session(db_engine) as s:
    t = s.exec(select(Tournament).where(Tournament.name == "Qatar 2022")).first()
    has_matches = t and s.exec(select(Match).where(Match.tournament_id == t.id)).first()
    if not has_matches:
        with st.spinner("Sembrando DB con Qatar 2022…"):
            t = ingest_qatar_backtest(s, fifa_points=FIFA_SNAPSHOT_EXAMPLE,
                                      prefer_scrape=False)
    matches = load_matches(s, t)

pipe = Pipeline(elo=EloSystem(k=float(k_factor), use_margin=use_margin))
pipe.seed(FIFA_SNAPSHOT_EXAMPLE)
pipe.bayes.seed_from_elo(pipe.initial_elo, strength=float(prior_strength))
pipe.process_all(matches)

common = dict(bankroll0=float(bankroll0), odds=float(odds), sizing=sizing,
              base_fraction=float(base_fraction), kelly_fraction=float(kelly_fraction),
              start_match_no=int(start_match_no), side_criterion=side_criterion,
              blend_weight=float(blend_weight), bayes_threshold=float(bayes_threshold))

res_all = simulate(pipe.match_log, BetParams(use_bayes_filter=False, **common))
res_flt = simulate(pipe.match_log, BetParams(use_bayes_filter=True, **common))

# --- KPIs comparados ---
st.subheader("Resultados")
colA, colB = st.columns(2)


def show_kpis(col, title, r):
    col.markdown(f"### {title}")
    col.metric("Bankroll final", f'{r["bankroll_final"]:.0f}',
               delta=f'{r["profit"]:+.0f}')
    col.metric("ROI", f'{r["roi"]*100:.1f}%')
    col.metric("Apuestas", r["n_bets"])
    col.metric("Aciertos", f'{r["win_rate"]*100:.1f}%' if r["n_bets"] else "—")
    col.metric("Yield", f'{r["yield"]*100:.1f}%' if r["total_staked"] else "—")
    col.metric("Max drawdown", f'{r["max_drawdown"]:.0f}')


show_kpis(colA, "Apostar a todos", res_all)
show_kpis(colB, f"Solo Bayes > {bayes_threshold:.2f}", res_flt)

# --- curvas de bankroll ---
st.subheader("Evolución del bankroll")
curve_rows = ([{"bet_no": c["bet_no"], "bankroll": c["bankroll"],
                "Estrategia": "Apostar a todos"} for c in res_all["curve"]]
              + [{"bet_no": c["bet_no"], "bankroll": c["bankroll"],
                  "Estrategia": f"Solo Bayes > {bayes_threshold:.2f}"}
                 for c in res_flt["curve"]])
curve_df = pd.DataFrame(curve_rows)
line = alt.Chart(curve_df).mark_line().encode(
    x=alt.X("bet_no:Q", title="Nº de apuesta"),
    y=alt.Y("bankroll:Q", title="Bankroll"),
    color=alt.Color("Estrategia:N", title="Estrategia"),
).properties(height=420)
rule = alt.Chart(pd.DataFrame({"y": [float(bankroll0)]})).mark_rule(
    strokeDash=[4, 4], color="gray").encode(y="y:Q")
st.altair_chart(line + rule, use_container_width=True)

# --- tablas de apuestas ---
st.subheader("Detalle de apuestas")
tA, tB = st.tabs(["Apostar a todos", f"Solo Bayes > {bayes_threshold:.2f}"])
with tA:
    st.dataframe(pd.DataFrame(res_all["bets"]), use_container_width=True, height=400)
with tB:
    st.dataframe(pd.DataFrame(res_flt["bets"]), use_container_width=True, height=400)
