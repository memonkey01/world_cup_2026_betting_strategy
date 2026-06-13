# Mejoras de la revisión (5 ítems) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cerrar los 5 puntos de la revisión: persistir snapshots, uploader FIFA, modelo 2026 en el panel de cuotas, override de estrategia en vivo y parser de Polymarket robusto.

**Architecture:** Cambios pequeños y localizados: `clear_snapshots` en ingest + llamada tras el backtest; `fifa_ranking()` en ui_common; el panel de cuotas entrena un pipe con finalizados 2026; toggle de override en la página en vivo; `parse_polymarket` soporta mercados Yes/No emparejados por partido.

**Tech Stack:** Python 3.11+, SQLModel/SQLite, Streamlit, pytest.

**Working dir:** Todos los comandos desde `app/`.

---

## File Structure

| Archivo | Responsabilidad |
|---------|-----------------|
| `app/src/ingest.py` | + `clear_snapshots(session, tournament)` |
| `app/src/odds.py` | `parse_polymarket` robusto (Yes/No) + `_parse_versus` |
| `app/ui_common.py` | + `fifa_ranking()` |
| `app/app.py` | usa `fifa_ranking()`; persiste snapshots tras el backtest |
| `app/pages/2_💰_Simulador_Apuestas.py` | panel de cuotas usa pipe 2026 |
| `app/pages/1_🔴_Mundial_en_vivo.py` | toggle override de estrategia |
| `app/tests/test_ingest.py` | + `clear_snapshots` |
| `app/tests/test_odds.py` | + Yes/No emparejado + `_parse_versus` |

---

## Task 1: `clear_snapshots` + persistir snapshots tras el backtest

**Files:**
- Modify: `app/src/ingest.py`
- Modify: `app/app.py`
- Test: `app/tests/test_ingest.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `app/tests/test_ingest.py`:
```python
def test_clear_snapshots():
    from src.pipeline import Pipeline
    from src.ingest import clear_snapshots, persist_snapshots
    from src.models import RatingSnapshot
    s = make_session()
    seed_teams(s, FIFA_SNAPSHOT_EXAMPLE)
    t = get_or_create_tournament(s, "Qatar 2022", 2022, "backtest")
    ingest_matches(s, t, fixture_to_results(QATAR_2022_SAMPLE), source="fixture")
    pipe = Pipeline()
    pipe.seed(FIFA_SNAPSHOT_EXAMPLE)
    pipe.process_all(load_matches(s, t))
    persist_snapshots(s, t, pipe)
    assert len(s.exec(select(RatingSnapshot)).all()) > 0
    removed = clear_snapshots(s, t)
    assert removed > 0
    assert s.exec(select(RatingSnapshot)).all() == []
```

- [ ] **Step 2: Correr para verlo fallar**

Run: `uv run pytest tests/test_ingest.py::test_clear_snapshots -q`
Expected: FAIL con `ImportError: cannot import name 'clear_snapshots'`.

- [ ] **Step 3: Implementar `clear_snapshots` en `app/src/ingest.py`**

Añadir tras `persist_snapshots`:
```python
def clear_snapshots(session: Session, tournament: Tournament) -> int:
    """Borra los RatingSnapshot del torneo. Devuelve cuántos borró."""
    rows = session.exec(select(RatingSnapshot).where(
        RatingSnapshot.tournament_id == tournament.id)).all()
    for r in rows:
        session.delete(r)
    session.commit()
    return len(rows)
```
(`RatingSnapshot` ya está importado en `ingest.py` desde `.models`.)

- [ ] **Step 4: Correr el test**

Run: `uv run pytest tests/test_ingest.py -q`
Expected: PASS (todos).

- [ ] **Step 5: Persistir snapshots en `app/app.py` tras el pipeline**

En `app/app.py`, añadir el import:
```python
from src.ingest import ingest_qatar_backtest, load_matches, clear_snapshots, persist_snapshots
```
(reemplaza el import existente `from src.ingest import ingest_qatar_backtest, load_matches`).

Tras `lb = pd.DataFrame(pipe.combined_leaderboard())` (después de procesar el pipe),
añadir:
```python
# Persistir la evolución (borra y reescribe los snapshots del torneo).
with Session(db_engine) as s:
    tq = s.exec(select(Tournament).where(Tournament.name == "Qatar 2022")).first()
    if tq:
        clear_snapshots(s, tq)
        persist_snapshots(s, tq, pipe)
