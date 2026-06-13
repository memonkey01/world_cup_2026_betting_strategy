# Laboratorio de estrategias → Producción Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Barrer estrategias de apuestas sobre Qatar, rankearlas por yield, fijar la ganadora en la DB y consumirla en la página en vivo.

**Architecture:** Función pura `betting.sweep_strategies` (reusa `simulate`) genera el ranking. Un modelo `Strategy` + `src/strategies.py` persisten/recuperan la estrategia activa (una sola `active`). La página Simulador corre el barrido y fija la ganadora; la página en vivo lee la estrategia activa y recomienda con ella.

**Tech Stack:** Python 3.11+, SQLModel/SQLite, Streamlit multipage, pytest.

**Working dir:** Todos los comandos desde `app/`.

---

## File Structure

| Archivo | Responsabilidad |
|---------|-----------------|
| `app/src/betting.py` | + `sweep_strategies(match_log, base)` (ranking por yield) |
| `app/src/models.py` | + modelo `Strategy` (campos BetParams + label/active/métricas) |
| `app/src/strategies.py` | NUEVO — `strategy_to_params`, `save_active_strategy`, `load_active_strategy` |
| `app/pages/2_💰_Simulador_Apuestas.py` | + barrido, ranking y botón "Fijar como activa" |
| `app/pages/1_🔴_Mundial_en_vivo.py` | usa la estrategia activa de la DB (con fallback) |
| `app/tests/test_betting.py` | + tests de `sweep_strategies` |
| `app/tests/test_strategies.py` | NUEVO — roundtrip y una sola activa |

---

## Task 1: `betting.sweep_strategies`

**Files:**
- Modify: `app/src/betting.py`
- Test: `app/tests/test_betting.py`

- [ ] **Step 1: Añadir el test que falla**

Agregar a `app/tests/test_betting.py` (usa el helper `rec` ya existente):
```python
def test_sweep_strategies_ranks_by_yield():
    from src.betting import sweep_strategies
    # log de 6 partidos, equipos ya con match_no>=2 (sin warm-up)
    log = [rec(home="A", away="B", p_home=0.7,
               bayes_home=0.6, bayes_away=0.4,
               home_win=(i % 2 == 0), away_win=(i % 2 == 1),
               home_match_no=2 + i, away_match_no=2 + i)
           for i in range(6)]
    base = BetParams(bankroll0=1000.0, odds=2.0, base_fraction=0.1,
                     kelly_fraction=0.25, start_match_no=2,
                     blend_weight=0.5, bayes_threshold=0.5)
    rows = sweep_strategies(log, base)
    # 3 sizing x 3 criterio x 2 filtro = 18 combinaciones
    assert len(rows) == 18
    # ordenadas por yield desc
    ys = [r["metrics"]["yield"] for r in rows]
    assert ys == sorted(ys, reverse=True)
    # cada fila trae los params (BetParams) y las claves del combo
    top = rows[0]
    assert isinstance(top["params"], BetParams)
    assert top["sizing"] in ("flat", "confidence", "kelly")
    assert top["side_criterion"] in ("elo", "bayes", "blend")
    assert top["use_bayes_filter"] in (True, False)
    assert "curve" not in top["metrics"]  # métricas livianas (sin curva/apuestas)
```

- [ ] **Step 2: Correr para verlo fallar**

Run: `uv run pytest tests/test_betting.py::test_sweep_strategies_ranks_by_yield -q`
Expected: FAIL con `ImportError: cannot import name 'sweep_strategies'`.

- [ ] **Step 3: Implementar `sweep_strategies` en `app/src/betting.py`**

