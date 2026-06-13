"""
Mundial en vivo: scrapea ESPN, guarda el calendario completo en la DB, lo muestra
como vista tipo calendario y recomienda lado + stake por partido programado.

El modelo se entrena con los partidos ya finalizados (de la DB). Los parámetros
se heredan del Backtest (mismos controles compartidos en session_state).
"""
from __future__ import annotations
import pandas as pd
import streamlit as st
from sqlmodel import Session, select

from src.pipeline import Pipeline
from src.elo import EloSystem
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE
from src.db import get_engine, init_db
from src.models import Tournament
from datetime import datetime
from src.ingest import (get_or_create_tournament, seed_teams, ingest_calendar,
                        load_calendar, load_matches)
from src.betting import BetParams, recommend_bet
from src.strategies import load_active_strategy, strategy_to_params
from src.odds import (detect_source, fetch_polymarket, fetch_codere,
                      parse_polymarket, parse_codere, select_markets, OddsQuote)
from src.odds_store import latest_odds, ingest_odds
from src.scraper import fetch_via_playwright, fetch_via_requests
from ui_common import model_controls, betting_controls

st.set_page_config(page_title="Mundial en vivo", layout="wide")
st.title("🔴 Mundial en vivo — calendario y recomendaciones")
st.caption("Scrapea ESPN, guarda el calendario en la DB y sugiere a quién apostar "
           "y cuánto en los partidos programados. Backtest educativo, no consejo real.")

with st.expander("ℹ️ ¿Cómo funciona?", expanded=False):
    st.markdown("""
1. **Actualizar** scrapea ESPN para el rango de fechas y guarda **todos** los
   partidos (finalizados + programados) en la base de datos.
2. El modelo Elo/Bayes se entrena con los **finalizados** y, para cada partido
   **programado**, se recomienda lado + stake según la estrategia (sizing).
3. Los parámetros (K, prior, cuota, criterio, umbral) se heredan del **Backtest**.
""")

# Controles compartidos (mismos que Backtest) + sizing por botones + scrape
k_factor, prior_strength, use_margin = model_controls()
common = betting_controls()

st.sidebar.header("Estrategia (sizing)")
if "live_sizing" not in st.session_state:
    st.session_state["live_sizing"] = "kelly"
b1, b2, b3 = st.sidebar.columns(3)
if b1.button("Flat"):
    st.session_state["live_sizing"] = "flat"
if b2.button("Confianza"):
    st.session_state["live_sizing"] = "confidence"
if b3.button("Kelly"):
    st.session_state["live_sizing"] = "kelly"
sizing = st.session_state["live_sizing"]
use_filter = st.sidebar.checkbox("Filtrar por umbral de Bayes", value=False,
                                 key="live_use_filter")
st.sidebar.caption(f"Sizing activo: **{sizing}**")
st.sidebar.caption("⚠️ Si hay una **estrategia activa** fijada en el Simulador, "
                   "ésta tiene prioridad y estos botones se ignoran.")
override_active = st.sidebar.checkbox(
    "Ignorar estrategia activa (override manual)", value=False,
    key="live_override")

# La fuente de cuotas se elige en la tab 💱 Cuotas (no en el sidebar): se ve
# junto a la comparativa y se recuerda en session_state.
st.session_state.setdefault("live_odds_source", "polymarket")

st.sidebar.header("Scrape ESPN")
date_range = st.sidebar.text_input("Rango de fechas", "20260611-20260710",
                                   key="live_date_range")
scraper_engine = st.sidebar.selectbox("Scraper", ["Playwright", "requests (fallback)"],
                                      key="live_scraper")
run_scrape = st.sidebar.button("Actualizar (scrape ESPN)")


@st.cache_resource
def get_db():
    eng = get_engine()
    init_db(eng)
    return eng


db_engine = get_db()

# 1) Scrape -> persistir TODO el calendario en la DB
if run_scrape:
    fn = fetch_via_playwright if scraper_engine == "Playwright" else fetch_via_requests
    with st.spinner("Scrapeando ESPN…"):
        results = fn(date_range, league="fifa.world")
        with Session(db_engine) as s:
            seed_teams(s, FIFA_SNAPSHOT_EXAMPLE)
            t = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
            n = ingest_calendar(s, t, results)
    st.success(f"{len(results)} partidos scrapeados, {n} nuevos guardados en la DB.")

# 2) Leer calendario + finalizados de la DB (las cuotas se leen por tab)
with Session(db_engine) as s:
    t = s.exec(select(Tournament).where(Tournament.name == "World Cup 2026")).first()
    calendar = load_calendar(s, t) if t else []
    finished = load_matches(s, t) if t else []

if not calendar:
    st.info("La DB no tiene calendario aún. Pulsa «Actualizar (scrape ESPN)» "
            "con un rango de fechas del torneo.")
    st.stop()

# 3) Entrenar el modelo con los finalizados
pipe = Pipeline(elo=EloSystem(k=k_factor, use_margin=use_margin))
pipe.seed(FIFA_SNAPSHOT_EXAMPLE)
pipe.bayes.seed_from_elo(pipe.initial_elo, strength=prior_strength)
pipe.process_all(finished)

