# Diseño — Simulador de apuestas (backtest estilo Winners)

**Fecha:** 2026-06-12
**Estado:** Aprobado

## Objetivo

Página nueva (Streamlit multipage) que hace un backtest de apuestas al ganador
sobre el Mundial, con bet size dinámico, arranque en la jornada 2, y una
**meta-estrategia configurable** (criterio de selección de lado + filtro Bayes).
Compara dos estrategias: apostar a todos los partidos vs. solo a los que superan
un umbral de Bayes.

## Decisiones

| Tema | Decisión |
|------|----------|
| Cuotas | Decimal **fija configurable** (default 2.0). No hay cuotas reales en los datos. |
| Mercado | **Gana el equipo elegido** (1 o 2); empate o derrota = apuesta perdida. |
| Bet sizing | **3 métodos seleccionables**: flat %, proporcional a confianza, Kelly fraccional. |
| Criterio de lado | **Configurable** (meta-estrategia): `elo` \| `bayes` \| `blend`. |
| Filtro | Umbral de Bayes (on/off) → distingue las dos estrategias comparadas. |
| Arranque | `start_match_no=2` → no se apuesta el 1er partido del lado elegido (jornada 2). |
| Página | `app/pages/2_💰_Simulador_Apuestas.py` (app.py pasa a página principal). |

## Capa de datos — `Pipeline.match_log` (`src/pipeline.py`)

Log por partido con la foto **pre-partido** (antes de actualizar Elo/Bayes, sin
mirar el resultado para decidir):

```python
{
  "date", "stage", "home", "away",
  "p_home",                    # Elo expected_score(home, away) pre-match
  "bayes_home", "bayes_away",  # media Bayes pre-match de cada equipo
  "home_goals", "away_goals",
  "home_win", "away_win",      # hg>ag / ag>hg (empate -> ambos False)
  "home_match_no", "away_match_no",  # nº de partido de cada equipo (incluye este, 1-based)
}
```

Se llena en `process_match`, capturando las medias Bayes y la prob Elo antes de
`elo.update_match`/`bayes.update_match`, y un contador de apariciones por equipo.

## Motor — `src/betting.py` (puro, sin Streamlit)

```python
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
```

- `pick_side(rec, side_criterion, blend_weight) -> (side, p_pick, bayes_pick, match_no)`:
  - `elo`: home si `p_home ≥ 0.5`, si no away.
  - `bayes`: el equipo con mayor media Bayes pre-match.
  - `blend`: score_side = `w·p_elo_side + (1−w)·bayes_side`; elige el mayor.
  - En todos los casos `p_pick` = prob. **Elo** del lado elegido (`p_home` o `1−p_home`),
    `bayes_pick` = media Bayes pre-match del lado elegido, `match_no` = su nº de partido.
- `stake_amount(params, bankroll, p_pick)`:
  - `flat`: `base_fraction · bankroll`.
  - `confidence`: `base_fraction · bankroll · clip((p_pick−0.5)·2, 0, 1)`.
  - `kelly`: `b = odds−1`; `f* = (b·p_pick − (1−p_pick))/b`; `max(f*,0)·kelly_fraction·bankroll`.
- `simulate(match_log, params) -> dict`:
  - Salta si `match_no < start_match_no`.
  - Si `use_bayes_filter` y `bayes_pick < bayes_threshold`, salta.
  - `stake = min(stake_amount(...), bankroll)`; si `≤ 0`, salta.
  - Gana si el lado elegido ganó → `bankroll += stake·(odds−1)`; si no → `bankroll −= stake`.
  - Devuelve `{bankroll_final, profit, roi, n_bets, wins, win_rate, total_staked, yield, max_drawdown, curve, bets}`.

Las dos estrategias comparadas usan el **mismo** `BetParams` salvo `use_bayes_filter`
(False = "apostar a todos", True = "solo Bayes > umbral").

## Página — `app/pages/2_💰_Simulador_Apuestas.py`

- Carga partidos de "Qatar 2022" desde la DB (siembra si hace falta), arma el
  `Pipeline` (con k / prior configurables o por defecto) y obtiene `match_log`.
- Sidebar: bankroll inicial, cuota, método de sizing + fracciones, `start_match_no`
  (jornada), criterio de lado + `blend_weight`, umbral de Bayes.
- Corre `simulate` dos veces (filtro off/on) y muestra:
  - KPIs comparados lado a lado (ROI, bankroll final, nº apuestas, % acierto, yield, drawdown).
  - Curvas de bankroll (Altair, X = nº de apuesta).
  - Tabla de apuestas de cada estrategia.

## Tests

- `tests/test_betting.py`:
  - `stake_amount` por método (flat exacto; confidence escala con p; kelly=0 sin edge,
    kelly>0 con edge).
  - `pick_side`: `elo` elige favorito; `bayes` elige mayor media; `blend` respeta peso.
  - `simulate`: log sintético determinista — aritmética de liquidación (ganar/perder),
    `start_match_no` salta la jornada 1, `use_bayes_filter` reduce nº de apuestas,
    `stake` nunca excede el bankroll.
- `tests/test_pipeline.py`: `match_log` tiene Bayes pre-partido = prior en la 1ª
  aparición, `home_win`/`away_win` correctos, longitud = nº de partidos.

## Fuera de alcance (YAGNI)

- Mercados 1-X-2 reales / cuotas por resultado; cuotas reales de Winners.
- Métricas avanzadas (Sharpe, Sortino) — solo ROI/yield/drawdown.
- Persistir las apuestas en la DB (se recalculan en memoria).
