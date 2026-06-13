# Simulador de apuestas (backtest Winners) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir una página Streamlit que hace backtest de apuestas al ganador sobre el Mundial, con bet size dinámico, arranque en jornada 2 y una meta-estrategia configurable (criterio de lado Elo/Bayes/blend + filtro Bayes), comparando "apostar a todos" vs "solo Bayes > umbral".

**Architecture:** El `Pipeline` expone un `match_log` con la foto pre-partido (prob Elo, medias Bayes, nº de partido por equipo, resultado). Un motor puro `src/betting.py` consume ese log y simula el bankroll según `BetParams`. Una página `app/pages/` arma el pipeline desde la DB y muestra KPIs comparados + curvas de bankroll en Altair. Toda la lógica numérica es pura y testeable; la página solo orquesta y dibuja.

**Tech Stack:** Python 3.11+, dataclasses, SQLModel/SQLite (datos), Streamlit multipage + Altair (UI), pytest.

**Working dir:** Todos los comandos desde `app/`.

---

## File Structure

| Archivo | Responsabilidad |
|---------|-----------------|
| `app/src/pipeline.py` | + `match_log` con foto pre-partido por partido |
| `app/src/betting.py` | NUEVO — `BetParams`, `pick_side`, `stake_amount`, `simulate` (puro) |
| `app/pages/2_💰_Simulador_Apuestas.py` | NUEVO — página Streamlit del simulador |
| `app/tests/test_pipeline.py` | + test de `match_log` |
| `app/tests/test_betting.py` | NUEVO — tests del motor de apuestas |

Nota: al crear `app/pages/`, Streamlit convierte `app.py` en la página principal y
lista las páginas de `pages/` en la barra lateral automáticamente. No hay que
cambiar `app.py`.

---

## Task 1: `Pipeline.match_log` (foto pre-partido)

**Files:**
- Modify: `app/src/pipeline.py`
- Test: `app/tests/test_pipeline.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir al final de `app/tests/test_pipeline.py`:
```python
def test_match_log_prematch_snapshot():
    p = Pipeline()
    p.seed(FIFA_SNAPSHOT_EXAMPLE)
    p.process_all(QATAR_2022_SAMPLE)
    log = p.match_log
    assert len(log) == len(QATAR_2022_SAMPLE)

    first = log[0]  # ("2022-11-20", "group", "Qatar", "Ecuador", 0, 2)
    assert first["home"] == "Qatar" and first["away"] == "Ecuador"
    assert first["home_match_no"] == 1 and first["away_match_no"] == 1
    # Ecuador ganó 2-0
    assert first["home_win"] is False and first["away_win"] is True
    # Bayes pre-partido del 1er partido == media del prior (seed_from_elo)
    from src.bayes import elo_to_prior, BetaBelief
    a, b = elo_to_prior(p.initial_elo["Qatar"])
    assert abs(first["bayes_home"] - BetaBelief(a, b).mean) < 1e-9
    # p_home es una probabilidad
    assert 0.0 < first["p_home"] < 1.0

    # Argentina perdió su 1er partido (vs Saudi Arabia) -> match_no incrementa luego
    arg_matches = [r for r in log
                   if r["home"] == "Argentina" or r["away"] == "Argentina"]
    nos = [r["home_match_no"] if r["home"] == "Argentina" else r["away_match_no"]
           for r in arg_matches]
    assert nos == [1, 2, 3, 4, 5, 6]
```

- [ ] **Step 2: Correr el test para verlo fallar**

Run: `uv run pytest tests/test_pipeline.py::test_match_log_prematch_snapshot -q`
Expected: FAIL con `AttributeError: 'Pipeline' object has no attribute 'match_log'`.

- [ ] **Step 3: Implementar `match_log` en `app/src/pipeline.py`**

Añadir dos campos al dataclass `Pipeline` (junto a los demás `field(...)`):
```python
    match_log: list[dict] = field(default_factory=list)
    _appearances: dict[str, int] = field(default_factory=dict)