```

- [ ] **Step 6: Verificar compila + snapshots se guardan**

Run: `uv run python -m py_compile app.py`
Expected: exit 0.

Run:
```bash
uv run python -c "
from sqlmodel import Session, select
from src.db import get_engine, init_db
from src.ingest import ingest_qatar_backtest, load_matches, clear_snapshots, persist_snapshots
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE
from src.pipeline import Pipeline
from src.elo import EloSystem
from src.models import RatingSnapshot, Tournament
eng = get_engine(':memory:'); init_db(eng)
with Session(eng) as s:
    t = ingest_qatar_backtest(s, prefer_scrape=False); m = load_matches(s, t)
p = Pipeline(elo=EloSystem(k=40.0)); p.seed(FIFA_SNAPSHOT_EXAMPLE); p.process_all(m)
with Session(eng) as s:
    tq = s.exec(select(Tournament).where(Tournament.name=='Qatar 2022')).first()
    clear_snapshots(s, tq); persist_snapshots(s, tq, p)
    clear_snapshots(s, tq); persist_snapshots(s, tq, p)  # 2ª vez no acumula
    print('snapshots:', len(s.exec(select(RatingSnapshot)).all()))
"
```
Expected: imprime un número >0 estable (no se duplica entre corridas).

- [ ] **Step 7: Commit**

```bash
git add src/ingest.py app.py tests/test_ingest.py
git commit -m "feat: persist RatingSnapshot after backtest (clear+rewrite)"
```

---

## Task 2: `fifa_ranking()` en ui_common + uso en Backtest

**Files:**
- Modify: `app/ui_common.py`
- Modify: `app/app.py`

- [ ] **Step 1: Añadir `fifa_ranking()` en `app/ui_common.py`**

```python
def fifa_ranking() -> dict[str, float]:
    """Sidebar 'Ranking FIFA': snapshot incluido o JSON subido {equipo: puntos}."""
    import json
    from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE
    st.sidebar.header("Ranking FIFA")
    fuente = st.sidebar.radio("Origen", ["Snapshot incluido", "Subir JSON"],
                              key="fifa_source")
    if fuente == "Subir JSON":
        up = st.sidebar.file_uploader("JSON {equipo: puntos}", type="json",
                                      key="fifa_json")
        if up is not None:
            try:
                return {k: float(v) for k, v in json.load(up).items()}
            except (ValueError, TypeError):
                st.sidebar.error("JSON inválido; usando el snapshot incluido.")
    return dict(FIFA_SNAPSHOT_EXAMPLE)
```

- [ ] **Step 2: Usarlo en `app/app.py`**

Reemplazar:
```python
from ui_common import model_controls
```
por:
```python
from ui_common import model_controls, fifa_ranking
```
y reemplazar:
```python
k_factor, prior_strength, use_margin = model_controls()
fifa_points = FIFA_SNAPSHOT_EXAMPLE
```
por:
```python
k_factor, prior_strength, use_margin = model_controls()
fifa_points = fifa_ranking()
```

- [ ] **Step 3: Verificar que compila**

Run: `uv run python -m py_compile app.py ui_common.py`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add ui_common.py app.py
git commit -m "feat: restore FIFA ranking JSON uploader via ui_common.fifa_ranking"
```

---

## Task 3: `parse_polymarket` robusto (mercados Yes/No)

**Files:**
- Modify: `app/src/odds.py`
- Test: `app/tests/test_odds.py`

- [ ] **Step 1: Añadir los tests que fallan**

