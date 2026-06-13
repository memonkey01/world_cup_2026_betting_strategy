# Diseño — Split en páginas (Backtest / Mundial en vivo) + recomendaciones en vivo

**Fecha:** 2026-06-13
**Estado:** Aprobado

## Objetivo

Dividir la app en páginas: **Backtest** (monitor Elo/Bayes sobre Qatar) y
**Mundial en vivo** (scrapea ESPN, muestra datos extraídos, vista tipo calendario
y recomienda apuestas para los partidos programados). Los parámetros se comparten
entre páginas (concordancia). Se conserva el **Simulador de apuestas**.

## Decisiones

| Tema | Decisión |
|------|----------|
| Estructura | 3 páginas: `app.py` = 📊 Backtest; `pages/1_🔴_Mundial_en_vivo.py` (nueva); `pages/2_💰_Simulador_Apuestas.py` (se conserva, realineada) |
| Parámetros | Compartidos vía `session_state` (widgets con `key=` fijos en helpers comunes) |
| En vivo | Por cada partido **programado**: lado + stake recomendado, con el modelo entrenado con lo ya jugado |
| Botones | Sizing **Flat / Confianza / Kelly**; criterio de lado, cuota y umbral se heredan del backtest |
| Persistencia | **Todo en la DB**: finalizados *y* calendario (programados). El scrape hace upsert; la página lee de la DB. |
| Modo demo | **No** (descartado). Sin red, la página lee el calendario ya guardado en la DB. |

## Estructura de páginas

```
app/
├── app.py                          # 📊 Backtest (Qatar): monitor Elo/Bayes/calibración
├── ui_common.py                    # NUEVO — controles de sidebar compartidos (session_state)
├── pages/
│   ├── 1_🔴_Mundial_en_vivo.py     # NUEVO — scrape ESPN + calendario + recomendaciones
│   └── 2_💰_Simulador_Apuestas.py  # se conserva; usa ui_common para concordancia
└── src/ ...                         # lógica pura (sin cambios salvo lo de abajo)
```

Streamlit toma `app.py` como página principal y lista `pages/` ordenadas por
nombre de archivo.

## UI compartida — `app/ui_common.py`

Helpers que dibujan widgets con `key=` fijos; como `session_state` es compartido
entre páginas, configurar en una deja iguales las demás.

```python
def model_controls() -> tuple[float, float, bool]:
    """Sidebar 'Modelo': K, fuerza del prior, multiplicador por margen.
    Keys: k_factor, prior_strength, use_margin. Devuelve (k, prior, margin)."""

def betting_controls() -> dict:
    """Sidebar 'Apuestas': bankroll, cuota, start_match_no, base_fraction,
    kelly_fraction, side_criterion, blend_weight, bayes_threshold (con keys).
    Devuelve un dict 'common' listo para BetParams (sin 'sizing' ni filtro)."""
```

Cada página decide el `sizing` (botones en vivo / selectbox en simulador) y
arma `BetParams(**common, sizing=..., use_bayes_filter=...)`.

## Persistencia del calendario (DB = fuente de verdad de todo)

La DB guarda **todos** los partidos: finalizados y programados (el calendario).

- `Match.home_goals` y `Match.away_goals` pasan a **`int | None`** (None para
  programados, que aún no tienen marcador). `Match.finished` ya depende de `status`.
- `ingest_calendar(session, tournament, results)` (nuevo, en `src/ingest.py`):
  persiste **todos** los `MatchResult` (finalizados + programados) con upsert por
  `espn_event_id`. Al re-scrapear, un partido que pasó de programado a finalizado
  se **actualiza** (status + goles). Para programados, goles = None.
- `load_matches(session, tournament)` pasa a devolver **solo finalizados** (los que
  alimentan el Pipeline) filtrando por `status in FINISHED_STATUSES`. El backtest no
  cambia (sus partidos son todos finalizados).
- `load_calendar(session, tournament)` (nuevo): devuelve **todos** los partidos
  ordenados por fecha (con status y goles) para la vista calendario.

## Capa lógica (pura, testeable)

