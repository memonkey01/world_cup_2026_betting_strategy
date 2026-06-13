# Diseño — Persistencia SQLite + scraper para el monitor Mundial Elo+Bayes

**Fecha:** 2026-06-12
**Estado:** Aprobado (pendiente de plan de implementación)

## Objetivo

Reestructurar el proyecto a un paquete consistente, montarlo en un entorno `uv`,
y darle una base de datos SQLite como **fuente de verdad** para partidos del
Mundial (backtest e "en vivo"), alimentada por un scraper de ESPN con Playwright.
Los modelos Elo y Bayes existentes no cambian; se rodean con una capa de
persistencia. Incluye tests sin red.

## Decisiones tomadas

| Tema | Decisión |
|------|----------|
| ORM / persistencia | **SQLModel** (Pydantic + SQLAlchemy) |
| Rol de la DB | **Fuente de verdad**: scraper → DB → pipeline → snapshots → DB |
| Modelos | **Núcleo (4 tablas)**: Team, Tournament, Match, RatingSnapshot |
| Scraper | **Playwright** (con `requests` como fallback ligero ya existente) |
| Datos del backtest | **Scrape real de ESPN + fallback** a `QATAR_2022_SAMPLE` |
| Entorno uv / pyproject | **En `app/`** (donde vive todo el código) |

## Estructura objetivo

```
pypro_worldcup_betting/
├── CLAUDE.md
├── docs/superpowers/specs/2026-06-12-worldcup-db-scraper-design.md
└── app/                          # raíz del proyecto uv
    ├── pyproject.toml            # uv: streamlit, pandas, playwright, sqlmodel · dev: pytest
    ├── .gitignore                # .venv/, data/*.db, __pycache__
    ├── app.py                    # Streamlit (imports `from src.*`)
    ├── data/worldcup.db          # SQLite (runtime, no versionado)
    ├── src/
    │   ├── __init__.py
    │   ├── elo.py                # sin cambios
    │   ├── bayes.py              # sin cambios
    │   ├── fifa_seed.py          # sin cambios
    │   ├── qatar_fixture.py      # sin cambios (fallback offline)
    │   ├── pipeline.py           # sin cambios
    │   ├── scraper.py            # consolidado: + normalización + parseo de stage
    │   ├── models.py             # NUEVO — SQLModel
    │   ├── db.py                 # NUEVO — engine / sesión / init_db
    │   └── ingest.py             # NUEVO — pegamento scraper ↔ DB ↔ pipeline
    └── tests/
        ├── __init__.py
        ├── test_pipeline.py      # actual, con imports arreglados
        ├── test_models.py        # NUEVO
        └── test_ingest.py        # NUEVO
```

Corriendo desde `app/` y con `src/__init__.py`, los imports absolutos
(`from src.elo import …` en `app.py`/tests) y los relativos (`from .elo import …`
en `pipeline.py`) funcionan sin tocar la lógica.

## Modelos de datos (SQLModel)

### Team
- `id: int` (PK)
- `name: str` (único) — nombre canónico interno (post-normalización)
- `fifa_points: float | None`
- `elo_seed: float | None` — calculado vía `fifa_to_elo`

### Tournament
- `id: int` (PK)
- `name: str` (p.ej. "Qatar 2022", "World Cup 2026")
- `year: int`
- `kind: str` — `'backtest'` | `'live'`

### Match
- `id: int` (PK)
- `tournament_id: int` (FK → Tournament)
- `date: str` (ISO `YYYY-MM-DD`)
- `stage: str` — normalizado a `STAGE_ORDER` (`group`, `R16`, `QF`, `SF`, `3rd`, `final`)
- `home_team_id: int` (FK → Team)
- `away_team_id: int` (FK → Team)
- `home_goals: int`
- `away_goals: int`
- `status: str` — estado ESPN (`STATUS_FULL_TIME`, etc.)
- `source: str` — `'espn'` | `'fixture'`
- `espn_event_id: str | None` — para dedup idempotente
- propiedad `finished` — espejo de `MatchResult.finished`

### RatingSnapshot
- `id: int` (PK)
- `tournament_id: int` (FK → Tournament)
- `team_id: int` (FK → Team)
- `step: int` — índice de jornada/partido procesado
- `after_match_id: int | None` (FK → Match)
- `elo: float`
- `bayes_mean: float`, `bayes_lo: float`, `bayes_hi: float`

Persiste la evolución que hoy vive solo en memoria (`pipeline.snapshots`).

## Capas nuevas

### db.py
- `get_engine(path=...)` — SQLite por archivo; acepta `:memory:` para tests.
- `init_db(engine)` — crea todas las tablas (`SQLModel.metadata.create_all`).
- Helper de sesión (context manager) para uso en ingest, app y tests.

