# Split en páginas (Backtest / Mundial en vivo) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dividir la app en páginas (Backtest / Mundial en vivo / Simulador), guardar todo el calendario en la DB, y recomendar lado + stake por partido programado con parámetros compartidos entre páginas.

**Architecture:** La DB guarda finalizados y programados (calendario); `ingest_calendar` hace upsert. Funciones puras nuevas (`Pipeline.prematch_rec`, `betting.recommend_bet`) producen recomendaciones por partido próximo reusando `pick_side`/`stake_amount`. Un módulo de UI compartida (`app/ui_common.py`) centraliza los controles en `session_state` para concordancia entre páginas. `app.py` queda como Backtest; una página nueva hace el flujo en vivo leyendo de la DB.

**Tech Stack:** Python 3.11+, SQLModel/SQLite, Streamlit multipage + Altair, pytest.

**Working dir:** Todos los comandos desde `app/`.

---

## File Structure

| Archivo | Responsabilidad |
|---------|-----------------|
| `app/src/models.py` | `Match.home_goals`/`away_goals` pasan a `int \| None` (programados sin marcador) |
| `app/src/ingest.py` | + `ingest_calendar` (persiste todos), `load_calendar` (todos); `load_matches` filtra finalizados |
| `app/src/pipeline.py` | + `prematch_rec(home, away)` |
| `app/src/betting.py` | + `recommend_bet(rec, bankroll, params)` |
| `app/ui_common.py` | NUEVO — `model_controls()`, `betting_controls()` (widgets con `key=`) |
| `app/app.py` | Pasa a solo Backtest (Qatar); usa `ui_common` |
| `app/pages/1_🔴_Mundial_en_vivo.py` | NUEVO — scrape→DB, calendario, recomendaciones |
| `app/pages/2_💰_Simulador_Apuestas.py` | Realineado a `ui_common` |
| `app/tests/test_*` | Tests de ingest_calendar/load_calendar, prematch_rec, recommend_bet |

---

## Task 1: `Match` con goles nullable + `ingest_calendar` / `load_calendar`

**Files:**
- Modify: `app/src/models.py`
- Modify: `app/src/ingest.py`
- Test: `app/tests/test_ingest.py`

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `app/tests/test_ingest.py`:
```python
SAMPLE_CALENDAR = {
    "events": [
        {
            "id": "501", "date": "2026-06-11T18:00Z",
            "competitions": [{
                "status": {"type": {"name": "STATUS_FULL_TIME"}},
                "notes": [{"headline": "Group A"}],
                "competitors": [
                    {"homeAway": "home", "score": "3", "team": {"displayName": "Mexico"}},
                    {"homeAway": "away", "score": "0", "team": {"displayName": "Canada"}},
                ],
            }],
        },
        {
            "id": "502", "date": "2026-06-12T18:00Z",
            "competitions": [{
                "status": {"type": {"name": "STATUS_SCHEDULED"}},
                "notes": [{"headline": "Group A"}],
                "competitors": [
                    {"homeAway": "home", "score": "0", "team": {"displayName": "Argentina"}},
                    {"homeAway": "away", "score": "0", "team": {"displayName": "Mexico"}},
                ],
            }],
        },
    ]
}


def test_ingest_calendar_persists_all_and_load_splits():
    from src.ingest import ingest_calendar, load_calendar
    s = make_session()
    t = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
    results = parse_scoreboard_json(SAMPLE_CALENDAR)
    ingest_calendar(s, t, results)

    cal = load_calendar(s, t)                 # todos (2)
    assert len(cal) == 2
    assert {c["status_finished"] for c in cal} == {True, False}

    finished = load_matches(s, t)             # solo finalizados (1)
    assert len(finished) == 1
    assert finished[0][2] == "Mexico" and finished[0][3] == "Canada"


def test_ingest_calendar_updates_scheduled_to_finished():
    from src.ingest import ingest_calendar, load_calendar
    s = make_session()
    t = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
    ingest_calendar(s, t, parse_scoreboard_json(SAMPLE_CALENDAR))
    # el evento 502 (Argentina vs Mexico) ahora termina 2-1
    SAMPLE_CALENDAR["events"][1]["competitions"][0]["status"]["type"]["name"] = "STATUS_FULL_TIME"
    SAMPLE_CALENDAR["events"][1]["competitions"][0]["competitors"][0]["score"] = "2"
    SAMPLE_CALENDAR["events"][1]["competitions"][0]["competitors"][1]["score"] = "1"
    ingest_calendar(s, t, parse_scoreboard_json(SAMPLE_CALENDAR))

    cal = load_calendar(s, t)
    assert len(cal) == 2                       # sin duplicar (dedup event_id)
    assert len(load_matches(s, t)) == 2        # ahora ambos finalizados
    # restaurar el payload para no afectar otros tests
    SAMPLE_CALENDAR["events"][1]["competitions"][0]["status"]["type"]["name"] = "STATUS_SCHEDULED"
```

