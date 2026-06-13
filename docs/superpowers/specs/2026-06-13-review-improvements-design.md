# Diseño — Mejoras de la revisión (5 ítems)

**Fecha:** 2026-06-13
**Estado:** Aprobado

## Objetivo

Cerrar los 5 puntos de la revisión: persistir snapshots, restaurar el uploader
FIFA, usar el modelo 2026 en el panel de cuotas, toggle de override de estrategia
en vivo, y endurecer el parser de Polymarket.

## Decisiones

| # | Mejora | Decisión |
|---|--------|----------|
| 1 | Persistir `RatingSnapshot` | **Automático tras el backtest**: borra los del torneo y reescribe |
| 2 | Uploader de ranking FIFA | Helper `fifa_ranking()` en `ui_common`; lo usa la página Backtest |
| 3 | Modelo 2026 en panel de cuotas | El panel entrena un pipe con los **finalizados 2026** (de la DB) |
| 4 | Override de estrategia en vivo | Checkbox "Ignorar estrategia activa (override manual)" |
| 5 | Parser Polymarket robusto | Soporta mercados **Yes/No "Will X win"** emparejados por partido, con fixtures |

## #1 — Persistir snapshots (`src/ingest.py` + `app.py`)

- Nueva `clear_snapshots(session, tournament) -> int` (borra `RatingSnapshot` del
  torneo, devuelve nº borrado).
- En `app.py`, tras `pipe.process_all(matches)`: abrir sesión, `clear_snapshots` +
  `persist_snapshots` para "Qatar 2022". Delete+insert → no acumula entre recargas.
- Test: `clear_snapshots` borra; tras `persist_snapshots` la tabla tiene filas.

## #2 — Uploader FIFA (`src/ui_common.py` + `app.py`)

```python
def fifa_ranking() -> dict[str, float]:
    """Sidebar 'Ranking FIFA': snapshot incluido o JSON subido {equipo: puntos}.
    Devuelve el dict de puntos FIFA. Key del radio: 'fifa_source'."""
```
- `app.py` reemplaza `fifa_points = FIFA_SNAPSHOT_EXAMPLE` por `fifa_points = fifa_ranking()`.
- Otras páginas siguen con el snapshot por defecto (el `file_uploader` no se comparte
  limpio entre páginas).

## #3 — Modelo 2026 en el panel de cuotas (`pages/2_💰_Simulador_Apuestas.py`)

- En la sección "Cuotas reales", construir `pipe_live` con los **finalizados 2026**
  (`load_matches(s, wc)`): `Pipeline` sembrado con FIFA, `process_all(finished_2026)`.
  Si no hay finalizados, queda con ratings iniciales (FIFA).
- La columna "modelo P(home)" y "valor" usan `pipe_live.prematch_rec` (no el pipe de
  Qatar). Caption actualizada.

## #4 — Override de estrategia en vivo (`pages/1_🔴_Mundial_en_vivo.py`)

- Checkbox `override = st.sidebar.checkbox("Ignorar estrategia activa (override manual)")`.
- Resolución de `params`: si hay estrategia activa **y no** `override` → usar la activa;
  si `override` o no hay activa → usar `BetParams(sizing=..., use_bayes_filter=..., **common)`.
- Banner refleja el modo (activa vs override manual).

## #5 — Parser Polymarket robusto (`src/odds.py`)

`parse_polymarket` soporta dos formas (y las combina):
1. **Mercado de 2 outcomes = equipos** (actual): `outcomes=[A,B]`, `outcomePrices=[pa,pb]`.
2. **Mercados Yes/No "Will X win"**: `question` contiene el partido; el outcome "Yes"
   da P(equipo gana). Se extraen `(equipo, rival)` de la pregunta con regex y se
   **emparejan** los dos mercados del mismo partido (clave = `frozenset{equipo,rival}`)
   en un único `OddsQuote` (home = el primero visto).
- Helper `_parse_versus(question) -> (team, opponent) | None` con patrones:
  "Will <T> beat <O>", "Will <T> win vs <O>", "<T> vs <O>".
- Degradación: mercados no parseables se ignoran. Tested con fixtures de ambas formas
  y del caso Yes/No emparejado.

## Tests

- `tests/test_ingest.py`: `clear_snapshots` borra y `persist_snapshots` repuebla.
- `tests/test_odds.py`: `parse_polymarket` con (a) 2-outcomes (ya existe), (b) dos
  mercados Yes/No "Will Argentina beat France" + "Will France beat Argentina" →
  un `OddsQuote` con ambas cuotas; (c) `_parse_versus` patrones.
- UI (#2/#3/#4): `py_compile` + smoke sin red.

## Fuera de alcance (YAGNI)

- Validar selectores Codere / endpoint Polymarket contra la red (queda best-effort).
- Compartir el uploader FIFA entre páginas (solo Backtest).
- Histórico/curva de snapshots en una vista (solo se persisten; se ven en Datos).