### ingest.py (DB = fuente de verdad)
- `seed_teams(session, fifa_points)` — upsert de Team + `elo_seed` vía `fifa_to_elo`.
- `ingest_matches(session, tournament, results)` — inserta/upserta Match (dedup por
  `espn_event_id`, o por `(tournament, date, home, away)` si no hay id), resolviendo
  Team por nombre normalizado (crea Team si falta).
- `ingest_qatar_backtest(session, prefer_scrape=True)` — intenta
  `scraper.fetch_via_playwright(qatar_2022_range())`; si lanza excepción o devuelve
  vacío, cae a `QATAR_2022_SAMPLE`; persiste. Marca `source` según origen.
- `ingest_live(session, tournament, date_range)` — scrape Playwright → persiste solo
  `finished`; idempotente.
- `load_matches(session, tournament)` — devuelve tuplas
  `(date, stage, home, away, hg, ag)` ordenadas por fecha → entrada de
  `Pipeline.process_all`.
- `persist_snapshots(session, tournament, pipeline)` — vuelca `pipeline.snapshots`
  y `combined_leaderboard()` a RatingSnapshot.

El `Pipeline`, `EloSystem` y `BayesianLeague` quedan **puros e intactos**; ingest los
rodea (DB → pipeline en memoria → DB).

## Cambios en app.py

- **Backtest:** en primer arranque siembra equipos y llena la DB con
  `ingest_qatar_backtest`; en adelante siempre lee partidos con `load_matches`.
- **En vivo 2026:** botón "Actualizar jornada" → `ingest_live` → recarga de DB.
- UI prácticamente igual; se añade un indicador de estado de la DB (nº de partidos).

## Gaps que el plan llenará explícitamente

1. **Normalización de nombres ESPN ↔ FIFA.** Mapa canónico
   ("United States"→"USA", "Korea Republic"→"Korea Republic", "IR Iran"→"Iran", etc.).
   Sin esto, Elo/Bayes parten ratings en equipos distintos. Vive en `scraper.py` o
   un `names.py` pequeño; lo usa `ingest_matches`.
2. **Parseo de `stage`.** El actual `notes[0].headline` es frágil; mapear etiquetas
   ESPN ("Group A", "Round of 16", "Final"…) a `STAGE_ORDER`, con default `group`.
3. **Idempotencia** al re-scrapear, vía `espn_event_id`.
4. **Carga de ranking FIFA oficial** a `Team.fifa_points` (hoy `FIFA_SNAPSHOT_EXAMPLE`
   es ejemplo); `load_fifa_ranking` ya existe, conectarlo al seed.
5. **Tiempo reglamentario vs prórroga/penales.** Documentar: Elo usa reglamentario;
   verificar qué marcador entrega ESPN. Limitación conocida, no se resuelve ahora.

## Tests (sin red)

- **test_pipeline.py** — existentes, con imports arreglados (`from src.*`).
- **test_models.py** — DB `:memory:`: crear Team/Tournament/Match/RatingSnapshot,
  consultar, relaciones FK, propiedad `finished`, unicidad de `Team.name`.
- **test_ingest.py** —
  - `parse_scoreboard_json` con un payload ESPN de muestra (fixture JSON local) →
    `ingest_matches` → `load_matches` roundtrip.
  - Rama fallback: `ingest_qatar_backtest` con scrape simulado vacío usa
    `QATAR_2022_SAMPLE`.
  - Normalización de nombres (ESPN → canónico) y dedup por `espn_event_id`.

Ninguna prueba hace red; el scraping se prueba contra payloads guardados.

## Comandos (uv, desde `app/`)

```bash
cd app
uv sync
uv run playwright install chromium     # solo para modo "En vivo"
uv run streamlit run app.py
uv run pytest -q
```

## Orden de implementación

1. Restructure a `app/src/` + `app/tests/` (mover archivos, añadir `__init__.py`).
2. `pyproject.toml` + entorno `uv` en `app/`; `.gitignore`.
3. Arreglar imports (`test_pipeline.py`, verificar `app.py`).
4. `models.py` + `db.py` + `test_models.py`.
5. `ingest.py` + consolidación de `scraper.py` (normalización, stage) + `test_ingest.py`.
6. Cablear `app.py` a la DB.
7. Pasada final de tests + actualizar `CLAUDE.md` y `README.md`.

## Fuera de alcance (YAGNI)

- Modelos Player/Venue/Group como tablas propias.
- Bradley-Terry / Poisson-Dixon-Coles (siguiente iteración, ya documentado).
- Migraciones (Alembic): para SQLite de un torneo, `create_all` basta.
- Selenium (Playwright cubre el caso).

## Nota de control de versiones

El directorio no es un repositorio git, así que este spec no se commitea. Si se
desea historial, hacer `git init` en `pypro_worldcup_betting/` antes de implementar.