Añadir al final del módulo:
```python
from dataclasses import replace

SWEEP_SIZINGS = ("flat", "confidence", "kelly")
SWEEP_CRITERIA = ("elo", "bayes", "blend")
SWEEP_FILTERS = (False, True)


def sweep_strategies(match_log: list[dict], base: BetParams) -> list[dict]:
    """Barre sizing x side_criterion x use_bayes_filter (18 combos) manteniendo
    el resto de `base` fijo. Devuelve filas {sizing, side_criterion,
    use_bayes_filter, params, metrics} ordenadas por yield desc (luego roi desc)."""
    rows = []
    for sizing in SWEEP_SIZINGS:
        for criterion in SWEEP_CRITERIA:
            for use_filter in SWEEP_FILTERS:
                params = replace(base, sizing=sizing, side_criterion=criterion,
                                 use_bayes_filter=use_filter)
                res = simulate(match_log, params)
                metrics = {k: v for k, v in res.items()
                           if k not in ("curve", "bets")}
                rows.append({
                    "sizing": sizing,
                    "side_criterion": criterion,
                    "use_bayes_filter": use_filter,
                    "params": params,
                    "metrics": metrics,
                })
    rows.sort(key=lambda r: (r["metrics"]["yield"], r["metrics"]["roi"]),
              reverse=True)
    return rows
```
(`replace` es de `dataclasses`; `BetParams` es un dataclass, así que `replace`
produce una copia con los campos cambiados.)

- [ ] **Step 4: Correr el test**

Run: `uv run pytest tests/test_betting.py -q`
Expected: PASS (los previos + el nuevo).

- [ ] **Step 5: Commit**

```bash
git add src/betting.py tests/test_betting.py
git commit -m "feat: betting.sweep_strategies ranks strategy grid by yield"
```

---

## Task 2: Modelo `Strategy`

**Files:**
- Modify: `app/src/models.py`
- Test: `app/tests/test_strategies.py` (parte de esquema)

- [ ] **Step 1: Escribir el test que falla**

Create `app/tests/test_strategies.py`:
```python
"""Tests de persistencia de la estrategia activa."""
from sqlmodel import Session

from src.db import get_engine, init_db
from src.models import Strategy
from src.betting import BetParams
from src.strategies import (strategy_to_params, save_active_strategy,
                            load_active_strategy)


def make_session() -> Session:
    engine = get_engine(":memory:")
    init_db(engine)
    return Session(engine)


def test_strategy_table_exists_and_defaults():
    s = make_session()
    row = Strategy(label="x", bankroll0=1000.0, odds=2.0, sizing="kelly",
                   base_fraction=0.05, kelly_fraction=0.25, start_match_no=2,
                   side_criterion="elo", blend_weight=0.5,
                   use_bayes_filter=False, bayes_threshold=0.5)
    s.add(row); s.commit()
    assert row.id is not None
    assert row.active is False
```

- [ ] **Step 2: Correr para verlo fallar**

Run: `uv run pytest tests/test_strategies.py -q`
Expected: FAIL con `ImportError` (`Strategy` / `src.strategies` no existen aún).

- [ ] **Step 3: Añadir el modelo `Strategy` en `app/src/models.py`**

Al final del archivo:
```python
class Strategy(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    label: str
    active: bool = False
    # campos de BetParams
    bankroll0: float
    odds: float
    sizing: str
    base_fraction: float
    kelly_fraction: float
    start_match_no: int
    side_criterion: str
    blend_weight: float
    use_bayes_filter: bool
    bayes_threshold: float
    # métricas logradas en el backtest
    backtest_yield: float | None = None
    backtest_roi: float | None = None
```

- [ ] **Step 4: Crear `app/src/strategies.py` (mínimo para que importe el test)**