### `Pipeline.prematch_rec(home, away)` (en `src/pipeline.py`)
Foto pre-partido para un juego **hipotético** con el estado actual, sin actualizar:
```python
{
  "home", "away",
  "p_home",                         # expected_score(elo[home], elo[away])
  "bayes_home", "bayes_away",       # medias Bayes actuales
  "home_match_no", "away_match_no", # _appearances[t] + 1
}
```

### `betting.recommend_bet(rec, bankroll, params)` (en `src/betting.py`)
Recomendación para **un** partido próximo:
```python
{
  "side", "pick",        # 'home'/'away' y nombre del equipo (rec[side])
  "p_pick", "bayes_pick", "match_no",
  "stake",               # 0.0 si no se apuesta
  "skip_warmup",         # match_no < start_match_no
  "filtered_out",        # use_bayes_filter y bayes_pick < bayes_threshold
  "bet",                 # stake > 0
}
```
Reusa `pick_side` y `stake_amount`. `stake = min(stake_amount(...), bankroll)`
solo si no hay skip/filtro; si no, 0.

## `app.py` → solo Backtest

Se elimina el modo "En vivo 2026" y su rama de scraping. Queda el monitor de
Qatar 2022 (tabla, evolución Elo, Bayes, calibración, evolución combinada),
sembrando la DB con el fixture. Usa `ui_common.model_controls()`. Título
"📊 Backtest — Mundial (Qatar 2022)".

## `pages/1_🔴_Mundial_en_vivo.py`

Flujo:
1. Sidebar: `model_controls()` + `betting_controls()` heredados + **botones de
   sizing** `[Flat | Confianza | Kelly]` (estado en `session_state["live_sizing"]`)
   + rango de fechas ESPN + selector de scraper (Playwright / requests).
2. Botón "Actualizar (scrape ESPN)": llama al scraper para el rango → lista de
   `MatchResult` (finalizados + programados) y los persiste **todos** vía
   `ingest_calendar` (torneo "World Cup 2026"), haciendo upsert.
3. **Lee de la DB** (no del scrape transitorio): `load_calendar` para la vista y
   `load_matches` (solo finalizados) para entrenar el modelo. Así el calendario
   persiste entre sesiones aunque no se vuelva a scrapear.
4. Entrena `Pipeline` con los finalizados de la DB usando K/prior/margin compartidos.
5. **Vista calendario:** partidos agrupados por fecha (desde la DB). Finalizados con
   marcador; programados → `pipe.prematch_rec(home, away)` → `recommend_bet(...)`
   mostrando a quién apostar y cuánto (o "— sin apuesta" si warm-up/filtro).
6. Si la DB no tiene calendario aún y el scrape no devuelve nada (sin red / fuera de
   fechas), `st.info` explicativo invitando a pulsar "Actualizar".

## Simulador (realineado)

`pages/2_💰_Simulador_Apuestas.py` usa `ui_common.model_controls()` y
`betting_controls()` para que sus parámetros concuerden con backtest y vivo; el
sizing sigue como selectbox propio de esa página.

## Tests

- `tests/test_betting.py`: `recommend_bet` — apuesta con stake>0 cuando pasa;
  `skip_warmup` si `match_no < start_match_no`; `filtered_out` si Bayes < umbral;
  `stake` nunca excede el bankroll.
- `tests/test_pipeline.py`: `prematch_rec` — `match_no == apariciones+1`,
  `p_home ∈ (0,1)`, medias Bayes presentes.
- `tests/test_ingest.py`: payload ESPN con un evento `STATUS_SCHEDULED` y uno
  `STATUS_FULL_TIME` → `ingest_calendar` persiste ambos; `load_calendar` los
  devuelve todos y `load_matches` solo el finalizado. Re-scrape donde el programado
  pasa a finalizado → se actualiza (status + goles), sin duplicar (dedup event_id).
- `tests/test_pipeline.py`: `prematch_rec` — `match_no == apariciones+1`,
  `p_home ∈ (0,1)`, medias Bayes presentes.
- Páginas: `py_compile` + smoke sin red que alimenta un payload sintético
  (finalizados + programados) por el flujo parse → ingest_calendar → load → pipeline
  → prematch_rec → recommend_bet.

## Fuera de alcance (YAGNI)

- Modo demo offline (descartado).
- Cuotas reales por partido (sigue cuota fija configurable).