```

Reemplazar el cuerpo de `process_match` por (mantiene el comportamiento previo y
añade el log pre-partido):
```python
    def process_match(self, home: str, away: str, hg: int, ag: int,
                      stage: str = "group", date: str | None = None) -> dict:
        # 1) prediccion ANTES de actualizar (para calibracion + apuestas)
        p_home = expected_score(self.elo.get(home), self.elo.get(away))
        s_home, _ = match_scores(hg, ag)
        self.pred_probs.append(p_home)
        self.pred_outcomes.append(s_home)
        # foto Bayes pre-partido y numero de aparicion por equipo
        bayes_home = self.bayes.get(home).mean
        bayes_away = self.bayes.get(away).mean
        self._appearances[home] = self._appearances.get(home, 0) + 1
        self._appearances[away] = self._appearances.get(away, 0) + 1
        self.match_log.append({
            "date": date, "stage": stage, "home": home, "away": away,
            "p_home": p_home,
            "bayes_home": bayes_home, "bayes_away": bayes_away,
            "home_goals": hg, "away_goals": ag,
            "home_win": hg > ag, "away_win": ag > hg,
            "home_match_no": self._appearances[home],
            "away_match_no": self._appearances[away],
        })
        # 2) actualizar ambos sistemas
        rec = self.elo.update_match(home, away, hg, ag, stage=stage, match_date=date)
        self.bayes.update_match(home, away, hg, ag)
        rec["pred_home_win"] = p_home
        return rec
```

- [ ] **Step 4: Correr el test para verlo pasar**

Run: `uv run pytest tests/test_pipeline.py -q`
Expected: PASS (8 tests, incluido el nuevo).

- [ ] **Step 5: Commit**

```bash
git add src/pipeline.py tests/test_pipeline.py
git commit -m "feat: Pipeline.match_log with pre-match snapshot for betting"
```

---

## Task 2: Motor de apuestas `src/betting.py` — `BetParams` y `pick_side`

**Files:**
- Create: `app/src/betting.py`
- Test: `app/tests/test_betting.py`

- [ ] **Step 1: Escribir los tests que fallan**

Create `app/tests/test_betting.py`:
```python
"""Tests del motor puro de apuestas."""
from src.betting import BetParams, pick_side, stake_amount, simulate


def rec(home="A", away="B", p_home=0.7, bayes_home=0.6, bayes_away=0.4,
        home_win=True, away_win=False, home_match_no=2, away_match_no=2):
    return {"date": "d", "stage": "group", "home": home, "away": away,
            "p_home": p_home, "bayes_home": bayes_home, "bayes_away": bayes_away,
            "home_goals": 1, "away_goals": 0,
            "home_win": home_win, "away_win": away_win,
            "home_match_no": home_match_no, "away_match_no": away_match_no}


def test_pick_side_elo_picks_favorite():
    side, p_pick, bayes_pick, mno = pick_side(rec(p_home=0.7), "elo", 0.5)
    assert side == "home" and abs(p_pick - 0.7) < 1e-9
    side, p_pick, _, _ = pick_side(rec(p_home=0.3), "elo", 0.5)
    assert side == "away" and abs(p_pick - 0.7) < 1e-9


def test_pick_side_bayes_picks_higher_mean():
    side, p_pick, bayes_pick, _ = pick_side(
        rec(p_home=0.7, bayes_home=0.3, bayes_away=0.8), "bayes", 0.5)
    assert side == "away"               # away tiene mayor Bayes
    assert abs(bayes_pick - 0.8) < 1e-9
    assert abs(p_pick - 0.3) < 1e-9     # p_pick sigue siendo prob Elo del lado


def test_pick_side_blend_respects_weight():
    # home: elo 0.55, bayes 0.20 ; away: elo 0.45, bayes 0.80
    r = rec(p_home=0.55, bayes_home=0.20, bayes_away=0.80)
    # w=1.0 -> solo Elo -> home (0.55 > 0.45)
    assert pick_side(r, "blend", 1.0)[0] == "home"
    # w=0.0 -> solo Bayes -> away (0.80 > 0.20)
    assert pick_side(r, "blend", 0.0)[0] == "away"