```python
"""Persistencia de la estrategia activa (la elegida en el laboratorio)."""
from __future__ import annotations

from sqlmodel import Session, select

from .models import Strategy
from .betting import BetParams

_PARAM_FIELDS = ("bankroll0", "odds", "sizing", "base_fraction", "kelly_fraction",
                 "start_match_no", "side_criterion", "blend_weight",
                 "use_bayes_filter", "bayes_threshold")


def strategy_to_params(strategy: Strategy) -> BetParams:
    return BetParams(**{f: getattr(strategy, f) for f in _PARAM_FIELDS})


def save_active_strategy(session: Session, params: BetParams, label: str,
                         *, yield_: float | None = None,
                         roi: float | None = None) -> Strategy:
    """Desactiva las previas y guarda `params` como la única estrategia activa."""
    for prev in session.exec(select(Strategy).where(Strategy.active == True)).all():  # noqa: E712
        prev.active = False
    row = Strategy(label=label, active=True,
                   backtest_yield=yield_, backtest_roi=roi,
                   **{f: getattr(params, f) for f in _PARAM_FIELDS})
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def load_active_strategy(session: Session) -> Strategy | None:
    return session.exec(select(Strategy).where(Strategy.active == True)).first()  # noqa: E712
```

- [ ] **Step 5: Correr el test de esquema**

Run: `uv run pytest tests/test_strategies.py::test_strategy_table_exists_and_defaults -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/models.py src/strategies.py tests/test_strategies.py
git commit -m "feat: Strategy model + strategies persistence module"
```

---

## Task 3: Roundtrip y unicidad de la estrategia activa

**Files:**
- Modify: `app/tests/test_strategies.py`

- [ ] **Step 1: Añadir los tests**

Agregar a `app/tests/test_strategies.py`:
```python
def test_save_and_load_roundtrip():
    s = make_session()
    params = BetParams(sizing="kelly", side_criterion="blend",
                       use_bayes_filter=True, bayes_threshold=0.55,
                       odds=1.9, base_fraction=0.08, kelly_fraction=0.5,
                       start_match_no=3, blend_weight=0.7, bankroll0=2000.0)
    save_active_strategy(s, params, "ganadora", yield_=0.12, roi=0.30)
    loaded = load_active_strategy(s)
    assert loaded is not None and loaded.label == "ganadora"
    assert loaded.backtest_yield == 0.12
    assert strategy_to_params(loaded) == params  # BetParams reconstruido igual


def test_only_one_active():
    s = make_session()
    save_active_strategy(s, BetParams(sizing="flat"), "v1")
    save_active_strategy(s, BetParams(sizing="kelly"), "v2")
    active = load_active_strategy(s)
    assert active.label == "v2" and active.sizing == "kelly"
    from sqlmodel import select
    actives = s.exec(select(Strategy).where(Strategy.active == True)).all()  # noqa: E712
    assert len(actives) == 1
```

- [ ] **Step 2: Correr los tests**

Run: `uv run pytest tests/test_strategies.py -q`
Expected: PASS (3 tests). `strategy_to_params(loaded) == params` confirma que el
roundtrip preserva todos los campos de `BetParams`.

- [ ] **Step 3: Suite completa**

Run: `uv run pytest -q`
Expected: PASS (todos).

- [ ] **Step 4: Commit**

```bash
git add tests/test_strategies.py
git commit -m "test: strategy save/load roundtrip and single-active invariant"
```

---

## Task 4: Laboratorio en la página Simulador

**Files:**
- Modify: `app/pages/2_💰_Simulador_Apuestas.py`

- [ ] **Step 1: Añadir imports del barrido y persistencia**

En la cabecera de imports de `pages/2_💰_Simulador_Apuestas.py`, junto a
`from src.betting import BetParams, simulate`, dejar:
```python
from src.betting import BetParams, simulate, sweep_strategies
from src.strategies import save_active_strategy
```

- [ ] **Step 2: Añadir la sección de barrido tras las curvas de bankroll**

Al final del archivo (después de las tablas de apuestas existentes), añadir:
```python
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
```

- [ ] **Step 3: Verificar que compila**

Run: `uv run python -m py_compile "pages/2_💰_Simulador_Apuestas.py"`
Expected: exit 0.

- [ ] **Step 4: Smoke del barrido + fijar (sin Streamlit)**

