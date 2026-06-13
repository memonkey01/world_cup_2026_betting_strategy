# CLAUDE.md

Monitor **Elo + Bayes** para el Mundial de fútbol, con scraping de resultados
desde ESPN y dashboard en Streamlit. Predice/valida la fuerza de las selecciones
y calibra las probabilidades del modelo contra resultados reales.

Todo el código vive en [app/](app/) (paquete `src/`, entorno `uv`). Comentarios,
docstrings y README están en español. La base de datos SQLite
(`app/data/worldcup.db`) es la **fuente de verdad**: guarda los partidos
**finalizados y el calendario** (programados); el scraper la llena (upsert) y el
pipeline Elo/Bayes lee de ella.

## Qué hace

1. **Semilla FIFA → Elo.** El ranking FIFA (tipo-Elo desde 2018) se re-centra a
   la escala Elo clásica (~1500 media). Ver [app/fifa_seed.py](app/fifa_seed.py).
2. **Elo por rondas.** `R' = R + K·(S − E)` con empates estilo ajedrez
   (`S ∈ {1, 0.5, 0}`) y multiplicador opcional por margen de gol.
   Ver [app/elo.py](app/elo.py).
3. **Bayes binario (Beta-Bernoulli).** Cada equipo tiene `θ ~ Beta(a,b)` con
   prior anclado al Elo; cada partido es un Bernoulli (empate = 0.5 éxito);
   posterior conjugado → media + intervalo de credibilidad.
   Ver [app/bayes.py](app/bayes.py).
4. **Calibración.** Las probabilidades que el Elo emite *antes* de cada partido
   se contrastan contra resultados con Brier, LogLoss y curva de fiabilidad
   (también en [app/bayes.py](app/bayes.py)).

## Arquitectura

| Archivo | Rol |
|---------|-----|
| [app/src/elo.py](app/src/elo.py) | `EloSystem` + `expected_score`, `match_scores`, `margin_multiplier` |
| [app/src/bayes.py](app/src/bayes.py) | `BetaBelief`, `BayesianLeague` + métricas `brier_score`, `log_loss`, `reliability_bins` |
| [app/src/fifa_seed.py](app/src/fifa_seed.py) | `fifa_to_elo`, `load_fifa_ranking`, `FIFA_SNAPSHOT_EXAMPLE` |
| [app/src/scraper.py](app/src/scraper.py) | ESPN scoreboard API vía Playwright; `fetch_via_requests` fallback; `normalize_team` (`ESPN_NAME_MAP` + `ALT_NAME_MAP` homologa grafías Polymarket/intl)/`normalize_stage` |
| [app/src/qatar_fixture.py](app/src/qatar_fixture.py) | `QATAR_2022_SAMPLE` — resultados reales para backtest offline / fallback |
| [app/src/pipeline.py](app/src/pipeline.py) | `Pipeline` — orquesta seed → Elo + Bayes; `snapshots`, `match_log`, `team_evolution`, `prematch_rec` |
| [app/src/models.py](app/src/models.py) | Modelos SQLModel: `Team`, `Tournament`, `Match` (goles nullable), `RatingSnapshot`, `Strategy`, `Odds` |
| [app/src/db.py](app/src/db.py) | Engine SQLite, `init_db`, sesiones (`:memory:` para tests) |
| [app/src/ingest.py](app/src/ingest.py) | scraper ↔ DB ↔ pipeline: `ingest_qatar_backtest`, `ingest_live`, `ingest_calendar`, `load_matches` (finalizados), `load_calendar` (todos), `persist_snapshots`, `clear_snapshots` |
| [app/src/betting.py](app/src/betting.py) | Motor puro de apuestas: `BetParams`, `pick_side`, `stake_amount`, `simulate`, `recommend_bet`, `sweep_strategies` |
| [app/src/strategies.py](app/src/strategies.py) | Estrategia activa en la DB: `save_active_strategy`, `load_active_strategy`, `strategy_to_params` |
| [app/src/odds.py](app/src/odds.py) | Capa de cuotas: `OddsQuote`, conversores, `detect_source`, `select_markets` (filtro regex), `parse_polymarket_events`/`parse_polymarket`/`parse_codere` (puro) + `fetch_*` (red, Polymarket por tag/eventos paginados) |
| [app/src/odds_store.py](app/src/odds_store.py) | Persistencia de cuotas: `ingest_odds`, `latest_odds`, `latest_scrape_iso` |
| [app/src/dbview.py](app/src/dbview.py) | Inspección read-only de la DB: `table_schema`, `table_rows` |
| [app/ui_common.py](app/ui_common.py) | Controles de sidebar compartidos entre páginas (`model_controls`, `betting_controls`, `fifa_ranking`) |
| [app/app.py](app/app.py) | 🏠 Página **Inicio** — guía del workflow + tablero de estado (¿calendario?/¿estrategia?/¿cuotas?) con `st.page_link`. No entrena ni apuesta. |
| [app/pages/1_🔴_Mundial_en_vivo.py](app/pages/) | 🔴 Página **en vivo**: scrape ESPN → DB (calendario) + recomendaciones por partido |
| [app/pages/2_🧪_Qatar_2022.py](app/pages/) | 🧪 Página **laboratorio**: monitor Elo/Bayes + backtest de apuestas + fijar estrategia (todo ligado al sidebar) |
| [app/pages/3_🗄️_Datos.py](app/pages/) | 🗄️ Página **explorador de datos** (expanders: head, nº filas, última actualización, esquema) |
| [app/tests/](app/tests/) | `test_pipeline.py`, `test_models.py`, `test_ingest.py`, `test_betting.py`, `test_dbview.py` |