- [ ] **Step 2: Correr para verlo fallar**

Run: `uv run pytest tests/test_ingest.py -k "calendar" -q`
Expected: FAIL con `ImportError: cannot import name 'ingest_calendar'`.

- [ ] **Step 3: Hacer nullable los goles en `app/src/models.py`**

Cambiar las dos líneas de `Match`:
```python
    home_goals: int | None = None
    away_goals: int | None = None
```
(Las demás líneas de `Match` quedan igual.)

- [ ] **Step 4: Añadir `ingest_calendar` y `load_calendar` en `app/src/ingest.py`**

`ingest_matches` ya hace upsert por `espn_event_id` y actualiza goles/status, así
que `ingest_calendar` solo persiste todos los resultados (sin filtrar finalizados):
```python
def ingest_calendar(session: Session, tournament: Tournament,
                    results: list[MatchResult]) -> int:
    """Persiste TODOS los partidos (finalizados + programados). Upsert por event_id."""
    return ingest_matches(session, tournament, results, source="espn")
```

Hacer que `load_matches` devuelva **solo finalizados** (filtra por status). Reemplazar
la función `load_matches` existente por:
```python
def load_matches(session: Session, tournament: Tournament) -> list[tuple]:
    """Tuplas (date, stage, home, away, hg, ag) de partidos FINALIZADOS, por fecha."""
    from .models import FINISHED_STATUSES
    names = {t.id: t.name for t in session.exec(select(Team)).all()}
    rows = session.exec(select(Match).where(
        Match.tournament_id == tournament.id,
        Match.status.in_(FINISHED_STATUSES))).all()
    out = [(m.date, m.stage, names[m.home_team_id], names[m.away_team_id],
            m.home_goals, m.away_goals) for m in rows]
    return sorted(out, key=lambda x: x[0])


def load_calendar(session: Session, tournament: Tournament) -> list[dict]:
    """Todos los partidos (calendario) ordenados por fecha, con status y goles."""
    from .models import FINISHED_STATUSES
    names = {t.id: t.name for t in session.exec(select(Team)).all()}
    rows = session.exec(select(Match).where(
        Match.tournament_id == tournament.id)).all()
    out = [{
        "date": m.date, "stage": m.stage,
        "home": names[m.home_team_id], "away": names[m.away_team_id],
        "home_goals": m.home_goals, "away_goals": m.away_goals,
        "status": m.status, "status_finished": m.status in FINISHED_STATUSES,
    } for m in rows]
    return sorted(out, key=lambda r: r["date"])
```

- [ ] **Step 5: Correr los tests**

Run: `uv run pytest tests/test_ingest.py -q`
Expected: PASS (todos: los previos + los 2 nuevos de calendario).

- [ ] **Step 6: Commit**

