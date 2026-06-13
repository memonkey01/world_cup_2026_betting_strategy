"""
🧪 Qatar 2022 — laboratorio del workflow.

Un solo lugar para, paso a paso:
  1. configurar el modelo y la apuesta (barra lateral),
  2. ver cómo se comporta el modelo Elo/Bayes sobre Qatar 2022 (monitor),
  3. correr el backtest de apuestas con ESAS variables,
  4. FIJAR esa misma configuración como estrategia activa (la usa «Mundial en vivo»).

El panel lateral y la estrategia que se fija están LIGADOS: «Guardar
configuración actual» persiste exactamente los parámetros de la izquierda.
"""
from __future__ import annotations
import pandas as pd
import altair as alt
import streamlit as st
from sqlmodel import Session, select

from src.pipeline import Pipeline
from src.elo import EloSystem
from src.db import get_engine, init_db
from src.models import Match, Tournament
from src.ingest import (ingest_qatar_backtest, load_matches, clear_snapshots,
                        persist_snapshots)
from src.betting import BetParams, simulate, sweep_strategies
from src.strategies import save_active_strategy, load_active_strategy
from ui_common import model_controls, betting_controls, fifa_ranking

st.set_page_config(page_title="Qatar 2022 — Laboratorio", layout="wide")
st.title("🧪 Qatar 2022 — laboratorio de estrategias")
st.caption("Configura a la izquierda, mira el modelo, corre el backtest y fija la "
           "estrategia. Lo que fijes aquí lo usará «Mundial en vivo». "
           "Backtest educativo, no consejo de apuestas.")

with st.expander("ℹ️ ¿Cómo se usa este laboratorio? (paso a paso)", expanded=False):
    st.markdown("""
1. **Paso 1 — Modelo** (barra lateral): ajusta **K**, la fuerza del prior Bayes y
   el multiplicador por margen. Define cómo aprende el modelo.
2. **Paso 2 — Apuesta** (barra lateral): fija **bankroll**, cuota, **criterio de
   lado** (Elo/Bayes/mezcla), umbral de Bayes, jornada de arranque, **sizing**
   (flat/confianza/Kelly) y si filtras por Bayes. Esta es tu *meta-estrategia*.
3. **Monitor del modelo** (abajo): cómo evolucionan Elo y la fuerza latente Bayes
   sobre Qatar 2022, y qué tan calibradas quedan las probabilidades (Brier/LogLoss).
4. **Backtest de apuestas**: simula tu configuración partido a partido y muestra
   ROI, yield, % de acierto, drawdown y la curva de bankroll.
5. **Fijar**: «Guardar configuración actual» persiste **estos** parámetros como la
   estrategia activa. «Mundial en vivo» recomendará 2026 con ella.

¿No sabes qué combinación conviene? Abre **🔬 Explorar combinaciones**: barre las
18 variantes, elige una y «Aplicar al panel» la copia a la izquierda para que la
revises y la fijes.
""")


@st.cache_resource
def get_db():
    eng = get_engine()
    init_db(eng)
    return eng


db_engine = get_db()

# ----------------------------------------------------------------------
# Sidebar: Paso 1 (modelo) + Paso 2 (apuesta) -> UN solo BetParams (params)
# ----------------------------------------------------------------------
k_factor, prior_strength, use_margin = model_controls()
fifa_points = fifa_ranking()
common = betting_controls()

st.sidebar.header("Estrategia (sizing y filtro)")
sizing = st.sidebar.selectbox(
    "Bet sizing", ["flat", "confidence", "kelly"],
    format_func={"flat": "Flat (% fijo)",
                 "confidence": "Proporcional a confianza",
                 "kelly": "Kelly fraccional"}.get,
    key="sim_sizing")
use_filter = st.sidebar.checkbox("Filtrar por umbral de Bayes", value=False,
                                 key="sim_filter")

params = BetParams(sizing=sizing, use_bayes_filter=use_filter, **common)

# ----------------------------------------------------------------------
# Datos + pipeline (siembra Qatar 2022 la primera vez)
# ----------------------------------------------------------------------
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

pipe = Pipeline(elo=EloSystem(k=float(k_factor), use_margin=use_margin))
pipe.seed(fifa_points)
pipe.bayes.seed_from_elo(pipe.initial_elo, strength=float(prior_strength))
pipe.process_all(matches)

lb = pd.DataFrame(pipe.combined_leaderboard())

# Persistir la evolución (borra y reescribe los snapshots del torneo).
with Session(db_engine) as s:
    tq = s.exec(select(Tournament).where(Tournament.name == "Qatar 2022")).first()
    if tq:
        clear_snapshots(s, tq)
        persist_snapshots(s, tq, pipe)