La app es un **workflow de 4 etapas**: `app.py` (Inicio/guía) → `pages/2` (Qatar
2022, laboratorio) → `pages/1` (Mundial en vivo, producción) → `pages/3` (Datos).
Los parámetros se comparten entre páginas vía `session_state` (helpers en
`ui_common.py`). El laboratorio consume `Pipeline.match_log` (foto pre-partido) y
la página en vivo usa `Pipeline.prematch_rec` + `betting.recommend_bet` para
recomendar lado + stake en cada partido programado del calendario.

**Flujo Laboratorio→Producción:** en **Qatar 2022** configuras el sidebar (modelo +
apuesta + sizing + filtro), ves el monitor Elo/Bayes, corres el backtest con
**esos** params y «Guardar configuración actual» fija exactamente esos params como
estrategia activa (`Strategy` vía `save_active_strategy`). El sidebar y la
estrategia que se fija están **ligados**; el sweep (`sweep_strategies`, rankeado por
yield) es opcional y «Aplicar al panel» copia la combo elegida al sidebar. La
página en vivo lee la activa (`load_active_strategy` + `strategy_to_params`) y
recomienda 2026 con ella.

**Cuotas reales:** `src/odds.py` (parsers puros + fetchers best-effort de
Polymarket/Codere) → `Odds` (histórico) vía `odds_store`. La página en vivo pasa la
cuota real por partido a `recommend_bet(..., match_odds=...)` según la fuente
elegida (selector en la tab Cuotas, Polymarket por defecto). Selectores Codere /
shape Polymarket: best-effort, validar en vivo. `parse_polymarket` soporta mercados
de 2 outcomes y Yes/No "Will X beat Y" (emparejados por partido). Qatar 2022
persiste `RatingSnapshot` (clear+rewrite) tras cada corrida; la página en vivo
permite override manual de la estrategia activa.