```bash
git add src/models.py src/ingest.py tests/test_ingest.py
git commit -m "feat: persist full calendar in DB (ingest_calendar/load_calendar, nullable goals)"
```

---

## Task 2: `Pipeline.prematch_rec`

**Files:**
- Modify: `app/src/pipeline.py`
- Test: `app/tests/test_pipeline.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir al final de `app/tests/test_pipeline.py`:
```python
def test_prematch_rec_uses_current_state():
    p = Pipeline()
    p.seed(FIFA_SNAPSHOT_EXAMPLE)
    p.process_all(QATAR_2022_SAMPLE)
    # Argentina jugó 6 -> su próximo sería el nº 7
    rec = p.prematch_rec("Argentina", "France")
    assert rec["home"] == "Argentina" and rec["away"] == "France"
    assert 0.0 < rec["p_home"] < 1.0
    assert 0.0 <= rec["bayes_home"] <= 1.0 and 0.0 <= rec["bayes_away"] <= 1.0
    assert rec["home_match_no"] == 7
    # equipo que no jugó -> match_no 1
    rec2 = p.prematch_rec("Atlantis", "France")
    assert rec2["home_match_no"] == 1
```

- [ ] **Step 2: Correr para verlo fallar**

Run: `uv run pytest tests/test_pipeline.py::test_prematch_rec_uses_current_state -q`
Expected: FAIL con `AttributeError: 'Pipeline' object has no attribute 'prematch_rec'`.

- [ ] **Step 3: Implementar `prematch_rec` en `app/src/pipeline.py`**

Añadir como método de `Pipeline` (p. ej. tras `team_evolution`):
```python
    def prematch_rec(self, home: str, away: str) -> dict:
        """Foto pre-partido para un juego hipotético con el estado ACTUAL,
        sin actualizar Elo/Bayes. Mismo formato que match_log (sin resultado)."""
        return {
            "home": home, "away": away,
            "p_home": expected_score(self.elo.get(home), self.elo.get(away)),
            "bayes_home": self.bayes.get(home).mean,
            "bayes_away": self.bayes.get(away).mean,
            "home_match_no": self._appearances.get(home, 0) + 1,
            "away_match_no": self._appearances.get(away, 0) + 1,
        }
```

- [ ] **Step 4: Correr el test**

Run: `uv run pytest tests/test_pipeline.py -q`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add src/pipeline.py tests/test_pipeline.py
git commit -m "feat: Pipeline.prematch_rec for hypothetical upcoming matches"
```

---

## Task 3: `betting.recommend_bet`

**Files:**
- Modify: `app/src/betting.py`
- Test: `app/tests/test_betting.py`

- [ ] **Step 1: Añadir los tests que fallan**

Agregar a `app/tests/test_betting.py` (reusa el helper `rec` ya existente, que
incluye `home_match_no`/`away_match_no`):
```python
def prec(home="A", away="B", p_home=0.7, bayes_home=0.6, bayes_away=0.4,
         home_match_no=2, away_match_no=2):
    """rec pre-partido (sin resultado) para recommend_bet."""
    return {"home": home, "away": away, "p_home": p_home,
            "bayes_home": bayes_home, "bayes_away": bayes_away,
            "home_match_no": home_match_no, "away_match_no": away_match_no}


def test_recommend_bet_places_bet():
    p = BetParams(sizing="flat", base_fraction=0.10, start_match_no=2,
                  side_criterion="elo")
    out = recommend_bet(prec(p_home=0.7), 1000.0, p)
    assert out["bet"] is True
    assert out["side"] == "home" and out["pick"] == "A"
    assert abs(out["stake"] - 100.0) < 1e-9
    assert out["skip_warmup"] is False and out["filtered_out"] is False


def test_recommend_bet_skips_warmup():
    p = BetParams(sizing="flat", base_fraction=0.10, start_match_no=2)
    out = recommend_bet(prec(p_home=0.7, home_match_no=1, away_match_no=1),
                        1000.0, p)
    assert out["skip_warmup"] is True
    assert out["bet"] is False and out["stake"] == 0.0


def test_recommend_bet_bayes_filter():
    p = BetParams(sizing="flat", base_fraction=0.10, start_match_no=2,
                  side_criterion="elo", use_bayes_filter=True, bayes_threshold=0.5)
    out = recommend_bet(prec(p_home=0.7, bayes_home=0.40), 1000.0, p)
    assert out["filtered_out"] is True and out["bet"] is False


def test_recommend_bet_stake_capped_by_bankroll():
    p = BetParams(sizing="flat", base_fraction=2.0, start_match_no=2)
    out = recommend_bet(prec(p_home=0.7), 100.0, p)
    assert abs(out["stake"] - 100.0) < 1e-9  # no excede el bankroll
```