# ======================================================================
# CUERPO 1 — Monitor del modelo (Elo + Bayes + calibración)
# ======================================================================
st.header("1 · Monitor del modelo")
rep = pipe.calibration_report()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Partidos procesados", rep["n_matches"])
c2.metric("Brier score", f'{rep["brier"]:.4f}',
          help="0 = perfecto · 0.25 = azar. Menor es mejor.")
c3.metric("Log loss", f'{rep["log_loss"]:.4f}', help="Menor es mejor.")
c4.metric("Líder Elo", lb.iloc[0]["team"])

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["🏆 Tabla", "📈 Evolución Elo", "🎲 Bayes", "🎯 Calibración",
     "📉 Evolución combinada"])

with tab1:
    st.caption("**Elo** = fuerza actual; **Δ Elo** = cambio vs la semilla FIFA; "
               "**Bayes media/inf/sup** = fuerza latente y su intervalo 95%.")
    show = lb.copy()
    show.columns = ["Equipo", "Elo", "Elo inicial", "Δ Elo",
                    "Bayes media", "Bayes inf", "Bayes sup"]
    st.dataframe(show, use_container_width=True, height=520)

with tab2:
    st.caption("Evolución del rating Elo de los mejores equipos a lo largo del torneo.")
    top_n = st.slider("Mostrar top N equipos", 4, 16, 8)
    top_teams = [r["team"] for r in pipe.combined_leaderboard()[:top_n]]
    rows = []
    for i, snap in enumerate(pipe.snapshots):
        for tm in top_teams:
            if tm in snap["elo"]:
                rows.append({"paso": i, "Equipo": tm, "Elo": snap["elo"][tm]})
    evo = pd.DataFrame(rows)
    if not evo.empty:
        pivot = evo.pivot(index="paso", columns="Equipo", values="Elo").ffill()
        st.line_chart(pivot)

with tab3:
    st.caption("Empate = 0.5 éxito. Intervalos anchos = pocos partidos (alta incertidumbre).")
    bdf = lb[["team", "bayes_mean", "bayes_lo", "bayes_hi"]].head(16).copy()
    chart_df = bdf.set_index("team")[["bayes_mean"]]
    chart_df.columns = ["Media"]
    st.bar_chart(chart_df)
    st.dataframe(bdf, use_container_width=True)

with tab4:
    st.caption("Si está bien calibrado, prob. predicha ≈ frecuencia observada.")
    rel = pd.DataFrame(rep["reliability"])
    if not rel.empty:
        rel_idx = rel.set_index("bin")[["avg_pred", "avg_obs"]]
        rel_idx.columns = ["Predicho", "Observado"]
        st.line_chart(rel_idx)
        st.dataframe(rel, use_container_width=True)
    st.markdown(f"**Brier {rep['brier']:.4f}** · **LogLoss {rep['log_loss']:.4f}** · "
                f"{rep['n_matches']} partidos.")

with tab5:
    st.caption("**Línea sólida = Elo** (eje izq) · **punteada = prob. Bayes** "
               "(eje der, 0–1). Color = equipo.")
    all_teams = [r["team"] for r in pipe.combined_leaderboard()]
    sel = st.multiselect("Selecciones a comparar", all_teams, default=all_teams[:3])
    evo_df = pd.DataFrame(pipe.team_evolution())
    plot_df = evo_df[evo_df["team"].isin(sel)] if sel else evo_df.iloc[0:0]
    if plot_df.empty:
        st.info("Elige al menos una selección.")
    else:
        base = alt.Chart(plot_df).encode(
            x=alt.X("match_no:Q", title="Partido del equipo",
                    axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("team:N", title="Equipo"),
            tooltip=["team:N", "match_no:Q", alt.Tooltip("elo:Q", format=".0f"),
                     alt.Tooltip("bayes:Q", format=".3f")])
        elo_line = base.mark_line(point=True).encode(
            y=alt.Y("elo:Q", title="Elo", scale=alt.Scale(zero=False)))
        bayes_line = base.mark_line(point=True, strokeDash=[4, 4]).encode(
            y=alt.Y("bayes:Q", title="Prob. Bayes", scale=alt.Scale(domain=[0, 1])))
        st.altair_chart(
            alt.layer(elo_line, bayes_line).resolve_scale(y="independent")
            .properties(height=480), use_container_width=True)

# ======================================================================
# CUERPO 2 — Backtest de apuestas con TU configuración (params del sidebar)
# ======================================================================
st.header("2 · Backtest de apuestas (tu configuración)")
st.caption(f"Sizing **{sizing}** · criterio **{common['side_criterion']}** · "
           f"filtro Bayes **{'sí' if use_filter else 'no'}** · "
           f"cuota fija **{common['odds']:.2f}** · arranque jornada "
           f"**{common['start_match_no']}**.")

res = simulate(pipe.match_log, params)
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Bankroll final", f'{res["bankroll_final"]:.0f}',
          delta=f'{res["profit"]:+.0f}')