Run:
```bash
uv run python -c "
from sqlmodel import Session
from src.db import get_engine, init_db
from src.ingest import ingest_qatar_backtest, load_matches
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE
from src.pipeline import Pipeline
from src.elo import EloSystem
from src.betting import BetParams, sweep_strategies
from src.strategies import save_active_strategy, load_active_strategy, strategy_to_params
eng = get_engine(':memory:'); init_db(eng)
with Session(eng) as s:
    t = ingest_qatar_backtest(s, prefer_scrape=False); m = load_matches(s, t)
p = Pipeline(elo=EloSystem(k=40.0)); p.seed(FIFA_SNAPSHOT_EXAMPLE)
p.bayes.seed_from_elo(p.initial_elo, strength=4.0); p.process_all(m)
ranking = sweep_strategies(p.match_log, BetParams(bankroll0=1000.0))
top = ranking[0]
print('combos:', len(ranking), '| top:', top['sizing'], top['side_criterion'],
      'filtro', top['use_bayes_filter'], '| yield', round(top['metrics']['yield']*100,1), '%')
with Session(eng) as s:
    save_active_strategy(s, top['params'], 'top', yield_=top['metrics']['yield'])
    act = load_active_strategy(s)
    assert strategy_to_params(act) == top['params']
print('estrategia activa:', act.label, act.sizing, act.side_criterion)
"
```
Expected: imprime 18 combos, la top con su yield, y confirma que la activa se guarda
y recupera igual. Sin excepciones.

- [ ] **Step 5: Commit**

```bash
git add "pages/2_💰_Simulador_Apuestas.py"
git commit -m "feat: strategy sweep + rank + 'fijar activa' in simulator page"
```

---

## Task 5: La página en vivo usa la estrategia activa

**Files:**
- Modify: `app/pages/1_🔴_Mundial_en_vivo.py`

- [ ] **Step 1: Importar la carga de estrategia activa**

En la cabecera de imports de `pages/1_🔴_Mundial_en_vivo.py`, junto a
`from src.betting import BetParams, recommend_bet`, añadir:
```python
from src.strategies import load_active_strategy, strategy_to_params
```

- [ ] **Step 2: Resolver los params desde la estrategia activa (con fallback)**

Sustituir la línea actual:
```python
params = BetParams(sizing=sizing, use_bayes_filter=use_filter, **common)
```
por:
```python
# Estrategia activa de la DB (fijada en el laboratorio) tiene prioridad.
with Session(db_engine) as s:
    active = load_active_strategy(s)
if active is not None:
    params = strategy_to_params(active)
    yld = f"{active.backtest_yield*100:.1f}%" if active.backtest_yield is not None else "n/d"
    st.success(f"📌 Estrategia activa: **{active.label}** "
               f"(sizing {active.sizing} · criterio {active.side_criterion} · "
               f"filtro {'sí' if active.use_bayes_filter else 'no'} · yield Qatar {yld}). "
               "Cámbiala en la página «Simulador».")
else:
    params = BetParams(sizing=sizing, use_bayes_filter=use_filter, **common)
    st.info("No hay estrategia activa fijada. Usando los controles de la barra "
            "lateral. Ve al «Simulador» para barrer y fijar la mejor.")
```

- [ ] **Step 3: Verificar que compila**

Run: `uv run python -m py_compile "pages/1_🔴_Mundial_en_vivo.py"`
Expected: exit 0.