- [ ] **Step 2: Correr para verlo fallar**

Run: `uv run pytest tests/test_betting.py -k recommend -q`
Expected: FAIL (`recommend_bet` no definido).

- [ ] **Step 3: Implementar `recommend_bet` en `app/src/betting.py`**

Añadir al final del módulo:
```python
def recommend_bet(rec: dict, bankroll: float, params: BetParams) -> dict:
    """Recomendación para UN partido próximo (rec sin resultado).
    Aplica pick_side + filtros (warm-up, umbral Bayes) + stake_amount."""
    side, p_pick, bayes_pick, match_no = pick_side(
        rec, params.side_criterion, params.blend_weight)
    skip_warmup = match_no < params.start_match_no
    filtered_out = params.use_bayes_filter and bayes_pick < params.bayes_threshold
    if skip_warmup or filtered_out:
        stake = 0.0
    else:
        stake = min(stake_amount(params, bankroll, p_pick), bankroll)
    return {
        "side": side, "pick": rec[side],
        "p_pick": p_pick, "bayes_pick": bayes_pick, "match_no": match_no,
        "stake": stake,
        "skip_warmup": skip_warmup, "filtered_out": filtered_out,
        "bet": stake > 0,
    }
```

- [ ] **Step 4: Correr los tests**

Run: `uv run pytest tests/test_betting.py -q`
Expected: PASS (los previos + 4 nuevos).

- [ ] **Step 5: Commit**

```bash
git add src/betting.py tests/test_betting.py
git commit -m "feat: betting.recommend_bet for a single upcoming match"
```

---

## Task 4: UI compartida `app/ui_common.py`

**Files:**
- Create: `app/ui_common.py`

- [ ] **Step 1: Crear `app/ui_common.py`**