```

- [ ] **Step 2: Correr para verlo fallar**

Run: `uv run pytest tests/test_betting.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.betting'`.

- [ ] **Step 3: Implementar `BetParams` y `pick_side` en `app/src/betting.py`**

```python
"""
Motor puro de backtest de apuestas al ganador (sin Streamlit).

Consume el match_log del Pipeline (foto pre-partido) y simula la evolución del
bankroll según BetParams. La meta-estrategia es configurable: el criterio de
selección de lado (elo|bayes|blend), el filtro de Bayes, el sizing y la cuota.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class BetParams:
    bankroll0: float = 1000.0
    odds: float = 2.0
    sizing: str = "flat"          # 'flat' | 'confidence' | 'kelly'
    base_fraction: float = 0.05   # fracción del bankroll para flat/confidence
    kelly_fraction: float = 0.25  # fracción de Kelly aplicada
    start_match_no: int = 2       # arranca en la 2ª aparición del lado elegido
    side_criterion: str = "elo"   # 'elo' | 'bayes' | 'blend'
    blend_weight: float = 0.5     # peso de Elo en 'blend' (1-w para Bayes)
    use_bayes_filter: bool = False
    bayes_threshold: float = 0.5


def pick_side(rec: dict, side_criterion: str, blend_weight: float
              ) -> tuple[str, float, float, int]:
    """
    Devuelve (side, p_pick, bayes_pick, match_no) para el partido.
    p_pick = prob. Elo del lado elegido (estimación de P(ganar)).
    bayes_pick = media Bayes pre-partido del lado elegido.
    """
    p_home = rec["p_home"]
    elo_home, elo_away = p_home, 1.0 - p_home
    bayes_home, bayes_away = rec["bayes_home"], rec["bayes_away"]

    if side_criterion == "bayes":
        home_score, away_score = bayes_home, bayes_away
    elif side_criterion == "blend":
        w = blend_weight
        home_score = w * elo_home + (1 - w) * bayes_home
        away_score = w * elo_away + (1 - w) * bayes_away
    else:  # 'elo'
        home_score, away_score = elo_home, elo_away

    if home_score >= away_score:
        return "home", elo_home, bayes_home, rec["home_match_no"]
    return "away", elo_away, bayes_away, rec["away_match_no"]
```

- [ ] **Step 4: Correr los tests de pick_side**

Run: `uv run pytest tests/test_betting.py -q`
Expected: los 3 tests de `pick_side` PASAN. (Los de `stake_amount`/`simulate` aún
no existen.)

- [ ] **Step 5: Commit**

```bash
git add src/betting.py tests/test_betting.py
git commit -m "feat: betting engine BetParams + configurable pick_side"
```

---

## Task 3: `stake_amount` (3 métodos de sizing)

**Files:**
- Modify: `app/src/betting.py`
- Test: `app/tests/test_betting.py`

- [ ] **Step 1: Añadir los tests que fallan**

Agregar a `app/tests/test_betting.py`:
```python
def test_stake_flat():
    p = BetParams(sizing="flat", base_fraction=0.05)
    assert abs(stake_amount(p, 1000.0, 0.7) - 50.0) < 1e-9


def test_stake_confidence_scales_with_p():
    p = BetParams(sizing="confidence", base_fraction=0.10)
    # conf = clip((0.75-0.5)*2,0,1) = 0.5 -> 0.10*1000*0.5 = 50
    assert abs(stake_amount(p, 1000.0, 0.75) - 50.0) < 1e-9
    # p<=0.5 -> conf 0 -> stake 0
    assert stake_amount(p, 1000.0, 0.5) == 0.0


def test_stake_kelly_zero_without_edge():
    p = BetParams(sizing="kelly", odds=2.0, kelly_fraction=1.0)
    # odds 2.0 -> b=1 -> edge requiere p>0.5; p=0.5 -> f*=0
    assert stake_amount(p, 1000.0, 0.5) == 0.0
    assert stake_amount(p, 1000.0, 0.4) == 0.0


def test_stake_kelly_positive_with_edge():
    p = BetParams(sizing="kelly", odds=2.0, kelly_fraction=1.0)
    # b=1, p=0.7 -> f* = (1*0.7 - 0.3)/1 = 0.4 -> 0.4*1000 = 400
    assert abs(stake_amount(p, 1000.0, 0.7) - 400.0) < 1e-9
    # con kelly_fraction 0.25 -> 100
    p2 = BetParams(sizing="kelly", odds=2.0, kelly_fraction=0.25)
    assert abs(stake_amount(p2, 1000.0, 0.7) - 100.0) < 1e-9
```

