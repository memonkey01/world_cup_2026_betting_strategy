# Diseño — Laboratorio de estrategias → Producción

**Fecha:** 2026-06-13
**Estado:** Aprobado

## Objetivo

Cerrar el flujo de dos fases: en el **backtest de Qatar** barrer estrategias y
encontrar la mejor por *yield*; **fijarla** en la DB; y que la página **en vivo**
recomiende con esa estrategia activa. Concordancia garantizada porque la estrategia
vive en la DB, no en sliders sueltos.

## Decisiones

| Tema | Decisión |
|------|----------|
| Búsqueda | Barrido sobre `sizing {flat,confidence,kelly} × criterio {elo,bayes,blend} × filtro {off,on}` (18 combos) |
| Métrica | **Yield** (profit / total apostado) — ranking descendente |
| Fijar | Guardar la ganadora en la DB (modelo `Strategy`, una activa) |
| Ubicación | Ampliar el **💰 Simulador** a laboratorio (barrido + ranking + fijar) |

## Capa pura — `src/betting.py`

```python
def sweep_strategies(match_log, base: BetParams) -> list[dict]:
    """Barre sizing × side_criterion × use_bayes_filter (18 combos) manteniendo
    el resto de `base` fijo. Corre simulate() en cada uno. Devuelve filas
    {sizing, side_criterion, use_bayes_filter, params, metrics} ordenadas por
    yield desc (desempate: roi desc)."""
```
- `params` = `BetParams` resultante; `metrics` = el dict de `simulate` sin `curve`/`bets`.
- Reusa `simulate`; no toca Streamlit ni DB.

## Persistencia — `src/models.py` + `src/strategies.py`

### Modelo `Strategy` (en `models.py`)
Campos de `BetParams` + `label`, `active: bool`, `backtest_yield`, `backtest_roi`.

### `src/strategies.py` (puro/DB)
```python
def strategy_to_params(strategy: Strategy) -> BetParams      # Strategy -> BetParams
def save_active_strategy(session, params: BetParams, label, *, yield_, roi) -> Strategy
    # desactiva las previas (active=False) y guarda la nueva con active=True
def load_active_strategy(session) -> Strategy | None          # la única active=True
```

## Fase 1 — Laboratorio (`pages/2_💰_Simulador_Apuestas.py`)

- Mantiene los controles compartidos (`ui_common`) para los parámetros base
  (bankroll, cuota, fracciones, umbral, blend_weight, start_match_no).
- Corre `sweep_strategies(pipe.match_log, base)` sobre Qatar y muestra una **tabla
  rankeada por yield** (sizing, criterio, filtro, yield, ROI, nº apuestas, %acierto,
  drawdown).
- `selectbox` para elegir una fila (default: la #1). Botón **"Fijar como estrategia
  activa"** → `save_active_strategy(...)`. Muestra confirmación.
- Conserva la curva de bankroll de la estrategia seleccionada.

## Fase 2 — Producción (`pages/1_🔴_Mundial_en_vivo.py`)

- `load_active_strategy(session)`; si existe, banner "Estrategia activa: <label>
  (yield Qatar X%)" y se usa `strategy_to_params` para recomendar.
- Si no hay estrategia activa, usa los controles/botones actuales (fallback) y
  sugiere ir al laboratorio.
- Nota de *warm-up*: con `start_match_no` > nº de partidos jugados, los equipos
  aparecen como "aún en calentamiento" (no es bug).

## Tests

- `tests/test_betting.py`: `sweep_strategies` sobre un log sintético → 18 filas,
  ordenadas por yield desc, cada una con `params` (BetParams) y `metrics`.
- `tests/test_strategies.py`: `save_active_strategy` + `load_active_strategy`
  roundtrip (BetParams se reconstruye igual); fijar una segunda desactiva la primera
  (solo una `active`).

## Fuera de alcance (YAGNI)

- Barrido fino (umbral/fracciones/cuota) — el grid es 18 combos.
- Auto-fijar la #1 sin confirmación (se requiere botón).
- Optimización/seeds aleatorios; histórico de estrategias fijadas.
