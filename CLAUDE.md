# CLAUDE.md

Monitor **Elo + Bayes** para el Mundial de fútbol, con scraping de resultados
desde ESPN y dashboard en Streamlit. Predice/valida la fuerza de las selecciones
y calibra las probabilidades del modelo contra resultados reales.

Todo el código vive en [app/](app/) (paquete `src/`, entorno `uv`). Comentarios,
docstrings y README están en español. La base de datos SQLite
(`app/data/worldcup.db`) es la **fuente de verdad**: el scraper la llena con
partidos y el pipeline Elo/Bayes lee de ella.

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
| [app/src/scraper.py](app/src/scraper.py) | ESPN scoreboard API vía Playwright; `fetch_via_requests` fallback; `normalize_team`/`normalize_stage` |
| [app/src/qatar_fixture.py](app/src/qatar_fixture.py) | `QATAR_2022_SAMPLE` — resultados reales para backtest offline / fallback |
| [app/src/pipeline.py](app/src/pipeline.py) | `Pipeline` — orquesta seed → Elo + Bayes por jornada, snapshots y calibración |
| [app/src/models.py](app/src/models.py) | Modelos SQLModel: `Team`, `Tournament`, `Match`, `RatingSnapshot` |
| [app/src/db.py](app/src/db.py) | Engine SQLite, `init_db`, sesiones (`:memory:` para tests) |
| [app/src/ingest.py](app/src/ingest.py) | Pegamento scraper ↔ DB ↔ pipeline: `seed_teams`, `ingest_qatar_backtest`, `ingest_live`, `load_matches`, `persist_snapshots` |
| [app/src/betting.py](app/src/betting.py) | Motor puro de backtest de apuestas: `BetParams`, `pick_side`, `stake_amount`, `simulate` |
| [app/app.py](app/app.py) | Dashboard Streamlit (lee/escribe vía DB) |
| [app/pages/](app/pages/) | Páginas Streamlit extra (multipage): simulador de apuestas |
| [app/tests/](app/tests/) | `test_pipeline.py`, `test_models.py`, `test_ingest.py`, `test_betting.py` |

El simulador de apuestas consume `Pipeline.match_log` (foto pre-partido: prob
Elo, medias Bayes y nº de partido por equipo) vía el motor puro `src/betting.py`.

Flujo: `Pipeline.seed(fifa_points)` → `process_all(matches)` donde cada `match`
es la tupla `(date, stage, home, away, home_goals, away_goals)`. Elo y Bayes se
actualizan en paralelo; antes de cada partido se guarda `P(A gana)` para calibrar.

## Modos del dashboard

- **Backtest Qatar 2022:** offline, usa `QATAR_2022_SAMPLE` (sin red).
- **En vivo 2026:** scrapea `fifa.world` de ESPN por rango de fechas
  (`YYYYMMDD-YYYYMMDD`) y procesa solo partidos finalizados. Botón
  «Actualizar jornada» al cerrar cada fecha.

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