```python
"""
Controles de barra lateral compartidos por las páginas (Backtest, En vivo,
Simulador). Como st.session_state es compartido entre páginas, usar el mismo
`key` en cada widget mantiene los parámetros CONCORDANTES al navegar.
"""
from __future__ import annotations
import streamlit as st


def model_controls() -> tuple[float, float, bool]:
    """Sidebar 'Modelo': K, fuerza del prior Bayes, multiplicador por margen."""
    st.sidebar.header("Modelo")
    k = st.sidebar.slider("Factor K (Elo)", 10, 80, 40, 5, key="k_factor")
    prior = st.sidebar.slider("Fuerza del prior Bayes", 1.0, 12.0, 4.0, 1.0,
                              key="prior_strength")
    margin = st.sidebar.checkbox("Multiplicador por margen de gol", value=True,
                                 key="use_margin")
    return float(k), float(prior), bool(margin)


def betting_controls() -> dict:
    """Sidebar 'Apuestas': params compartidos (sin 'sizing' ni filtro Bayes).
    Devuelve un dict listo para BetParams(**common, sizing=..., use_bayes_filter=...)."""
    st.sidebar.header("Apuestas")
    bankroll0 = st.sidebar.number_input("Bankroll inicial", 100.0, 1_000_000.0,
                                        1000.0, 100.0, key="bankroll0")
    odds = st.sidebar.number_input("Cuota decimal fija", 1.01, 10.0, 2.0, 0.05,
                                   key="odds")
    start_match_no = st.sidebar.slider("Apostar desde la jornada", 1, 5, 2,
                                       key="start_match_no")
    base_fraction = st.sidebar.slider("Fracción base del bankroll", 0.01, 0.50,
                                      0.05, 0.01, key="base_fraction")
    kelly_fraction = st.sidebar.slider("Fracción de Kelly", 0.05, 1.0, 0.25, 0.05,
                                       key="kelly_fraction")
    side_criterion = st.sidebar.selectbox(
        "Criterio para elegir el lado", ["elo", "bayes", "blend"],
        format_func={"elo": "Elo (favorito)", "bayes": "Mayor media Bayes",
                     "blend": "Mezcla Elo/Bayes"}.get, key="side_criterion")
    blend_weight = st.sidebar.slider("Peso de Elo en la mezcla (blend)", 0.0, 1.0,
                                     0.5, 0.05, key="blend_weight")
    bayes_threshold = st.sidebar.slider("Umbral de Bayes (filtro)", 0.30, 0.80,
                                        0.50, 0.01, key="bayes_threshold")
    return dict(bankroll0=float(bankroll0), odds=float(odds),
                start_match_no=int(start_match_no),
                base_fraction=float(base_fraction),
                kelly_fraction=float(kelly_fraction),
                side_criterion=side_criterion, blend_weight=float(blend_weight),
                bayes_threshold=float(bayes_threshold))
```

- [ ] **Step 2: Verificar que compila**

Run: `uv run python -m py_compile ui_common.py`
Expected: sin salida (exit 0).

- [ ] **Step 3: Commit**

```bash
git add ui_common.py
git commit -m "feat: shared sidebar controls (ui_common) synced via session_state"
```

---

## Task 5: `app.py` → solo Backtest

**Files:**
- Modify: `app/app.py`

- [ ] **Step 1: Reescribir la cabecera, sidebar y carga de datos**

Reemplazar el docstring + imports + bloque de sidebar + carga de partidos
(desde el inicio del archivo hasta justo antes de `# Ejecutar pipeline`) por:
```python
"""
Página Backtest del sistema Elo + Bayes del Mundial (Qatar 2022, offline).

Vistas: tabla combinada, evolución de Elo, distribución bayesiana, calibración
y evolución combinada Elo+Bayes. La página "Mundial en vivo" y el "Simulador de
apuestas" están en pages/.
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
from src.ingest import ingest_qatar_backtest, load_matches
from ui_common import model_controls

st.set_page_config(page_title="Backtest — Mundial Elo+Bayes", layout="wide")

st.markdown("""
<style>
  .stApp { background:#0F1117; }
  h1,h2,h3 { color:#22D3EE; }
</style>
""", unsafe_allow_html=True)

st.title("📊 Backtest — Mundial (Qatar 2022)")

with st.expander("ℹ️ ¿Cómo funciona este monitor?", expanded=False):
    st.markdown(\"\"\"
El sistema procesa los partidos **en orden** y mantiene dos modelos en paralelo:

1. **Semilla FIFA → Elo.** El ranking FIFA se re-centra a la escala Elo (~1500).
2. **Elo por partido.** `R' = R + K·(S − E)`; **K** controla la reactividad.
3. **Bayes (Beta-Bernoulli).** Fuerza latente con media + intervalo de credibilidad.
4. **Calibración.** Prob. pre-partido vs resultado (Brier, LogLoss, fiabilidad).
\"\"\")

# Parámetros del modelo (compartidos entre páginas vía session_state)
k_factor, prior_strength, use_margin = model_controls()
fifa_points = FIFA_SNAPSHOT_EXAMPLE


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
```

El bloque `# Ejecutar pipeline` y todo lo de KPIs/tabs se mantiene **igual** que
ahora (ya usa `k_factor`, `prior_strength`, `use_margin`, `fifa_points`).