- [ ] **Step 2: Correr para verlo fallar**

Run: `uv run pytest tests/test_betting.py -k stake -q`
Expected: FAIL con `ImportError`/`AttributeError` (`stake_amount` no definido aún).

- [ ] **Step 3: Implementar `stake_amount` en `app/src/betting.py`**

Añadir tras `pick_side`:
```python
def stake_amount(params: BetParams, bankroll: float, p_pick: float) -> float:
    """Monto a apostar según el método de sizing (>= 0)."""
    if params.sizing == "confidence":
        conf = (p_pick - 0.5) * 2.0
        conf = min(max(conf, 0.0), 1.0)
        return params.base_fraction * bankroll * conf
    if params.sizing == "kelly":
        b = params.odds - 1.0
        if b <= 0:
            return 0.0
        f_star = (b * p_pick - (1.0 - p_pick)) / b
        f_star = max(f_star, 0.0) * params.kelly_fraction
        return f_star * bankroll
    # 'flat' (default)
    return params.base_fraction * bankroll
```

- [ ] **Step 4: Correr los tests de stake**

Run: `uv run pytest tests/test_betting.py -k stake -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/betting.py tests/test_betting.py
git commit -m "feat: stake_amount with flat/confidence/kelly sizing"
```

---

## Task 4: `simulate` (motor de backtest)

**Files:**
- Modify: `app/src/betting.py`
- Test: `app/tests/test_betting.py`

- [ ] **Step 1: Añadir los tests que fallan**

Agregar a `app/tests/test_betting.py`:
```python
def test_simulate_settlement_and_skips():
    log = [
        rec(home="A", away="B", p_home=0.7, home_win=True, away_win=False,
            home_match_no=1, away_match_no=1),   # jornada 1 -> se salta
        rec(home="A", away="C", p_home=0.7, home_win=True, away_win=False,
            home_match_no=2, away_match_no=1),   # apuesta a A (gana)
        rec(home="A", away="D", p_home=0.7, home_win=False, away_win=True,
            home_match_no=3, away_match_no=1),   # apuesta a A (pierde)
    ]
    p = BetParams(bankroll0=1000.0, odds=2.0, sizing="flat", base_fraction=0.10,
                  start_match_no=2, side_criterion="elo", use_bayes_filter=False)
    out = simulate(log, p)
    # 2 apuestas (la jornada 1 se salta). Apuesta1: 100 -> +100 (1100).
    # Apuesta2: 110 (10% de 1100) -> -110 (990).
    assert out["n_bets"] == 2
    assert out["wins"] == 1
    assert abs(out["bankroll_final"] - 990.0) < 1e-6
    assert abs(out["total_staked"] - 210.0) < 1e-6
    assert len(out["curve"]) == out["n_bets"] + 1  # incluye punto inicial


def test_simulate_bayes_filter_reduces_bets():
    log = [
        rec(home="A", away="B", p_home=0.7, bayes_home=0.40,
            home_win=True, away_win=False, home_match_no=2, away_match_no=2),
        rec(home="A", away="C", p_home=0.7, bayes_home=0.65,
            home_win=True, away_win=False, home_match_no=3, away_match_no=2),
    ]
    base = dict(bankroll0=1000.0, odds=2.0, sizing="flat", base_fraction=0.10,
                start_match_no=2, side_criterion="elo")
    no_filter = simulate(log, BetParams(use_bayes_filter=False, **base))
    filtered = simulate(log, BetParams(use_bayes_filter=True,
                                       bayes_threshold=0.5, **base))
    assert no_filter["n_bets"] == 2
    assert filtered["n_bets"] == 1   # solo el segundo (bayes 0.65 > 0.5)


def test_simulate_stake_never_exceeds_bankroll():
    log = [rec(home="A", away="B", p_home=0.99, home_win=False, away_win=True,
               home_match_no=2, away_match_no=2)]
    p = BetParams(bankroll0=100.0, odds=2.0, sizing="flat", base_fraction=2.0,
                  start_match_no=2)
    out = simulate(log, p)
    # base_fraction 2.0 pediría 200 pero el bankroll es 100 -> apuesta 100 y pierde
    assert abs(out["bankroll_final"] - 0.0) < 1e-6
    assert abs(out["total_staked"] - 100.0) < 1e-6
```