- [ ] **Step 4: Smoke del consumo de estrategia activa (sin red)**

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
from src.strategies import save_active_strategy, load_active_strategy, strategy_to_params
payload = {'events': [
  {'id':'1','date':'2026-06-11T18:00Z','competitions':[{'status':{'type':{'name':'STATUS_FULL_TIME'}},'notes':[{'headline':'Group A'}],'competitors':[{'homeAway':'home','score':'3','team':{'displayName':'Argentina'}},{'homeAway':'away','score':'0','team':{'displayName':'Mexico'}}]}]},
  {'id':'2','date':'2026-06-15T18:00Z','competitions':[{'status':{'type':{'name':'STATUS_SCHEDULED'}},'notes':[{'headline':'Group A'}],'competitors':[{'homeAway':'home','score':'0','team':{'displayName':'Argentina'}},{'homeAway':'away','score':'0','team':{'displayName':'France'}}]}]},
]}
eng = get_engine(':memory:'); init_db(eng)
with Session(eng) as s:
    seed_teams(s, FIFA_SNAPSHOT_EXAMPLE)
    t = get_or_create_tournament(s, 'World Cup 2026', 2026, 'live')
    ingest_calendar(s, t, parse_scoreboard_json(payload))
    save_active_strategy(s, BetParams(sizing='kelly', side_criterion='elo', start_match_no=2), 'top', yield_=0.1)
    cal = load_calendar(s, t); fin = load_matches(s, t)
    params = strategy_to_params(load_active_strategy(s))
p = Pipeline(elo=EloSystem(k=40.0)); p.seed(FIFA_SNAPSHOT_EXAMPLE)
p.bayes.seed_from_elo(p.initial_elo, strength=4.0); p.process_all(fin)
sched = [m for m in cal if not m['status_finished']][0]
r = recommend_bet(p.prematch_rec(sched['home'], sched['away']), 1000.0, params)
print('estrategia activa sizing:', params.sizing, '| recomienda:', r['pick'], 'stake', round(r['stake'],1))
"
```
Expected: usa la estrategia activa (kelly) y recomienda con ella; sin excepciones.

- [ ] **Step 5: Commit**

```bash
git add "pages/1_🔴_Mundial_en_vivo.py"
git commit -m "feat: live page consumes active strategy from DB (with fallback)"
```

---

## Task 6: Documentación

**Files:**
- Modify: `app/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Actualizar `app/README.md`**

- En "Estructura" añadir:
```
src/strategies.py     # estrategia activa en la DB (save/load, Strategy<->BetParams)
```
- En la descripción del **Simulador**, añadir que ahora barre estrategias
  (sizing × criterio × filtro) y rankea por **yield**, y permite **fijar la
  ganadora** en la DB; y en **Mundial en vivo**, que usa esa **estrategia activa**.
- Añadir una línea de flujo: "Laboratorio (Qatar) → fijar la mejor → la página en
  vivo recomienda 2026 con esa estrategia."

- [ ] **Step 2: Actualizar `CLAUDE.md`**

- Añadir a la tabla de arquitectura:
```
| [app/src/strategies.py](app/src/strategies.py) | Estrategia activa en la DB: `save_active_strategy`, `load_active_strategy`, `strategy_to_params` |
```
- En `src/betting.py` añadir `sweep_strategies` a las firmas; en `src/models.py`
  añadir `Strategy`.
- Añadir una frase: "Flujo Laboratorio→Producción: el Simulador barre estrategias
  sobre Qatar (`sweep_strategies`) y fija la ganadora en la DB (`Strategy`); la
  página en vivo la lee (`load_active_strategy`) y recomienda con ella."

- [ ] **Step 3: Suite completa final**

Run: `uv run pytest -q`
Expected: PASS (todos).

- [ ] **Step 4: Commit**

```bash
git add ../CLAUDE.md README.md
git commit -m "docs: document strategy lab (sweep, active strategy, lab->live flow)"
```

---

## Notas de verificación final

- `uv run pytest -q` verde (incluye `sweep_strategies` y `strategies`).
- `py_compile` OK en las dos páginas modificadas.
- `sweep_strategies` es puro (reusa `simulate`, no toca DB/Streamlit).
- Solo una `Strategy` con `active=True`; `strategy_to_params` reconstruye `BetParams` íntegro.
- La página en vivo prioriza la estrategia activa; sin ella, cae a los controles.