- [ ] **Step 2: Verificar que compila y los imports resuelven**

Run: `uv run python -m py_compile app.py`
Expected: exit 0.

- [ ] **Step 3: Smoke del flujo backtest (sin Streamlit)**

Run:
```bash
uv run python -c "
from sqlmodel import Session, select
from src.db import get_engine, init_db
from src.ingest import ingest_qatar_backtest, load_matches
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE
from src.pipeline import Pipeline
from src.elo import EloSystem
eng = get_engine(':memory:'); init_db(eng)
with Session(eng) as s:
    t = ingest_qatar_backtest(s, prefer_scrape=False)
    m = load_matches(s, t)
p = Pipeline(elo=EloSystem(k=40.0)); p.seed(FIFA_SNAPSHOT_EXAMPLE)
p.process_all(m)
print('backtest partidos:', len(m), 'lider:', p.combined_leaderboard()[0]['team'])
assert len(m) == 48
"
```
Expected: imprime 48 partidos y un líder; sin excepciones.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "refactor: app.py becomes Backtest-only page using shared controls"
```

---

## Task 6: Página `pages/1_🔴_Mundial_en_vivo.py`

**Files:**
- Create: `app/pages/1_🔴_Mundial_en_vivo.py`

- [ ] **Step 1: Crear la página**

```python
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
from src.ingest import (get_or_create_tournament, seed_teams, ingest_calendar,
                        load_calendar, load_matches)
from src.betting import BetParams, recommend_bet
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

# 2) Leer calendario + finalizados de la DB
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

params = BetParams(sizing=sizing, use_bayes_filter=use_filter, **common)

# 4) KPIs rápidos
c1, c2, c3 = st.columns(3)
c1.metric("Partidos en calendario", len(calendar))
c2.metric("Finalizados", len(finished))
c3.metric("Programados", len(calendar) - len(finished))

# 5) Vista tipo calendario (agrupada por fecha)
st.subheader("📅 Calendario")
by_date: dict[str, list[dict]] = {}
for m in calendar:
    by_date.setdefault(m["date"], []).append(m)

for date in sorted(by_date):
    st.markdown(f"#### {date}")
    for m in by_date[date]:
        if m["status_finished"]:
            st.markdown(
                f"✅ **{m['home']} {m['home_goals']}-{m['away_goals']} {m['away']}** "
                f"· {m['stage']}")
        else:
            r = recommend_bet(pipe.prematch_rec(m["home"], m["away"]),
                              float(common["bankroll0"]), params)
            if r["bet"]:
                st.markdown(
                    f"🔵 {m['home']} vs {m['away']} · {m['stage']} → "
                    f"**Apostar: {r['pick']}**  ·  stake **{r['stake']:.0f}**  "
                    f"(p={r['p_pick']:.2f}, Bayes={r['bayes_pick']:.2f}, {sizing})")
            else:
                motivo = "warm-up" if r["skip_warmup"] else "filtro Bayes"
                st.markdown(
                    f"⚪ {m['home']} vs {m['away']} · {m['stage']} → "
                    f"— sin apuesta ({motivo})")

# 6) Tabla de recomendaciones (solo programados)
st.subheader("Recomendaciones (partidos programados)")
rows = []
for m in calendar:
    if m["status_finished"]:
        continue
    r = recommend_bet(pipe.prematch_rec(m["home"], m["away"]),
                      float(common["bankroll0"]), params)
    rows.append({"fecha": m["date"], "partido": f"{m['home']} vs {m['away']}",
                 "lado": r["pick"] if r["bet"] else "—",
                 "stake": round(r["stake"], 2), "p_elo": round(r["p_pick"], 3),
                 "bayes": round(r["bayes_pick"], 3),
                 "apuesta": "sí" if r["bet"] else "no"})