Agregar a `app/tests/test_odds.py`:
```python
from src.odds import _parse_versus


def test_parse_versus_patterns():
    assert _parse_versus("Will Argentina beat France?") == ("Argentina", "France")
    assert _parse_versus("Will Mexico win vs Canada") == ("Mexico", "Canada")
    assert _parse_versus("Brazil vs Croatia") == ("Brazil", "Croatia")
    assert _parse_versus("Who wins the World Cup?") is None


# Dos mercados Yes/No del mismo partido -> un OddsQuote emparejado.
POLY_YESNO = [
    {"question": "Will Argentina beat France?",
     "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.6\", \"0.4\"]"},
    {"question": "Will France beat Argentina?",
     "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.4\", \"0.6\"]"},
]


def test_parse_polymarket_yesno_pairs():
    quotes = parse_polymarket(POLY_YESNO, "2026-06-13T08:00:00")
    assert len(quotes) == 1
    q = quotes[0]
    assert {q.home, q.away} == {"Argentina", "France"}
    # P(home) = precio Yes del primer mercado visto (Argentina) = 0.6
    if q.home == "Argentina":
        assert abs(q.home_prob - 0.6) < 1e-6
        assert abs(q.away_prob - 0.4) < 1e-6


def test_parse_polymarket_yesno_unpaired_ignored():
    # un solo Yes/No sin su par -> no se emite quote (no se puede emparejar)
    one = [{"question": "Will Argentina beat France?",
            "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.6\", \"0.4\"]"}]
    assert parse_polymarket(one, "2026-06-13T08:00:00") == []
```

- [ ] **Step 2: Correr para verlo fallar**

Run: `uv run pytest tests/test_odds.py -k "versus or yesno" -q`
Expected: FAIL (`_parse_versus` no existe; el parser aún no empareja Yes/No).

- [ ] **Step 3: Modificar `app/src/odds.py`**

Añadir el import de `re` arriba (junto a `import json`):
```python
import json
import re
```

Añadir el helper antes de `parse_polymarket`:
```python
_VERSUS_PATTERNS = [
    re.compile(r"^will\s+(.+?)\s+beat\s+(.+?)\??$", re.I),
    re.compile(r"^will\s+(.+?)\s+win\s+vs\.?\s+(.+?)\??$", re.I),
    re.compile(r"^will\s+(.+?)\s+win\s+against\s+(.+?)\??$", re.I),
    re.compile(r"^(.+?)\s+vs\.?\s+(.+?)\??$", re.I),
]


def _parse_versus(question: str) -> tuple[str, str] | None:
    """Extrae (equipo, rival) de la pregunta de un mercado Yes/No. None si no aplica."""
    q = (question or "").strip()
    for pat in _VERSUS_PATTERNS:
        m = pat.match(q)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return None
```

Reemplazar `parse_polymarket` por la versión que soporta ambas formas:
```python
def parse_polymarket(payload: list, fetched_at: str) -> list[OddsQuote]:
    """Soporta (1) mercados de 2 outcomes = equipos, y (2) mercados Yes/No
    'Will X beat Y' que se emparejan por partido (clave frozenset{equipos})."""
    out: list[OddsQuote] = []
    pending: dict[frozenset, tuple[str, float]] = {}  # par -> (equipo, P(Yes))
    for mkt in payload:
        try:
            outcomes = json.loads(mkt["outcomes"])
            prices = [float(p) for p in json.loads(mkt["outcomePrices"])]
        except (KeyError, ValueError, TypeError):
            continue
        if len(outcomes) != 2 or len(prices) != 2:
            continue
        labels = [str(o).strip().lower() for o in outcomes]
        if set(labels) == {"yes", "no"}:
            vs = _parse_versus(mkt.get("question", ""))
            if not vs:
                continue
            team, opp = normalize_es(vs[0]), normalize_es(vs[1])
            yes_idx = labels.index("yes")
            p_yes = prices[yes_idx]
            key = frozenset((team, opp))
            if key in pending:
                first_team, first_pyes = pending.pop(key)
                # first_team es home; el otro equipo del par es away
                away = opp if first_team == team else team
                home = first_team
                p_home = first_pyes
                p_away = p_yes if away in (team, opp) else 1 - p_yes
                out.append(_quote("polymarket", home, away,
                                  price_to_decimal(p_home), price_to_decimal(p_away),
                                  None, fetched_at))
            else:
                pending[key] = (team, p_yes)
        else:
            home, away = normalize_es(outcomes[0]), normalize_es(outcomes[1])
            out.append(_quote("polymarket", home, away,
                              price_to_decimal(prices[0]), price_to_decimal(prices[1]),
                              None, fetched_at))
    return out
```