- [ ] **Step 2: Correr para verlo fallar**

Run: `uv run pytest tests/test_betting.py -k simulate -q`
Expected: FAIL (`simulate` no definido aún).

- [ ] **Step 3: Implementar `simulate` en `app/src/betting.py`**

Añadir tras `stake_amount`:
```python
def simulate(match_log: list[dict], params: BetParams) -> dict:
    """Recorre el log y simula el bankroll. Devuelve métricas + curva + apuestas."""
    bankroll = params.bankroll0
    peak = bankroll
    max_dd = 0.0
    bets: list[dict] = []
    curve = [{"bet_no": 0, "bankroll": bankroll}]
    total_staked = 0.0
    wins = 0

    for rec in match_log:
        side, p_pick, bayes_pick, match_no = pick_side(
            rec, params.side_criterion, params.blend_weight)
        if match_no < params.start_match_no:
            continue
        if params.use_bayes_filter and bayes_pick < params.bayes_threshold:
            continue
        stake = min(stake_amount(params, bankroll, p_pick), bankroll)
        if stake <= 0:
            continue

        won = rec["home_win"] if side == "home" else rec["away_win"]
        if won:
            bankroll += stake * (params.odds - 1.0)
            wins += 1
        else:
            bankroll -= stake
        total_staked += stake

        peak = max(peak, bankroll)
        max_dd = max(max_dd, peak - bankroll)
        bets.append({
            "date": rec["date"], "match": f'{rec["home"]} vs {rec["away"]}',
            "side": side, "pick": rec[side], "p_pick": round(p_pick, 4),
            "bayes_pick": round(bayes_pick, 4), "stake": round(stake, 2),
            "won": won, "bankroll": round(bankroll, 2),
        })
        curve.append({"bet_no": len(bets), "bankroll": bankroll})

    n_bets = len(bets)
    profit = bankroll - params.bankroll0
    return {
        "bankroll_final": bankroll,
        "profit": profit,
        "roi": profit / params.bankroll0 if params.bankroll0 else 0.0,
        "n_bets": n_bets,
        "wins": wins,
        "win_rate": wins / n_bets if n_bets else 0.0,
        "total_staked": total_staked,
        "yield": profit / total_staked if total_staked else 0.0,
        "max_drawdown": max_dd,
        "curve": curve,
        "bets": bets,
    }
```

Nota: `rec[side]` usa que cada record tiene claves `"home"` y `"away"`, así
`rec["home"]`/`rec["away"]` da el nombre del equipo apostado.

- [ ] **Step 4: Correr todos los tests de betting**

Run: `uv run pytest tests/test_betting.py -q`
Expected: PASS (10 tests).

- [ ] **Step 5: Correr la suite completa**

Run: `uv run pytest -q`
Expected: PASS (todos).

- [ ] **Step 6: Commit**