La página **Mundial en vivo** está en 3 tabs (Calendario / Cuotas / Recomendaciones).
El **hub de cuotas** vive en la tab Cuotas. Polymarket es un flujo de 2 pasos:
"🔎 Buscar mercados" trae **eventos por `tag_id`** (la Gamma API **no tiene
búsqueda de texto**; 102232 = FIFA World Cup 2026) **paginando** `/events`
(límite 100/página vía `offset`), `select_markets(raw, regex)` filtra eventos
client-side y `parse_polymarket_events` los convierte a cuota por partido. Cada
evento de partido es "X vs. Y" con mercados Yes/No "Will X win…"/"Will Y win…"/
"…end in a draw?" → home/away/draw. Llena un **preview** (`st.data_editor` con
checkbox `guardar`, default = los que casan con el calendario); "💾 Guardar
seleccionadas" ingesta solo los marcados (`OddsQuote(**d)` → `ingest_odds`). Hay
un expander "ver eventos crudos" y contadores (crudos→regex→partidos) para
diagnosticar. Codere tiene su propio botón (URL detectada con `detect_source`).
La cuota casa con el calendario por `(home, away)`: los nombres de todas las
fuentes convergen al canónico ESPN vía `normalize_team` (`ALT_NAME_MAP` homologa
"Cabo Verde"→"Cape Verde", "Côte d'Ivoire"→"Ivory Coast", "DR Congo"→"Congo DR",
etc.) — validado: 135/135 partidos de Polymarket casan con el calendario 2026.
Debajo, comparar Codere/Polymarket vs el modelo entrenado con finalizados 2026, y
**elegir ahí la fuente** que alimenta las recomendaciones (key `live_odds_source`).

Flujo: `Pipeline.seed(fifa_points)` → `process_all(matches)` donde cada `match`
es la tupla `(date, stage, home, away, home_goals, away_goals)`. Elo y Bayes se
actualizan en paralelo; antes de cada partido se guarda `P(A gana)` para calibrar.

## Páginas (Streamlit multipage)

- **🏠 Inicio (`app.py`):** guía del workflow + tablero de estado (sin red, sin
  modelo). Muestra si hay calendario/estrategia/cuotas y enlaza a cada página.
- **🧪 Qatar 2022 (`pages/2_…`):** laboratorio offline. Siembra `QATAR_2022_SAMPLE`,
  muestra el monitor Elo/Bayes, corre el backtest de apuestas con los params del
  sidebar y fija esa configuración como estrategia activa (ligado).
- **🔴 Mundial en vivo (`pages/1_…`):** scrapea `fifa.world` de ESPN por rango de
  fechas (`YYYYMMDD-YYYYMMDD`), persiste **todo el calendario** (finalizados +
  programados) y recomienda lado + stake en los programados con la estrategia activa.
- **🗄️ Datos (`pages/3_…`):** explorador read-only (expanders con head/esquema/última
  actualización por tabla).

Endpoint ESPN (sin API key):
`https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=YYYYMMDD-YYYYMMDD`

## Comandos

Todos desde `app/` (donde vive el entorno `uv`):

```bash
cd app
uv sync
uv run playwright install chromium     # solo para modo "En vivo 2026"
uv run streamlit run app.py
uv run pytest -q                        # tests (sin red)
```

## Flujo de datos (DB = fuente de verdad)

`scraper` (o fixture de fallback) → `ingest.ingest_*` persiste `Match` en SQLite →
`ingest.load_matches` devuelve tuplas → `Pipeline.process_all` (Elo+Bayes en
memoria) → `ingest.persist_snapshots` vuelca `RatingSnapshot` de vuelta. El
`Pipeline`/Elo/Bayes son puros y no tocan la DB.

## Convenciones

- Python 3.11+, entorno `uv` (`pyproject.toml` en `app/`), tests con `pytest`
  (`pythonpath=["."]` para resolver `from src.*`).
- Persistencia con **SQLModel** sobre SQLite; tests usan engine `:memory:`.
- Python con `from __future__ import annotations` y `@dataclass`/SQLModel en los modelos.
- Sin scipy: el intervalo de credibilidad Beta usa aproximación normal con
  `statistics.NormalDist` ([app/src/bayes.py](app/src/bayes.py)).
- Los tests no hacen red: el scraping se inyecta (`scrape_fn`) o se parsean payloads guardados.
- Marcadores Elo en **tiempo reglamentario** — los penales no cuentan.
- Empate = 0.5 tanto en Elo como en Bayes.

## Limitación conocida (siguiente iteración)

El Bayes binario trata partidos como ensayos independientes y **no usa la fuerza
del rival ni los goles**. Para mejorar predicción: Bradley-Terry (fuerza relativa)
o Poisson/Dixon-Coles (goles), reusando el mismo scraping y la misma capa de
calibración.