- [ ] **Step 4: Correr los tests de odds**

Run: `uv run pytest tests/test_odds.py -q`
Expected: PASS (los previos de 2-outcomes + los nuevos Yes/No + `_parse_versus`).

- [ ] **Step 5: Commit**

```bash
git add src/odds.py tests/test_odds.py
git commit -m "feat: polymarket parser handles paired Yes/No 'Will X beat Y' markets"
```

---

## Task 4: Panel de cuotas usa el modelo 2026

**Files:**
- Modify: `app/pages/2_💰_Simulador_Apuestas.py`

- [ ] **Step 1: Entrenar un pipe con finalizados 2026 en el panel de cuotas**

En `pages/2_💰_Simulador_Apuestas.py`, añadir `load_matches` al import de ingest:
```python
from src.ingest import get_or_create_tournament, seed_teams, load_calendar, load_matches
```

En el bloque de la tabla comparativa de cuotas (donde hoy se hace
`rec = pipe.prematch_rec(...)`), antes del bucle construir un pipe 2026 y usarlo:
```python
with Session(db_engine) as s:
    wc = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
    poly_map = {(o["home"], o["away"]): o for o in latest_odds(s, wc, "polymarket")}
    cod_map = {(o["home"], o["away"]): o for o in latest_odds(s, wc, "codere")}
    calendar = load_calendar(s, wc)
    finished_2026 = load_matches(s, wc)

pipe_live = Pipeline(elo=EloSystem(k=k_factor, use_margin=use_margin))
pipe_live.seed(FIFA_SNAPSHOT_EXAMPLE)
pipe_live.bayes.seed_from_elo(pipe_live.initial_elo, strength=prior_strength)
pipe_live.process_all(finished_2026)
```
Y dentro del bucle cambiar `rec = pipe.prematch_rec(...)` por
`rec = pipe_live.prematch_rec(m["home"], m["away"])`.

Actualizar la caption de la tabla:
```python
    st.caption("«modelo P(home)» usa un pipe entrenado con los partidos 2026 ya "
               "finalizados (de la DB). «valor» = prob. modelo − prob. implícita.")
```
(`k_factor`, `prior_strength`, `use_margin` ya existen en la página desde
`model_controls()`.)

- [ ] **Step 2: Verificar que compila**

Run: `uv run python -m py_compile "pages/2_💰_Simulador_Apuestas.py"`
Expected: exit 0.

- [ ] **Step 3: Smoke sin red (pipe 2026 + comparación)**

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
payload={'events':[{'id':'1','date':'2026-06-11T18:00Z','competitions':[{'status':{'type':{'name':'STATUS_FULL_TIME'}},'notes':[{'headline':'Group A'}],'competitors':[{'homeAway':'home','score':'3','team':{'displayName':'Argentina'}},{'homeAway':'away','score':'0','team':{'displayName':'Mexico'}}]}]},{'id':'2','date':'2026-06-15T18:00Z','competitions':[{'status':{'type':{'name':'STATUS_SCHEDULED'}},'notes':[{'headline':'Group A'}],'competitors':[{'homeAway':'home','score':'0','team':{'displayName':'Argentina'}},{'homeAway':'away','score':'0','team':{'displayName':'France'}}]}]}]}
eng=get_engine(':memory:'); init_db(eng)
with Session(eng) as s:
    seed_teams(s, FIFA_SNAPSHOT_EXAMPLE)
    t=get_or_create_tournament(s,'World Cup 2026',2026,'live')
    ingest_calendar(s,t,parse_scoreboard_json(payload))
    fin=load_matches(s,t)
