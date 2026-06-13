# Página en vivo en tabs + hub de cuotas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reestructurar la página en vivo en 3 tabs (Calendario / Cuotas / Recomendaciones) con detección de fuente por URL y una acción de "actualizar solo cuotas", y mover el panel de cuotas del Simulador a esa tab.

**Architecture:** `detect_source(url)` puro en `src/odds.py`. La página en vivo se divide en `st.tabs`: Calendario (info), Cuotas (pegar URL + badge + actualizar solo cuotas + tabla Codere/Polymarket/modelo 2026) y Recomendaciones (lado+stake). El Simulador pierde su panel de cuotas.

**Tech Stack:** Python 3.11+, SQLModel/SQLite, Streamlit, pytest.

**Working dir:** Todos los comandos desde `app/`.

---

## File Structure

| Archivo | Responsabilidad |
|---------|-----------------|
| `app/src/odds.py` | + `detect_source(url)` |
| `app/pages/1_🔴_Mundial_en_vivo.py` | 3 tabs + hub de cuotas (pegar URL, actualizar solo cuotas) |
| `app/pages/2_💰_Simulador_Apuestas.py` | quitar el panel "Cuotas reales" y sus imports |
| `app/tests/test_odds.py` | + `detect_source` |

---

## Task 1: `detect_source` en `src/odds.py`

**Files:**
- Modify: `app/src/odds.py`
- Test: `app/tests/test_odds.py`

- [ ] **Step 1: Añadir el test que falla**

Agregar a `app/tests/test_odds.py` (añade `detect_source` al import de `src.odds`):
```python
def test_detect_source():
    from src.odds import detect_source
    assert detect_source("https://www.codere.mx/apuestas/futbol") == "codere"
    assert detect_source("https://polymarket.com/event/world-cup") == "polymarket"
    assert detect_source("https://www.espn.com/soccer") is None
    assert detect_source("") is None
```

- [ ] **Step 2: Correr para verlo fallar**

Run: `uv run pytest tests/test_odds.py::test_detect_source -q`
Expected: FAIL con `ImportError: cannot import name 'detect_source'`.

- [ ] **Step 3: Implementar `detect_source` en `app/src/odds.py`**

Añadir tras `normalize_es` (antes de `_quote`):
```python
def detect_source(url: str) -> str | None:
    """Detecta la fuente de cuotas por dominio: 'codere' | 'polymarket' | None."""
    u = (url or "").lower()
    if "codere" in u:
        return "codere"
    if "polymarket" in u:
        return "polymarket"
    return None
```

- [ ] **Step 4: Correr el test**

Run: `uv run pytest tests/test_odds.py -q`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add src/odds.py tests/test_odds.py
git commit -m "feat: odds.detect_source (codere/polymarket by domain)"
```

---

## Task 2: Página en vivo en 3 tabs + hub de cuotas

**Files:**
- Modify: `app/pages/1_🔴_Mundial_en_vivo.py`

- [ ] **Step 1: Añadir imports (cuotas + datetime)**

Reemplazar el bloque de imports:
```python
from src.ingest import (get_or_create_tournament, seed_teams, ingest_calendar,
                        load_calendar, load_matches)
from src.betting import BetParams, recommend_bet
from src.strategies import load_active_strategy, strategy_to_params
from src.odds_store import latest_odds
from src.scraper import fetch_via_playwright, fetch_via_requests
from ui_common import model_controls, betting_controls
```
por:
```python
from datetime import datetime
from src.ingest import (get_or_create_tournament, seed_teams, ingest_calendar,
                        load_calendar, load_matches)
from src.betting import BetParams, recommend_bet
from src.strategies import load_active_strategy, strategy_to_params
from src.odds import (detect_source, fetch_polymarket, fetch_codere,
                      parse_polymarket, parse_codere)
from src.odds_store import latest_odds, ingest_odds
from src.scraper import fetch_via_playwright, fetch_via_requests
from ui_common import model_controls, betting_controls
```

- [ ] **Step 2: Reemplazar el bloque KPIs + calendario + recomendaciones por 3 tabs**

Reemplazar todo desde `# 4) KPIs rápidos` (la línea `c1, c2, c3 = st.columns(3)` y
lo que sigue) hasta el final del archivo, por:
```python
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
    st.caption("Pega una URL (Codere o Polymarket) y/o ajusta el query de "
               "Polymarket; «Actualizar solo cuotas» busca al instante y guarda "
               "en la DB (independiente del scrape de calendario).")
    url = st.text_input("URL de cuotas (Codere o Polymarket)", key="odds_url")
    src = detect_source(url) if url else None
    if url:
        st.caption(f"Fuente detectada: **{src or 'no reconocida'}**")
    poly_query = st.text_input("Query Polymarket", "World Cup", key="poly_query")
    if st.button("💱 Actualizar solo cuotas"):
        now_iso = datetime.now().isoformat(timespec="seconds")
        n_poly = n_cod = 0
        with st.spinner("Actualizando cuotas…"):
            with Session(db_engine) as s:
                seed_teams(s, FIFA_SNAPSHOT_EXAMPLE)
                wc = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
                n_poly = ingest_odds(s, wc,
                                     parse_polymarket(fetch_polymarket(poly_query), now_iso))
                if src == "codere":
                    n_cod = ingest_odds(s, wc,
                                        parse_codere(fetch_codere(url), now_iso))
        msg = f"Polymarket: {n_poly} cuotas guardadas."
        if src == "codere":
            msg += f" Codere: {n_cod}."
        elif url:
            msg += " (la URL no es de Codere; Codere no se actualizó.)"
        st.success(msg)

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

# ---- Tab Recomendaciones ----
with tab_rec:
    st.caption("🔵 con apuesta `@ cuota` · ⚪ sin apuesta (warm-up / filtro Bayes). "
               f"Fuente de cuotas activa: **{odds_source}**.")
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
```

