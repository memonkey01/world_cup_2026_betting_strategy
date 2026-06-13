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
from src.betting import BetParams, simulate, sweep_strategies
from src.strategies import save_active_strategy
from datetime import datetime, timedelta
from src.ingest import get_or_create_tournament, seed_teams, load_calendar
from src.odds import fetch_polymarket, fetch_codere, parse_polymarket, parse_codere
from src.odds_store import ingest_odds, latest_odds, latest_scrape_iso
from ui_common import model_controls, betting_controls

st.set_page_config(page_title="Simulador de apuestas", layout="wide")
st.title("💰 Simulador de apuestas — Mundial (backtest)")
st.caption("Mercado: gana el equipo elegido (empate o derrota = apuesta perdida). "
           "Cuotas sintéticas fijas. Esto es un backtest educativo, no consejo de apuestas.")

# Panel explicativo: cómo funciona el backtest de apuestas (visible en la UI).
with st.expander("ℹ️ ¿Cómo funciona el simulador?", expanded=False):
    st.markdown("""
Reproduce el Mundial partido a partido y, **antes de cada juego**, decide si
apostar usando solo la información disponible hasta ese momento (sin mirar el
resultado). Pasos en cada partido:

1. **Elegir lado** según el *criterio* (la meta-estrategia, configurable):
   - **Elo** → apuesta al favorito por rating.
   - **Bayes** → apuesta al de mayor fuerza latente estimada.
   - **Mezcla** → combina ambos con un peso ajustable.
2. **Filtrar** (solo la 2ª estrategia): si la media Bayes del lado elegido no
   supera el **umbral**, no se apuesta.
3. **Arranque:** no se apuesta antes de la *jornada* indicada (default 2), para
   dar al modelo un partido de calentamiento por equipo.
4. **Tamaño de apuesta** (*bet sizing* dinámico):
   - **Flat** → % fijo del bankroll.
   - **Confianza** → escala con qué tan arriba de 50% está la prob. del lado.
   - **Kelly fraccional** → fracción de Kelly según ventaja y cuota (0 si no hay ventaja).
5. **Liquidar:** si el equipo gana, `bankroll += stake·(cuota−1)`; si no, se
   pierde el stake.

Se corren **dos estrategias con los mismos parámetros** salvo el filtro Bayes
(*apostar a todos* vs *solo Bayes > umbral*) y se comparan **ROI**, **yield**
(ganancia / total apostado), **% de acierto** y **drawdown máximo** (mayor caída
desde un pico del bankroll).

⚠️ No hay cuotas reales: se usa una **cuota decimal fija** configurable. Es un
ejercicio de modelado, no una recomendación para apostar dinero real.
""")


@st.cache_resource
def get_db():
    eng = get_engine()
    init_db(eng)
    return eng


db_engine = get_db()

# Controles compartidos entre páginas (mismos parámetros para concordancia).
k_factor, prior_strength, use_margin = model_controls()
common = betting_controls()
st.sidebar.header("Estrategia (sizing)")
sizing = st.sidebar.selectbox("Bet sizing", ["flat", "confidence", "kelly"],
                              format_func={"flat": "Flat (% fijo)",
                                           "confidence": "Proporcional a confianza",
                                           "kelly": "Kelly fraccional"}.get,
                              key="sim_sizing")
bayes_threshold = common["bayes_threshold"]

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

res_all = simulate(pipe.match_log,
                   BetParams(sizing=sizing, use_bayes_filter=False, **common))
res_flt = simulate(pipe.match_log,
                   BetParams(sizing=sizing, use_bayes_filter=True, **common))

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
rule = alt.Chart(pd.DataFrame({"y": [float(common["bankroll0"])]})).mark_rule(
    strokeDash=[4, 4], color="gray").encode(y="y:Q")
st.altair_chart(line + rule, use_container_width=True)

# --- tablas de apuestas ---
st.subheader("Detalle de apuestas")
tA, tB = st.tabs(["Apostar a todos", f"Solo Bayes > {bayes_threshold:.2f}"])
with tA:
    st.dataframe(pd.DataFrame(res_all["bets"]), use_container_width=True, height=400)
with tB:
    st.dataframe(pd.DataFrame(res_flt["bets"]), use_container_width=True, height=400)

# ----------------------------------------------------------------------
# Laboratorio: barrido de estrategias y fijar la ganadora
# ----------------------------------------------------------------------
st.subheader("🧪 Laboratorio — comparar estrategias y fijar la mejor")
st.caption("Barre sizing × criterio de lado × filtro Bayes sobre Qatar y rankea "
           "por yield (ganancia / total apostado).")

base_params = BetParams(**common)   # sin sizing/filtro: el barrido los varía
ranking = sweep_strategies(pipe.match_log, base_params)

LABELS = {"flat": "Flat", "confidence": "Confianza", "kelly": "Kelly",
          "elo": "Elo", "bayes": "Bayes", "blend": "Mezcla"}