pl=Pipeline(elo=EloSystem(k=40.0)); pl.seed(FIFA_SNAPSHOT_EXAMPLE)
pl.bayes.seed_from_elo(pl.initial_elo, strength=4.0); pl.process_all(fin)
print('finalizados 2026:', len(fin), '| P(Arg vs France):', round(pl.prematch_rec('Argentina','France')['p_home'],3))
"
```
Expected: finalizados 2026 = 1 y una P(home); sin excepciones.

- [ ] **Step 4: Commit**

```bash
git add "pages/2_💰_Simulador_Apuestas.py"
git commit -m "feat: odds panel compares against a 2026-trained model pipe"
```

---

## Task 5: Toggle de override de estrategia en vivo

**Files:**
- Modify: `app/pages/1_🔴_Mundial_en_vivo.py`

- [ ] **Step 1: Añadir el checkbox de override en el sidebar**

En `pages/1_🔴_Mundial_en_vivo.py`, tras el caption de aviso de estrategia activa
(la línea `st.sidebar.caption("⚠️ Si hay una **estrategia activa**...")`), añadir:
```python
override_active = st.sidebar.checkbox(
    "Ignorar estrategia activa (override manual)", value=False,
    key="live_override")
```

- [ ] **Step 2: Respetar el override en la resolución de params**

Reemplazar el bloque:
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
por:
```python
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
```

- [ ] **Step 3: Verificar que compila**

Run: `uv run python -m py_compile "pages/1_🔴_Mundial_en_vivo.py"`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add "pages/1_🔴_Mundial_en_vivo.py"
git commit -m "feat: live page manual override toggle for active strategy"
```

---

## Task 6: Documentación

**Files:**
- Modify: `app/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Actualizar `app/README.md`**

- En **Backtest** añadir: persiste la evolución (`RatingSnapshot`) tras cada corrida
  y permite **subir un ranking FIFA** en JSON.
- En **Mundial en vivo** añadir el toggle **"Ignorar estrategia activa"**.
- En el panel de **Cuotas reales** aclarar que la prob. del modelo usa un pipe
  entrenado con los **finalizados 2026**, y que el parser de Polymarket soporta
  mercados Yes/No "Will X beat Y" (emparejados por partido).

- [ ] **Step 2: Actualizar `CLAUDE.md`**

- En `src/ingest.py` añadir `clear_snapshots` a las firmas.
- En `ui_common.py` añadir `fifa_ranking`.
- Nota: "El Backtest persiste `RatingSnapshot` (clear+rewrite) tras cada corrida; el
  panel de cuotas del Simulador usa un pipe entrenado con finalizados 2026; la página
  en vivo permite override manual de la estrategia activa; `parse_polymarket` empareja
  mercados Yes/No por partido."

- [ ] **Step 3: Suite completa final**

Run: `uv run pytest -q`
Expected: PASS (todos, incluidos los nuevos de `clear_snapshots` y Polymarket Yes/No).

- [ ] **Step 4: Commit**

```bash
git add ../CLAUDE.md README.md
git commit -m "docs: document review improvements (snapshots, FIFA upload, 2026 model, override, polymarket yes/no)"
```

---

## Notas de verificación final

- `uv run pytest -q` verde (nuevos: `clear_snapshots`, `_parse_versus`, Polymarket Yes/No).
- `py_compile` OK en `app.py`, `ui_common.py` y las dos páginas modificadas.
- Snapshots: clear+rewrite → no acumulan entre recargas; visibles en la página Datos.
- `parse_polymarket` retrocompatible (2-outcomes sigue funcionando) + empareja Yes/No.
- Override en vivo: con estrategia activa y toggle on → usa los controles del sidebar.