```bash
git add src/betting.py tests/test_betting.py
git commit -m "feat: simulate() backtest engine with metrics + bankroll curve"
```

---

## Task 5: Página Streamlit del simulador

**Files:**
- Create: `app/pages/2_💰_Simulador_Apuestas.py`

- [ ] **Step 1: Crear la página**

```python
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
```

- [ ] **Step 2: Verificar que compila**

Run: `uv run python -m py_compile pages/2_💰_Simulador_Apuestas.py`
Expected: sin salida (exit 0).

- [ ] **Step 3: Smoke test del flujo de datos (sin Streamlit)**

Run:
```bash
uv run python -c "
from src.pipeline import Pipeline
from src.elo import EloSystem
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE
from src.qatar_fixture import QATAR_2022_SAMPLE
from src.betting import BetParams, simulate
p = Pipeline(elo=EloSystem(k=40.0, use_margin=True))
p.seed(FIFA_SNAPSHOT_EXAMPLE)
p.bayes.seed_from_elo(p.initial_elo, strength=4.0)
p.process_all(QATAR_2022_SAMPLE)
a = simulate(p.match_log, BetParams(use_bayes_filter=False))
b = simulate(p.match_log, BetParams(use_bayes_filter=True, bayes_threshold=0.5))
print('todos:', a['n_bets'], 'apuestas, ROI', round(a['roi']*100,1), '%')
print('filtro:', b['n_bets'], 'apuestas, ROI', round(b['roi']*100,1), '%')
assert a['n_bets'] >= b['n_bets']
"
```
Expected: imprime nº de apuestas y ROI de ambas estrategias; `todos` ≥ `filtro` en
nº de apuestas. Sin excepciones.

- [ ] **Step 4: Smoke test manual (opcional)**

Run: `uv run streamlit run app.py`
Expected: en la barra lateral aparece la página "Simulador Apuestas"; al abrirla
muestra KPIs comparados, la curva de bankroll de ambas estrategias y las tablas.
Cerrar con Ctrl+C.

- [ ] **Step 5: Commit**

```bash
git add pages/2_💰_Simulador_Apuestas.py
git commit -m "feat: add betting simulator Streamlit page (multipage)"
```

---

## Task 6: Documentación

**Files:**
- Modify: `app/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Actualizar `app/README.md`**

Añadir a la sección "Estructura" las líneas:
```
src/betting.py                  # motor puro de backtest de apuestas
pages/2_💰_Simulador_Apuestas.py # página Streamlit del simulador (multipage)
```
Y un párrafo corto en "Cómo correrlo" indicando que, al correr
`uv run streamlit run app.py`, la barra lateral muestra la página
**Simulador de apuestas** (backtest de dos estrategias con bet sizing dinámico).

- [ ] **Step 2: Actualizar `CLAUDE.md`**

Añadir a la tabla de arquitectura:
```
| [app/src/betting.py](app/src/betting.py) | Motor puro de backtest de apuestas: `BetParams`, `pick_side`, `stake_amount`, `simulate` |
| [app/pages/](app/pages/) | Páginas Streamlit extra (multipage): simulador de apuestas |
```
Y una frase: "El simulador de apuestas consume `Pipeline.match_log` (foto
pre-partido) vía el motor puro `src/betting.py`."

- [ ] **Step 3: Verificar suite completa**

Run: `uv run pytest -q`
Expected: PASS (todos).

- [ ] **Step 4: Commit**

```bash
git add ../CLAUDE.md README.md
git commit -m "docs: document betting simulator page and engine"
```

---

## Notas de verificación final

- `uv run pytest -q` verde (pipeline + models + ingest + betting).
- `uv run python -m py_compile pages/2_💰_Simulador_Apuestas.py` sin errores.
- El motor `src/betting.py` no importa Streamlit (es puro y testeable).
- La página recalcula todo en memoria; no persiste apuestas en la DB.
- Las dos estrategias comparten `BetParams` salvo `use_bayes_filter`.