# Estrategia activa de la DB (salvo override manual).
with Session(db_engine) as s:
    active = load_active_strategy(s)
if active is not None and not override_active:
    params = strategy_to_params(active)
    yld = f"{active.backtest_yield*100:.1f}%" if active.backtest_yield is not None else "n/d"
    st.success(f"📌 Estrategia activa: **{active.label}** "
               f"(sizing {active.sizing} · criterio {active.side_criterion} · "
               f"filtro {'sí' if active.use_bayes_filter else 'no'} · yield Qatar {yld}). "
               "Marca «Ignorar estrategia activa» para usar los controles de la izquierda.")
else:
    params = BetParams(sizing=sizing, use_bayes_filter=use_filter, **common)
    if active is not None:
        st.info("Override manual activo: usando sizing/criterio de la barra lateral "
                "(ignorando la estrategia activa).")
    else:
        st.info("No hay estrategia activa fijada. Usando los controles de la barra "
                "lateral. Ve al «Simulador» para barrer y fijar la mejor.")

# 4) Tres tabs: Calendario (info) · Cuotas (Codere+Polymarket) · Recomendaciones
tab_cal, tab_odds, tab_rec = st.tabs(
    ["📅 Calendario", "💱 Cuotas", "🎯 Recomendaciones"])

# ---- Tab Calendario (solo info) ----
with tab_cal:
    c1, c2, c3 = st.columns(3)
    c1.metric("Partidos en calendario", len(calendar))
    c2.metric("Finalizados", len(finished))
    c3.metric("Programados", len(calendar) - len(finished))
    st.caption("✅ finalizado (con marcador) · 🗓️ programado.")
    by_date: dict[str, list[dict]] = {}
    for m in calendar:
        by_date.setdefault(m["date"], []).append(m)
    for date in sorted(by_date):
        st.markdown(f"#### {date}")
        for m in by_date[date]:
            if m["status_finished"]:
                st.markdown(f"✅ **{m['home']} {m['home_goals']}-{m['away_goals']} "
                            f"{m['away']}** · {m['stage']}")
            else:
                st.markdown(f"🗓️ {m['home']} vs {m['away']} · {m['stage']}")