- [ ] **Step 3: Verificar que compila**

Run: `uv run python -m py_compile "pages/1_🔴_Mundial_en_vivo.py"`
Expected: exit 0.

- [ ] **Step 4: Smoke sin red del flujo de cuotas en vivo**

Run:
```bash
uv run python -c "
from src.odds import detect_source, parse_polymarket, parse_codere
from sqlmodel import Session
from src.db import get_engine, init_db
from src.ingest import seed_teams, get_or_create_tournament
from src.odds_store import ingest_odds, latest_odds
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE
assert detect_source('https://codere.mx/x') == 'codere'
poly = parse_polymarket([{'q':'x','outcomes':'[\"Argentina\",\"France\"]','outcomePrices':'[\"0.6\",\"0.4\"]'}], '2026-06-13T08:00:00')
cod = parse_codere({'events':[{'home':'Argentina','away':'France','odds':{'home':1.9,'draw':3.3,'away':3.8}}]}, '2026-06-13T08:00:00')
eng=get_engine(':memory:'); init_db(eng)
with Session(eng) as s:
    seed_teams(s, FIFA_SNAPSHOT_EXAMPLE)
    t=get_or_create_tournament(s,'World Cup 2026',2026,'live')
    ingest_odds(s,t,poly); ingest_odds(s,t,cod)
    print('poly', latest_odds(s,t,'polymarket')[0]['home_decimal'], '| codere', latest_odds(s,t,'codere')[0]['home_decimal'])
"
```
Expected: imprime las cuotas de ambas fuentes; sin excepciones.

- [ ] **Step 5: Commit**

```bash
git add "pages/1_🔴_Mundial_en_vivo.py"
git commit -m "feat: live page split into Calendario/Cuotas/Recomendaciones tabs + odds hub"
```

---

## Task 3: Quitar el panel de cuotas del Simulador

**Files:**
- Modify: `app/pages/2_💰_Simulador_Apuestas.py`

- [ ] **Step 1: Eliminar los imports que solo usaba el panel de cuotas**

Quitar estas líneas del bloque de imports:
```python
from datetime import datetime, timedelta
from src.ingest import get_or_create_tournament, seed_teams, load_calendar
from src.odds import fetch_polymarket, fetch_codere, parse_polymarket, parse_codere
from src.odds_store import ingest_odds, latest_odds, latest_scrape_iso
```
(El resto de imports se mantiene: `Match, Tournament`, `ingest_qatar_backtest,
load_matches`, `BetParams, simulate, sweep_strategies`, `save_active_strategy`,
`model_controls, betting_controls`.)

- [ ] **Step 2: Eliminar la sección "Cuotas reales"**

Borrar todo desde el comentario:
```python
# ----------------------------------------------------------------------
# Cuotas reales (Codere + Polymarket) — scrape con caché diario (TTL 24h)
# ----------------------------------------------------------------------
```
hasta el final del archivo (incluye el `st.subheader("💱 Cuotas reales…")`,
`_stale`, el botón de actualizar, el bloque `pipe_live` y la tabla comparativa).
El archivo termina ahora tras el bloque del laboratorio (el `st.success(...)` del
botón "📌 Fijar como estrategia activa").

- [ ] **Step 3: Verificar que compila**

Run: `uv run python -m py_compile "pages/2_💰_Simulador_Apuestas.py"`
Expected: exit 0.

- [ ] **Step 4: Suite completa**

Run: `uv run pytest -q`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add "pages/2_💰_Simulador_Apuestas.py"
git commit -m "refactor: move odds panel out of simulator (now lives in live page Cuotas tab)"
```

---

## Task 4: Documentación

**Files:**
- Modify: `app/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Actualizar `app/README.md`**

- En **Mundial en vivo** describir las 3 tabs (Calendario / Cuotas / Recomendaciones),
  el campo de pegar URL con detección de fuente y el botón "Actualizar solo cuotas".
- En **Simulador** quitar la mención al panel "Cuotas reales" (ahora vive en la
  tab de Cuotas de la página en vivo).

- [ ] **Step 2: Actualizar `CLAUDE.md`**

- En `src/odds.py` añadir `detect_source` a las firmas.
- Ajustar la nota de cuotas: "El hub de cuotas (pegar URL con `detect_source`,
  actualizar solo cuotas, comparar Codere/Polymarket vs modelo 2026) vive en la tab
  **Cuotas** de la página en vivo; la página en vivo está en 3 tabs (Calendario /
  Cuotas / Recomendaciones)."

- [ ] **Step 3: Suite completa final**

Run: `uv run pytest -q`
Expected: PASS (todos).

- [ ] **Step 4: Commit**

```bash
git add ../CLAUDE.md README.md
git commit -m "docs: live page tabs + odds hub; simulator no longer hosts odds panel"
```

---

## Notas de verificación final

- `uv run pytest -q` verde (incluye `detect_source`).
- `py_compile` OK en ambas páginas.
- La página en vivo tiene 3 tabs; "Actualizar solo cuotas" no toca el calendario.
- El Simulador ya no importa `odds`/`odds_store`/`datetime`; sin panel de cuotas.
- `detect_source` puro y testeado; fetchers siguen best-effort.