if rows:
    st.dataframe(pd.DataFrame(rows), use_container_width=True, height=400)
else:
    st.caption("No hay partidos programados en el calendario actual.")
```

- [ ] **Step 2: Verificar que compila**

Run: `uv run python -m py_compile "pages/1_🔴_Mundial_en_vivo.py"`
Expected: exit 0.

- [ ] **Step 3: Smoke sin red del flujo en vivo (payload sintético → DB → recomendación)**

Run:
```bash
uv run python -c "
from sqlmodel import Session
from src.db import get_engine, init_db
from src.ingest import (seed_teams, get_or_create_tournament, ingest_calendar,
                        load_calendar, load_matches)
from src.scraper import parse_scoreboard_json
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE
from src.pipeline import Pipeline
from src.elo import EloSystem
from src.betting import BetParams, recommend_bet

payload = {'events': [
  {'id':'1','date':'2026-06-11T18:00Z','competitions':[{'status':{'type':{'name':'STATUS_FULL_TIME'}},'notes':[{'headline':'Group A'}],'competitors':[{'homeAway':'home','score':'3','team':{'displayName':'Argentina'}},{'homeAway':'away','score':'0','team':{'displayName':'Mexico'}}]}]},
  {'id':'2','date':'2026-06-15T18:00Z','competitions':[{'status':{'type':{'name':'STATUS_SCHEDULED'}},'notes':[{'headline':'Group A'}],'competitors':[{'homeAway':'home','score':'0','team':{'displayName':'Argentina'}},{'homeAway':'away','score':'0','team':{'displayName':'France'}}]}]},
]}
eng = get_engine(':memory:'); init_db(eng)
with Session(eng) as s:
    seed_teams(s, FIFA_SNAPSHOT_EXAMPLE)
    t = get_or_create_tournament(s, 'World Cup 2026', 2026, 'live')
    ingest_calendar(s, t, parse_scoreboard_json(payload))
    cal = load_calendar(s, t); fin = load_matches(s, t)
p = Pipeline(elo=EloSystem(k=40.0)); p.seed(FIFA_SNAPSHOT_EXAMPLE)
p.bayes.seed_from_elo(p.initial_elo, strength=4.0); p.process_all(fin)
params = BetParams(sizing='kelly', start_match_no=2)
sched = [m for m in cal if not m['status_finished']][0]
r = recommend_bet(p.prematch_rec(sched['home'], sched['away']), 1000.0, params)
print('calendario:', len(cal), 'finalizados:', len(fin))
print('recomendacion:', r['pick'], 'stake', round(r['stake'],1), 'bet', r['bet'])
assert len(cal) == 2 and len(fin) == 1
"
```
Expected: calendario 2, finalizados 1, e imprime una recomendación; sin excepciones.

- [ ] **Step 4: Smoke manual (opcional, requiere red para datos reales)**

Run: `uv run streamlit run app.py`
Expected: barra lateral con páginas "Backtest", "Mundial en vivo", "Simulador
Apuestas". En "Mundial en vivo", pulsar «Actualizar» con un rango válido scrapea y
muestra el calendario con recomendaciones. Cerrar con Ctrl+C.

- [ ] **Step 5: Commit**

```bash
git add "pages/1_🔴_Mundial_en_vivo.py"
git commit -m "feat: live World Cup page (scrape->DB calendar, per-match bet recommendations)"
```

---

## Task 7: Realinear el Simulador a `ui_common`

**Files:**
- Modify: `app/pages/2_💰_Simulador_Apuestas.py`

- [ ] **Step 1: Reemplazar el bloque del sidebar por los controles compartidos**

En `pages/2_💰_Simulador_Apuestas.py`, sustituir todo el bloque `with st.sidebar:`
(desde `with st.sidebar:` hasta el final de los controles de la barra lateral) por:
```python
from ui_common import model_controls, betting_controls