rank_rows = []
for i, r in enumerate(ranking):
    m = r["metrics"]
    rank_rows.append({
        "#": i + 1,
        "sizing": LABELS[r["sizing"]],
        "criterio": LABELS[r["side_criterion"]],
        "filtro Bayes": "sí" if r["use_bayes_filter"] else "no",
        "yield %": round(m["yield"] * 100, 1),
        "ROI %": round(m["roi"] * 100, 1),
        "apuestas": m["n_bets"],
        "% acierto": round(m["win_rate"] * 100, 1),
        "drawdown": round(m["max_drawdown"], 0),
    })
st.dataframe(pd.DataFrame(rank_rows), use_container_width=True, hide_index=True,
             height=380)

opciones = {f'#{i+1} · {LABELS[r["sizing"]]} + {LABELS[r["side_criterion"]]}'
            f' + filtro {"sí" if r["use_bayes_filter"] else "no"}': i
            for i, r in enumerate(ranking)}
elegida = st.selectbox("Estrategia a fijar", list(opciones), index=0)
idx = opciones[elegida]
win = ranking[idx]
if st.button("📌 Fijar como estrategia activa"):
    with Session(db_engine) as s:
        save_active_strategy(s, win["params"], elegida,
                             yield_=win["metrics"]["yield"],
                             roi=win["metrics"]["roi"])
    st.success(f"Estrategia activa fijada: {elegida} "
               f"(yield {win['metrics']['yield']*100:.1f}%). "
               "La página «Mundial en vivo» la usará.")

# ----------------------------------------------------------------------
# Cuotas reales (Codere + Polymarket) — scrape con caché diario (TTL 24h)
# ----------------------------------------------------------------------
st.subheader("💱 Cuotas reales — Codere vs Polymarket")
st.caption("Scrapea cuotas de partidos próximos del Mundial 2026 y las compara con "
           "la probabilidad del modelo. Bajo demanda, con caché de 24h.")

with Session(db_engine) as s:
    seed_teams(s, FIFA_SNAPSHOT_EXAMPLE)
    wc = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
    last_poly = latest_scrape_iso(s, wc, "polymarket")
    last_cod = latest_scrape_iso(s, wc, "codere")

st.caption(f"Última actualización — Polymarket: {last_poly or '—'} · "
           f"Codere: {last_cod or '—'}")
forzar = st.checkbox("Forzar re-scrape aunque haya datos de <24h")


def _stale(iso: str | None) -> bool:
    if not iso:
        return True
    try:
        return datetime.fromisoformat(iso) < datetime.now() - timedelta(hours=24)
    except ValueError:
        return True


if st.button("💱 Actualizar cuotas (Codere + Polymarket)"):
    if not forzar and not _stale(last_poly) and not _stale(last_cod):
        st.info("Hay cuotas de hace <24h. Marca «Forzar» para re-scrapear.")
    else:
        now_iso = datetime.now().isoformat(timespec="seconds")
        with st.spinner("Scrapeando Polymarket y Codere…"):
            poly = parse_polymarket(fetch_polymarket("World Cup"), now_iso)
            cod = parse_codere(fetch_codere(), now_iso)
            with Session(db_engine) as s:
                wc = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
                n = ingest_odds(s, wc, poly) + ingest_odds(s, wc, cod)
        st.success(f"{len(poly)} cuotas Polymarket + {len(cod)} Codere "
                   f"({n} filas guardadas).")

# Tabla comparativa por próximo partido (de la DB)
with Session(db_engine) as s:
    wc = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
    poly_map = {(o["home"], o["away"]): o for o in latest_odds(s, wc, "polymarket")}
    cod_map = {(o["home"], o["away"]): o for o in latest_odds(s, wc, "codere")}
    calendar = load_calendar(s, wc)

rows = []
for m in calendar:
    if m["status_finished"]:
        continue
    key = (m["home"], m["away"])
    pm, cd = poly_map.get(key), cod_map.get(key)
    rec = pipe.prematch_rec(m["home"], m["away"])
    rows.append({
        "partido": f'{m["home"]} vs {m["away"]}',
        "modelo P(home)": round(rec["p_home"], 3),
        "Poly home": round(pm["home_decimal"], 2) if pm else None,
        "Poly P(home)": round(pm["home_prob"], 3) if pm else None,
        "Codere home": round(cd["home_decimal"], 2) if cd else None,
        "Codere P(home)": round(cd["home_prob"], 3) if cd else None,
        "valor vs Poly": round(rec["p_home"] - pm["home_prob"], 3) if pm else None,
    })
if rows:
    st.caption("«modelo P(home)» usa los ratings actuales del pipeline (entrenado "
               "con Qatar en esta página). «valor» = prob. modelo − prob. implícita.")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                 height=360)
else:
    st.caption("No hay partidos próximos en el calendario (scrapéalo en «Mundial en "
               "vivo») o no hay cuotas todavía.")