# ---- Tab Cuotas (hub Codere + Polymarket) ----
with tab_odds:
    st.caption("Flujo en 2 pasos: **buscar** mercados (query + filtro regex) → "
               "revisar el preview y **marcar** cuáles guardar → **guardar**. "
               "El guardado es independiente del scrape de calendario.")

    # Partidos del calendario (para marcar qué mercado casa con un fixture).
    cal_keys = {(m["home"], m["away"]) for m in calendar if not m["status_finished"]}

    # ---- Paso 1: buscar mercados de Polymarket (query + regex) ----
    st.markdown("**Polymarket**")
    pq1, pq2 = st.columns(2)
    poly_query = pq1.text_input("Query (search de la API)", "World Cup",
                                key="poly_query")
    poly_regex = pq2.text_input("Filtro regex (opcional, client-side)", "",
                                key="poly_regex",
                                help="Ej: `argentina|mexico|brazil` o `vs`. "
                                     "Filtra los mercados traídos por question/slug.")
    if st.button("🔎 Buscar mercados Polymarket"):
        now_iso = datetime.now().isoformat(timespec="seconds")
        with st.spinner("Buscando en Polymarket…"):
            raw = fetch_polymarket(poly_query)
            sel = select_markets(raw, poly_regex or None)
            quotes = parse_polymarket(sel, now_iso)
        st.session_state["poly_preview"] = [vars(q) for q in quotes]
        st.session_state["poly_fetched_at"] = now_iso
        st.caption(f"{len(raw)} mercados crudos · {len(sel)} tras regex · "
                   f"{len(quotes)} parseados como partido.")

    # ---- Paso 2: preview + marcar cuáles guardar ----
    preview = st.session_state.get("poly_preview", [])
    if preview:
        df = pd.DataFrame([{
            "guardar": (q["home"], q["away"]) in cal_keys,   # default: solo los que casan
            "partido": f'{q["home"]} vs {q["away"]}',
            "cuota home": round(q["home_decimal"], 2),
            "cuota away": round(q["away_decimal"], 2),
            "P(home)": round(q["home_prob"], 3),
            "✅ calendario": (q["home"], q["away"]) in cal_keys,
        } for q in preview])
        edited = st.data_editor(
            df, key="poly_editor", use_container_width=True, hide_index=True,
            height=320,
            column_order=["guardar", "partido", "cuota home", "cuota away",
                          "P(home)", "✅ calendario"],
            disabled=["partido", "cuota home", "cuota away", "P(home)",
                      "✅ calendario"])
        st.caption("Marca «guardar» en los mercados que quieras ingestar "
                   "(por defecto solo los que casan con el calendario).")
        if st.button("💾 Guardar cuotas seleccionadas"):
            chosen = [preview[i] for i, v in enumerate(edited["guardar"]) if v]
            quotes = [OddsQuote(**d) for d in chosen]
            with Session(db_engine) as s:
                wc = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
                n = ingest_odds(s, wc, quotes)
            st.success(f"{n} cuotas de Polymarket guardadas en la DB.")

    # ---- Codere (de la URL pegada) ----
    st.markdown("**Codere**")
    url = st.text_input("URL de Codere", key="odds_url")
    src = detect_source(url) if url else None
    if url:
        st.caption(f"Fuente detectada: **{src or 'no reconocida'}**")
    if st.button("💱 Actualizar Codere (de la URL)", disabled=(src != "codere")):
        now_iso = datetime.now().isoformat(timespec="seconds")
        with st.spinner("Scrapeando Codere…"):
            with Session(db_engine) as s:
                wc = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
                n_cod = ingest_odds(s, wc, parse_codere(fetch_codere(url), now_iso))
        st.success(f"Codere: {n_cod} cuotas guardadas.")

    st.divider()
    st.markdown("**Comparativa (última cuota guardada por fuente vs modelo)**")
    with Session(db_engine) as s:
        wc = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
        poly_map = {(o["home"], o["away"]): o for o in latest_odds(s, wc, "polymarket")}
        cod_map = {(o["home"], o["away"]): o for o in latest_odds(s, wc, "codere")}
    odds_rows = []
    for m in calendar:
        if m["status_finished"]:
            continue
        key = (m["home"], m["away"])
        pm, cd = poly_map.get(key), cod_map.get(key)
        rec = pipe.prematch_rec(m["home"], m["away"])
        odds_rows.append({
            "partido": f'{m["home"]} vs {m["away"]}',
            "modelo P(home)": round(rec["p_home"], 3),
            "Poly home": round(pm["home_decimal"], 2) if pm else None,
            "Poly P(home)": round(pm["home_prob"], 3) if pm else None,
            "Codere home": round(cd["home_decimal"], 2) if cd else None,
            "Codere P(home)": round(cd["home_prob"], 3) if cd else None,
            "valor vs Poly": round(rec["p_home"] - pm["home_prob"], 3) if pm else None,
        })
    if odds_rows:
        st.caption("«modelo P(home)» usa el pipe entrenado con finalizados 2026. "
                   "«valor» = prob. modelo − prob. implícita de Polymarket.")
        st.dataframe(pd.DataFrame(odds_rows), use_container_width=True,
                     hide_index=True, height=360)
    else:
        st.caption("No hay partidos próximos en el calendario o no hay cuotas todavía.")

    st.divider()
    st.selectbox(
        "Fuente de cuotas para las recomendaciones",
        ["polymarket", "codere", "cuota fija"], key="live_odds_source",
        help="«cuota fija» usa la cuota decimal de la barra lateral; "
             "las otras dos usan la cuota real de la fuente elegida.")
    st.caption("La tab 🎯 Recomendaciones usará esta fuente.")

# ---- Tab Recomendaciones ----
with tab_rec:
    odds_source = st.session_state.get("live_odds_source", "polymarket")
    odds_map: dict = {}
    if odds_source != "cuota fija":
        with Session(db_engine) as s:
            wc = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
            odds_map = {(o["home"], o["away"]): o
                        for o in latest_odds(s, wc, odds_source)}
    st.caption("🔵 con apuesta `@ cuota` · ⚪ sin apuesta (warm-up / filtro Bayes). "
               f"Fuente de cuotas activa: **{odds_source}** (se elige en 💱 Cuotas).")
    rows = []
    for m in calendar:
        if m["status_finished"]:
            continue
        o = odds_map.get((m["home"], m["away"]))
        mo = {"home": o["home_decimal"], "away": o["away_decimal"]} if o else None
        r = recommend_bet(pipe.prematch_rec(m["home"], m["away"]),
                          float(common["bankroll0"]), params, match_odds=mo)
        if r["bet"]:
            st.markdown(f"🔵 {m['home']} vs {m['away']} · {m['stage']} → "
                        f"**Apostar: {r['pick']}** · stake **{r['stake']:.0f}** "
                        f"@ cuota {r['odds']:.2f} "
                        f"(p={r['p_pick']:.2f}, Bayes={r['bayes_pick']:.2f})")
        else:
            motivo = "warm-up" if r["skip_warmup"] else "filtro Bayes"
            st.markdown(f"⚪ {m['home']} vs {m['away']} · {m['stage']} → "
                        f"— sin apuesta ({motivo})")
        rows.append({"fecha": m["date"], "partido": f"{m['home']} vs {m['away']}",
                     "lado": r["pick"] if r["bet"] else "—",
                     "stake": round(r["stake"], 2), "cuota": round(r["odds"], 2),
                     "p_elo": round(r["p_pick"], 3), "bayes": round(r["bayes_pick"], 3),
                     "apuesta": "sí" if r["bet"] else "no"})
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, height=360)
    else:
        st.caption("No hay partidos programados en el calendario actual.")