k_factor, prior_strength, use_margin = model_controls()
common = betting_controls()
st.sidebar.header("Estrategia (sizing)")
sizing = st.sidebar.selectbox("Bet sizing", ["flat", "confidence", "kelly"],
                              format_func={"flat": "Flat (% fijo)",
                                           "confidence": "Proporcional a confianza",
                                           "kelly": "Kelly fraccional"}.get,
                              key="sim_sizing")
bayes_threshold = common["bayes_threshold"]
```
Añadir el import `from ui_common import model_controls, betting_controls` junto a
los demás imports de la cabecera (y quitar el import duplicado si quedara dentro
del sidebar).

- [ ] **Step 2: Ajustar la construcción de `common`/`BetParams` y referencias**

El código posterior ya usa un dict `common` y `BetParams(use_bayes_filter=..., **common)`.
Reemplazar la antigua definición local de `common` (la que armaba el dict con
`bankroll0`, `odds`, etc.) por el uso del `common` devuelto por `betting_controls()`
más `sizing`:
```python
res_all = simulate(pipe.match_log, BetParams(sizing=sizing, use_bayes_filter=False, **common))
res_flt = simulate(pipe.match_log, BetParams(sizing=sizing, use_bayes_filter=True, **common))
```
(Las dos llamadas a `simulate` y todo lo de KPIs/curvas/tablas se mantienen igual;
`bayes_threshold` ya está disponible desde `common`.)

- [ ] **Step 3: Verificar que compila**

Run: `uv run python -m py_compile "pages/2_💰_Simulador_Apuestas.py"`
Expected: exit 0.

- [ ] **Step 4: Suite completa**

Run: `uv run pytest -q`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add "pages/2_💰_Simulador_Apuestas.py"
git commit -m "refactor: simulator page uses shared ui_common controls"
```

---

## Task 8: Documentación

**Files:**
- Modify: `app/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Actualizar `app/README.md`**

En "Estructura", reflejar las 3 páginas y los nuevos módulos:
```
app.py                            # 📊 Backtest (Qatar)
ui_common.py                      # controles de sidebar compartidos (session_state)
pages/1_🔴_Mundial_en_vivo.py     # scrape ESPN -> DB (calendario) + recomendaciones
pages/2_💰_Simulador_Apuestas.py  # backtest de apuestas
src/betting.py                    # motor puro: BetParams, pick_side, stake_amount, simulate, recommend_bet
```
Y un párrafo en "Cómo correrlo": la barra lateral muestra **Backtest**, **Mundial
en vivo** y **Simulador**; los parámetros se comparten entre páginas; en vivo el
scrape guarda el calendario completo en la DB.

- [ ] **Step 2: Actualizar `CLAUDE.md`**

Actualizar la tabla de arquitectura: marcar que la DB guarda finalizados +
calendario, añadir `app/ui_common.py` y la página `pages/1_🔴_Mundial_en_vivo.py`,
y añadir `recommend_bet`/`prematch_rec` a las firmas de betting/pipeline. Añadir:
"`app.py` es la página Backtest; `pages/` contiene Mundial en vivo y Simulador. Los
parámetros se comparten entre páginas vía `session_state` (helpers en `ui_common.py`)."

- [ ] **Step 3: Suite completa final**

Run: `uv run pytest -q`
Expected: PASS (todos).

- [ ] **Step 4: Commit**

```bash
git add ../CLAUDE.md README.md
git commit -m "docs: document page split, live calendar and shared controls"
```

---

## Notas de verificación final

- `uv run pytest -q` verde (pipeline + models + ingest + betting con los nuevos tests).
- `py_compile` OK en `app.py`, `ui_common.py` y las dos páginas.
- DB guarda finalizados + calendario; `load_matches` solo finalizados, `load_calendar` todos.
- El scraping en vivo necesita red; sin calendario en DB la página muestra aviso.
- Parámetros concordantes entre páginas vía `session_state` (mismas `key=`).