k2.metric("ROI", f'{res["roi"]*100:.1f}%')
k3.metric("Yield", f'{res["yield"]*100:.1f}%' if res["total_staked"] else "—")
k4.metric("Apuestas", res["n_bets"])
k5.metric("Aciertos", f'{res["win_rate"]*100:.1f}%' if res["n_bets"] else "—")
k6.metric("Max drawdown", f'{res["max_drawdown"]:.0f}')

curve_df = pd.DataFrame(res["curve"])
line = alt.Chart(curve_df).mark_line().encode(
    x=alt.X("bet_no:Q", title="Nº de apuesta"),
    y=alt.Y("bankroll:Q", title="Bankroll", scale=alt.Scale(zero=False)),
).properties(height=360)
rule = alt.Chart(pd.DataFrame({"y": [float(common["bankroll0"])]})).mark_rule(
    strokeDash=[4, 4], color="gray").encode(y="y:Q")
st.altair_chart(line + rule, use_container_width=True)

with st.expander("Detalle de apuestas y comparativa con/sin filtro Bayes"):
    res_flt = simulate(pipe.match_log,
                       BetParams(sizing=sizing, use_bayes_filter=not use_filter,
                                 **common))
    otro = "sin filtro" if use_filter else f"con filtro (>{common['bayes_threshold']:.2f})"
    cc1, cc2 = st.columns(2)
    cc1.metric(f"Yield (variante {otro})",
               f'{res_flt["yield"]*100:.1f}%' if res_flt["total_staked"] else "—")
    cc2.metric(f"ROI (variante {otro})", f'{res_flt["roi"]*100:.1f}%')
    st.dataframe(pd.DataFrame(res["bets"]), use_container_width=True, height=320)

# ======================================================================
# CUERPO 3 — Fijar la configuración actual como estrategia activa (LIGADO)
# ======================================================================
st.header("3 · Fijar estrategia")
with Session(db_engine) as s:
    active = load_active_strategy(s)
if active is not None:
    st.caption(f"Estrategia activa ahora mismo: **{active.label}**.")
else:
    st.caption("Todavía no hay ninguna estrategia activa fijada.")

label = (f"{sizing} + {common['side_criterion']} + "
         f"filtro {'sí' if use_filter else 'no'}")
st.markdown(f"Vas a fijar: **{label}** "
            f"(yield Qatar {res['yield']*100:.1f}% · ROI {res['roi']*100:.1f}%).")
if st.button("📌 Guardar configuración actual como estrategia activa"):
    with Session(db_engine) as s:
        save_active_strategy(s, params, label,
                             yield_=res["yield"], roi=res["roi"])
    st.success(f"Estrategia activa fijada: **{label}**. "
               "La página «Mundial en vivo» la usará para recomendar 2026.")

# ======================================================================
# Explorar combinaciones (opcional) — barre 18 combos y aplica al panel
# ======================================================================
with st.expander("🔬 Explorar combinaciones (sweep) y aplicarlas al panel"):
    st.caption("Barre sizing × criterio × filtro sobre Qatar y rankea por yield. "
               "Elige una y «Aplicar al panel» la copia a la barra lateral.")
    ranking = sweep_strategies(pipe.match_log, BetParams(**common))
    LABELS = {"flat": "Flat", "confidence": "Confianza", "kelly": "Kelly",
              "elo": "Elo", "bayes": "Bayes", "blend": "Mezcla"}
    rank_rows = []
    for i, r in enumerate(ranking):
        m = r["metrics"]
        rank_rows.append({
            "#": i + 1, "sizing": LABELS[r["sizing"]],
            "criterio": LABELS[r["side_criterion"]],
            "filtro Bayes": "sí" if r["use_bayes_filter"] else "no",
            "yield %": round(m["yield"] * 100, 1), "ROI %": round(m["roi"] * 100, 1),
            "apuestas": m["n_bets"], "% acierto": round(m["win_rate"] * 100, 1),
            "drawdown": round(m["max_drawdown"], 0),
        })
    st.dataframe(pd.DataFrame(rank_rows), use_container_width=True,
                 hide_index=True, height=320)

    opciones = {f'#{i+1} · {LABELS[r["sizing"]]} + {LABELS[r["side_criterion"]]}'
                f' + filtro {"sí" if r["use_bayes_filter"] else "no"}': i
                for i, r in enumerate(ranking)}

    def aplicar_combo():
        i = opciones[st.session_state["sweep_choice"]]
        r = ranking[i]
        st.session_state["sim_sizing"] = r["sizing"]
        st.session_state["side_criterion"] = r["side_criterion"]
        st.session_state["sim_filter"] = r["use_bayes_filter"]

    st.selectbox("Combinación", list(opciones), index=0, key="sweep_choice")
    st.button("⬅️ Aplicar al panel", on_click=aplicar_combo,
              help="Copia sizing/criterio/filtro de la combo elegida a la barra "
                   "lateral. Luego revísala y pulsa «Guardar configuración actual».")
