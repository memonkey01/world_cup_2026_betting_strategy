# Mundial Elo+Bayes — Persistencia SQLite + Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reestructurar el proyecto a un paquete `src/`, montarlo en un entorno `uv`, y darle una base de datos SQLite (SQLModel) como fuente de verdad para partidos del Mundial, alimentada por el scraper Playwright de ESPN, con tests sin red.

**Architecture:** El código Elo/Bayes (`elo.py`, `bayes.py`, `pipeline.py`) queda intacto y puro. Una capa nueva (`models.py`, `db.py`, `ingest.py`) lo rodea: el scraper persiste partidos en SQLite, `ingest` carga partidos de la DB hacia el `Pipeline` en memoria y vuelca snapshots de vuelta. `app.py` lee siempre de la DB.

**Tech Stack:** Python 3.11+, uv, SQLModel (SQLAlchemy+Pydantic), SQLite, Playwright, Streamlit, pandas, pytest.

**Working dir:** Todos los comandos se ejecutan desde `app/` salvo que se indique otra cosa.

---

## File Structure

| Archivo | Responsabilidad |
|---------|-----------------|
| `app/pyproject.toml` | Proyecto uv: dependencias + config de pytest |
| `app/src/__init__.py` | Marca `src` como paquete |
| `app/src/elo.py` `bayes.py` `fifa_seed.py` `qatar_fixture.py` `pipeline.py` | Movidos sin cambios |
| `app/src/scraper.py` | Movido + `normalize_team`, `normalize_stage`, `event_id` en `MatchResult` |
| `app/src/models.py` | NUEVO — modelos SQLModel (Team, Tournament, Match, RatingSnapshot) |
| `app/src/db.py` | NUEVO — engine / `init_db` / sesión |
| `app/src/ingest.py` | NUEVO — pegamento scraper ↔ DB ↔ pipeline |
| `app/app.py` | Modificado — lee/escribe vía DB |
| `app/tests/__init__.py` | Marca `tests` como paquete |
| `app/tests/test_pipeline.py` | Movido sin cambios (sus imports `from src.*` ya quedan válidos) |
| `app/tests/test_models.py` | NUEVO |
| `app/tests/test_ingest.py` | NUEVO |

---

## Task 1: Reestructurar a `src/` + `tests/`

**Files:**
- Move: `app/{bayes,elo,fifa_seed,pipeline,qatar_fixture,scraper}.py` → `app/src/`
- Move: `app/test_pipeline.py` → `app/tests/test_pipeline.py`
- Create: `app/src/__init__.py`, `app/tests/__init__.py`

- [ ] **Step 1: Mover archivos con git mv y crear paquetes**

Run (desde `app/`):
```bash
cd app
mkdir -p src tests
git mv bayes.py src/bayes.py
git mv elo.py src/elo.py
git mv fifa_seed.py src/fifa_seed.py
git mv pipeline.py src/pipeline.py
git mv qatar_fixture.py src/qatar_fixture.py
git mv scraper.py src/scraper.py
git mv test_pipeline.py tests/test_pipeline.py
touch src/__init__.py tests/__init__.py
```

- [ ] **Step 2: Verificar layout**

Run: `git status --short && ls src tests`
Expected: `src/` contiene los 6 módulos + `__init__.py`; `tests/` contiene `test_pipeline.py` + `__init__.py`. No quedan `.py` de lógica en `app/` salvo `app.py`.

Nota: no hay que tocar imports — `app.py` y `test_pipeline.py` ya usan `from src.*` y `pipeline.py` usa `from .elo` (relativo dentro del paquete). El layout `src/` es exactamente lo que esperaban.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: restructure flat app/ into src/ package + tests/"
```

---

## Task 2: Entorno uv + pyproject.toml

**Files:**
- Create: `app/pyproject.toml`
- Delete: `app/requirements.txt` (sustituido por pyproject)

- [ ] **Step 1: Crear `app/pyproject.toml`**

```toml
[project]
name = "worldcup-elo-bayes"
version = "0.1.0"
description = "Monitor Elo + Bayes del Mundial con persistencia SQLite y scraper ESPN"
requires-python = ">=3.11"
dependencies = [
    "streamlit>=1.40",
    "pandas>=2.0",
    "playwright>=1.45",
    "sqlmodel>=0.0.22",
]

[dependency-groups]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

`pythonpath = ["."]` hace importable `src` durante los tests (rootdir = `app/`).

- [ ] **Step 2: Eliminar requirements.txt legacy**

```bash
git rm requirements.txt
```

- [ ] **Step 3: Crear el entorno e instalar**

Run:
```bash
uv sync
```
Expected: crea `.venv/` e instala streamlit, pandas, playwright, sqlmodel y pytest. (No correr `playwright install chromium` aún; solo hace falta para el modo en vivo.)

- [ ] **Step 4: Verificar que los tests existentes pasan en el nuevo layout**

Run: `uv run pytest -q`
Expected: PASS — los 6 tests de `test_pipeline.py` pasan (valida que el restructure + pythonpath funcionan).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "build: add uv pyproject.toml, drop requirements.txt"
```

---

## Task 3: Modelos SQLModel (`models.py`)

**Files:**
- Create: `app/src/models.py`
- Test: `app/tests/test_models.py`

- [ ] **Step 1: Escribir el test que falla**

Create `app/tests/test_models.py`:
```python
"""Tests de los modelos SQLModel sobre una DB en memoria."""
import pytest
from sqlmodel import Session, select
from sqlalchemy.exc import IntegrityError

from src.db import get_engine, init_db
from src.models import Team, Tournament, Match, RatingSnapshot


def make_session() -> Session:
    engine = get_engine(":memory:")
    init_db(engine)
    return Session(engine)


def test_create_and_query_team():
    s = make_session()
    s.add(Team(name="Argentina", fifa_points=1886.0, elo_seed=1850.0))
    s.commit()
    t = s.exec(select(Team).where(Team.name == "Argentina")).first()
    assert t.id is not None
    assert t.fifa_points == 1886.0


def test_match_finished_property():
    m = Match(tournament_id=1, date="2022-11-20", home_team_id=1,
              away_team_id=2, home_goals=0, away_goals=2,
              status="STATUS_FULL_TIME")
    assert m.finished is True
    m.status = "STATUS_SCHEDULED"
    assert m.finished is False


def test_relationships_via_ids():
    s = make_session()
    arg, fra = Team(name="Argentina"), Team(name="France")
    s.add(arg); s.add(fra)
    tour = Tournament(name="Qatar 2022", year=2022, kind="backtest")
    s.add(tour); s.commit()
    s.add(Match(tournament_id=tour.id, date="2022-12-18", stage="final",
                home_team_id=arg.id, away_team_id=fra.id,
                home_goals=3, away_goals=3, status="STATUS_FULL_TIME"))
    s.commit()
    m = s.exec(select(Match)).first()
    assert m.tournament_id == tour.id
    assert {m.home_team_id, m.away_team_id} == {arg.id, fra.id}


def test_team_name_unique():
    s = make_session()
    s.add(Team(name="Brazil")); s.commit()
    s.add(Team(name="Brazil"))
    with pytest.raises(IntegrityError):
        s.commit()


def test_rating_snapshot_intervals_optional():
    snap = RatingSnapshot(tournament_id=1, team_id=1, step=0, elo=1500.0,
                          bayes_mean=0.5)
    assert snap.bayes_lo is None and snap.bayes_hi is None
```

- [ ] **Step 2: Correr el test para verlo fallar**

Run: `uv run pytest tests/test_models.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.models'` (y `src.db`).

- [ ] **Step 3: Implementar `app/src/models.py`**

```python
"""
Modelos SQLModel del dominio Mundial.

Cuatro tablas núcleo:
  Team             -> selección (nombre canónico + semilla FIFA/Elo)
  Tournament       -> edición del torneo (Qatar 2022 backtest, WC 2026 live)
  Match            -> partido (resultado en tiempo reglamentario)
  RatingSnapshot   -> evolución Elo/Bayes por paso (persistencia de snapshots)
"""
from __future__ import annotations
from sqlmodel import SQLModel, Field

FINISHED_STATUSES = ("STATUS_FULL_TIME", "STATUS_FINAL", "STATUS_FT")


class Team(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    fifa_points: float | None = None
    elo_seed: float | None = None


class Tournament(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    year: int
    kind: str = "backtest"  # 'backtest' | 'live'


class Match(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    date: str                       # ISO YYYY-MM-DD
    stage: str = "group"            # group | R16 | QF | SF | 3rd | final
    home_team_id: int = Field(foreign_key="team.id")
    away_team_id: int = Field(foreign_key="team.id")
    home_goals: int
    away_goals: int
    status: str = "STATUS_FULL_TIME"
    source: str = "fixture"         # 'espn' | 'fixture'
    espn_event_id: str | None = Field(default=None, index=True)

    @property
    def finished(self) -> bool:
        return self.status in FINISHED_STATUSES


class RatingSnapshot(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    step: int
    after_match_id: int | None = Field(default=None, foreign_key="match.id")
    elo: float
    bayes_mean: float
    bayes_lo: float | None = None   # solo se rellena en el paso final
    bayes_hi: float | None = None
```

- [ ] **Step 4: Implementar `app/src/db.py` (necesario para los tests de modelos)**

```python
"""
Capa de base de datos: engine SQLite, creación de tablas y sesiones.

Para tests usar get_engine(":memory:") -> StaticPool mantiene una sola
conexión, así la DB en memoria sobrevive entre sesiones del mismo engine.
"""
from __future__ import annotations
from pathlib import Path
from contextlib import contextmanager

from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

from . import models  # noqa: F401  registra las tablas en SQLModel.metadata

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "worldcup.db"


def get_engine(path: str | Path = DEFAULT_DB_PATH, echo: bool = False):
    if str(path) == ":memory:":
        return create_engine(
            "sqlite://", echo=echo,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{path}", echo=echo,
        connect_args={"check_same_thread": False},
    )


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope(engine):
    with Session(engine) as session:
        yield session
```

- [ ] **Step 5: Correr los tests de modelos**

Run: `uv run pytest tests/test_models.py -q`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add src/models.py src/db.py tests/test_models.py
git commit -m "feat: add SQLModel models (Team/Tournament/Match/RatingSnapshot) + db layer"
```

---

## Task 4: Consolidar el scraper (normalización de nombres y stage, `event_id`)

**Files:**
- Modify: `app/src/scraper.py`
- Test: `app/tests/test_ingest.py` (parte de scraper)

- [ ] **Step 1: Escribir los tests que fallan**

Create `app/tests/test_ingest.py` (sección scraper por ahora):
```python
"""Tests de scraper + ingest, sin red (payloads ESPN guardados)."""
from sqlmodel import Session, select

from src.db import get_engine, init_db
from src.models import Match
from src.scraper import parse_scoreboard_json, normalize_team, normalize_stage
from src.ingest import (
    seed_teams, get_or_create_tournament, ingest_matches, load_matches,
    ingest_qatar_backtest, fixture_to_results, persist_snapshots,
)
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE
from src.qatar_fixture import QATAR_2022_SAMPLE


SAMPLE_PAYLOAD = {
    "events": [{
        "id": "401",
        "date": "2022-11-20T16:00Z",
        "competitions": [{
            "status": {"type": {"name": "STATUS_FULL_TIME"}},
            "notes": [{"headline": "Group A"}],
            "competitors": [
                {"homeAway": "home", "score": "0",
                 "team": {"displayName": "Qatar"}},
                {"homeAway": "away", "score": "2",
                 "team": {"displayName": "Ecuador"}},
            ],
        }],
    }]
}


def make_session() -> Session:
    engine = get_engine(":memory:")
    init_db(engine)
    return Session(engine)


def test_normalize_team():
    assert normalize_team("United States") == "USA"
    assert normalize_team("IR Iran") == "Iran"
    assert normalize_team("Brazil") == "Brazil"


def test_normalize_stage():
    assert normalize_stage("Round of 16") == "R16"
    assert normalize_stage("Quarterfinals") == "QF"
    assert normalize_stage("Semifinals") == "SF"
    assert normalize_stage("Final") == "final"
    assert normalize_stage("Group A") == "group"
    assert normalize_stage(None) == "group"


def test_parse_scoreboard_json():
    res = parse_scoreboard_json(SAMPLE_PAYLOAD)
    assert len(res) == 1
    r = res[0]
    assert r.home == "Qatar" and r.away == "Ecuador"
    assert r.home_goals == 0 and r.away_goals == 2
    assert r.stage == "group"
    assert r.event_id == "401"
    assert r.finished
```

- [ ] **Step 2: Correr para verlo fallar**

Run: `uv run pytest tests/test_ingest.py -q`
Expected: FAIL — `ImportError: cannot import name 'normalize_team'` (y `src.ingest` no existe).

- [ ] **Step 3: Añadir normalización y `event_id` a `app/src/scraper.py`**

Añadir cerca del inicio (después de los imports y antes de `MatchResult`):
```python
# Mapa ESPN displayName -> nombre canónico interno (coincide con FIFA snapshot).
ESPN_NAME_MAP = {
    "United States": "USA",
    "IR Iran": "Iran",
    "Iran": "Iran",
    "South Korea": "Korea Republic",
    "Korea Republic": "Korea Republic",
    "Republic of Korea": "Korea Republic",
    "Saudi Arabia": "Saudi Arabia",
}


def normalize_team(name: str) -> str:
    """Normaliza el nombre de ESPN al nombre canónico del proyecto."""
    n = (name or "").strip()
    return ESPN_NAME_MAP.get(n, n)


def normalize_stage(raw: str | None) -> str:
    """Mapea etiquetas de fase de ESPN a STAGE_ORDER (default 'group')."""
    if not raw:
        return "group"
    s = raw.lower()
    if "round of 16" in s or s.strip() == "r16":
        return "R16"
    if "quarter" in s:
        return "QF"
    if "semi" in s:
        return "SF"
    if "3rd" in s or "third" in s:
        return "3rd"
    if "final" in s:
        return "final"
    return "group"
```

Modificar el dataclass `MatchResult` para añadir `event_id`:
```python
@dataclass
class MatchResult:
    date: str
    stage: str
    home: str
    away: str
    home_goals: int
    away_goals: int
    status: str  # "STATUS_FULL_TIME", "STATUS_SCHEDULED", etc.
    event_id: str | None = None

    @property
    def finished(self) -> bool:
        return self.status in ("STATUS_FULL_TIME", "STATUS_FINAL", "STATUS_FT")
```

Reemplazar el cuerpo de `parse_scoreboard_json` para que normalice y capture el id:
```python
def parse_scoreboard_json(payload: dict) -> list[MatchResult]:
    """Parsea la respuesta del scoreboard API de ESPN (con normalización)."""
    results: list[MatchResult] = []
    for event in payload.get("events", []):
        comp = event.get("competitions", [{}])[0]
        status = comp.get("status", {}).get("type", {}).get("name", "UNKNOWN")
        competitors = comp.get("competitors", [])
        if len(competitors) != 2:
            continue
        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
        try:
            hg = int(home.get("score", 0))
            ag = int(away.get("score", 0))
        except (ValueError, TypeError):
            hg, ag = 0, 0
        headline = (comp.get("notes", [{}])[0].get("headline")
                    if comp.get("notes") else None)
        results.append(MatchResult(
            date=event.get("date", "")[:10],
            stage=normalize_stage(headline),
            home=normalize_team(home.get("team", {}).get("displayName", "?")),
            away=normalize_team(away.get("team", {}).get("displayName", "?")),
            home_goals=hg, away_goals=ag, status=status,
            event_id=str(event.get("id")) if event.get("id") is not None else None,
        ))
    return results
```

- [ ] **Step 4: Correr solo los tests de scraper**

Run: `uv run pytest tests/test_ingest.py -k "normalize or parse" -q`
Expected: PASS (3 tests). El resto de `test_ingest.py` aún falla por falta de `src.ingest` (se resuelve en la Task 5).

- [ ] **Step 5: Commit**

```bash
git add src/scraper.py tests/test_ingest.py
git commit -m "feat: scraper team/stage normalization + event_id capture"
```

---

## Task 5: Capa de ingesta (`ingest.py`)

**Files:**
- Create: `app/src/ingest.py`
- Test: `app/tests/test_ingest.py` (completar)

- [ ] **Step 1: Añadir los tests de ingest restantes a `app/tests/test_ingest.py`**

Agregar al final del archivo:
```python
def test_ingest_roundtrip():
    s = make_session()
    seed_teams(s, FIFA_SNAPSHOT_EXAMPLE)
    t = get_or_create_tournament(s, "Qatar 2022", 2022, "backtest")
    n = ingest_matches(s, t, parse_scoreboard_json(SAMPLE_PAYLOAD), source="espn")
    assert n == 1
    assert load_matches(s, t) == [("2022-11-20", "group", "Qatar", "Ecuador", 0, 2)]


def test_ingest_dedup_by_event_id():
    s = make_session()
    t = get_or_create_tournament(s, "Qatar 2022", 2022, "backtest")
    res = parse_scoreboard_json(SAMPLE_PAYLOAD)
    ingest_matches(s, t, res)
    ingest_matches(s, t, res)  # idempotente
    assert len(load_matches(s, t)) == 1


def test_backtest_fallback_to_fixture():
    s = make_session()

    def boom(date_range, league="fifa.world"):
        raise RuntimeError("no network")

    t = ingest_qatar_backtest(s, prefer_scrape=True, scrape_fn=boom)
    assert len(load_matches(s, t)) == len(QATAR_2022_SAMPLE)
    assert s.exec(select(Match)).first().source == "fixture"


def test_persist_snapshots():
    from src.pipeline import Pipeline
    from src.models import RatingSnapshot
    s = make_session()
    seed_teams(s, FIFA_SNAPSHOT_EXAMPLE)
    t = get_or_create_tournament(s, "Qatar 2022", 2022, "backtest")
    ingest_matches(s, t, fixture_to_results(QATAR_2022_SAMPLE), source="fixture")
    pipe = Pipeline()
    pipe.seed(FIFA_SNAPSHOT_EXAMPLE)
    pipe.process_all(load_matches(s, t))
    n = persist_snapshots(s, t, pipe)
    rows = s.exec(select(RatingSnapshot)).all()
    assert n == len(rows) and n > 0
    assert any(r.bayes_lo is not None for r in rows)  # el paso final lleva intervalos
```

- [ ] **Step 2: Correr para verlo fallar**

Run: `uv run pytest tests/test_ingest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ingest'`.

- [ ] **Step 3: Implementar `app/src/ingest.py`**

```python
"""
Pegamento entre el scraper, la base de datos y el Pipeline Elo/Bayes.

Flujo (DB = fuente de verdad):
  seed_teams -> ingest_(qatar_backtest|live) -> load_matches -> Pipeline -> persist_snapshots
"""
from __future__ import annotations

from sqlmodel import Session, select

from .models import Team, Tournament, Match, RatingSnapshot
from .fifa_seed import fifa_to_elo, FIFA_SNAPSHOT_EXAMPLE
from .scraper import (
    MatchResult, normalize_team, fetch_via_playwright, qatar_2022_range,
)
from .qatar_fixture import QATAR_2022_SAMPLE


# ---- equipos / torneos ----

def get_or_create_team(session: Session, name: str) -> Team:
    cname = normalize_team(name)
    team = session.exec(select(Team).where(Team.name == cname)).first()
    if team is None:
        team = Team(name=cname)
        session.add(team)
        session.flush()
    return team


def seed_teams(session: Session, fifa_points: dict[str, float]) -> None:
    elo = fifa_to_elo(fifa_points)
    for name, pts in fifa_points.items():
        team = get_or_create_team(session, name)
        team.fifa_points = pts
        team.elo_seed = elo[name]
    session.commit()


def get_or_create_tournament(session: Session, name: str, year: int,
                             kind: str) -> Tournament:
    t = session.exec(select(Tournament).where(Tournament.name == name)).first()
    if t is None:
        t = Tournament(name=name, year=year, kind=kind)
        session.add(t)
        session.flush()
    return t


# ---- partidos ----

def fixture_to_results(fixture: list[tuple]) -> list[MatchResult]:
    """Convierte tuplas (date, stage, home, away, hg, ag) a MatchResult."""
    return [MatchResult(date=d, stage=stage, home=h, away=a,
                        home_goals=hg, away_goals=ag,
                        status="STATUS_FULL_TIME", event_id=None)
            for (d, stage, h, a, hg, ag) in fixture]


def ingest_matches(session: Session, tournament: Tournament,
                   results: list[MatchResult], source: str = "espn") -> int:
    """Inserta/actualiza partidos. Dedup por event_id o por (torneo,fecha,equipos)."""
    inserted = 0
    for r in results:
        home = get_or_create_team(session, r.home)
        away = get_or_create_team(session, r.away)
        existing = None
        if r.event_id:
            existing = session.exec(select(Match).where(
                Match.tournament_id == tournament.id,
                Match.espn_event_id == r.event_id)).first()
        if existing is None:
            existing = session.exec(select(Match).where(
                Match.tournament_id == tournament.id,
                Match.date == r.date,
                Match.home_team_id == home.id,
                Match.away_team_id == away.id)).first()
        if existing is None:
            session.add(Match(
                tournament_id=tournament.id, date=r.date, stage=r.stage,
                home_team_id=home.id, away_team_id=away.id,
                home_goals=r.home_goals, away_goals=r.away_goals,
                status=r.status, source=source, espn_event_id=r.event_id))
            inserted += 1
        else:
            existing.home_goals = r.home_goals
            existing.away_goals = r.away_goals
            existing.status = r.status
    session.commit()
    return inserted


def load_matches(session: Session, tournament: Tournament) -> list[tuple]:
    """Devuelve tuplas (date, stage, home, away, hg, ag) ordenadas por fecha."""
    names = {t.id: t.name for t in session.exec(select(Team)).all()}
    rows = session.exec(select(Match).where(
        Match.tournament_id == tournament.id)).all()
    out = [(m.date, m.stage, names[m.home_team_id], names[m.away_team_id],
            m.home_goals, m.away_goals) for m in rows]
    return sorted(out, key=lambda x: x[0])


# ---- orquestación de alto nivel ----

def ingest_qatar_backtest(session: Session,
                          fifa_points: dict[str, float] = FIFA_SNAPSHOT_EXAMPLE,
                          prefer_scrape: bool = True,
                          scrape_fn=fetch_via_playwright) -> Tournament:
    """Siembra equipos y llena la DB con Qatar 2022 (scrape ESPN o fixture)."""
    seed_teams(session, fifa_points)
    t = get_or_create_tournament(session, "Qatar 2022", 2022, "backtest")
    results: list[MatchResult] = []
    source = "espn"
    if prefer_scrape:
        try:
            results = [r for r in scrape_fn(qatar_2022_range()) if r.finished]
        except Exception:  # noqa: BLE001  -> caemos al fixture
            results = []
    if not results:
        results = fixture_to_results(QATAR_2022_SAMPLE)
        source = "fixture"
    ingest_matches(session, t, results, source=source)
    return t


def ingest_live(session: Session, date_range: str,
                scrape_fn=fetch_via_playwright,
                fifa_points: dict[str, float] = FIFA_SNAPSHOT_EXAMPLE) -> Tournament:
    """Scrapea una jornada en vivo y persiste solo partidos finalizados."""
    seed_teams(session, fifa_points)
    t = get_or_create_tournament(session, "World Cup 2026", 2026, "live")
    results = [r for r in scrape_fn(date_range) if r.finished]
    ingest_matches(session, t, results, source="espn")
    return t


def persist_snapshots(session: Session, tournament: Tournament,
                      pipeline) -> int:
    """Vuelca pipeline.snapshots (evolución) + leaderboard final a RatingSnapshot."""
    ids: dict[str, int] = {}

    def tid(name: str) -> int:
        if name not in ids:
            ids[name] = get_or_create_team(session, name).id
        return ids[name]

    n = 0
    for step, snap in enumerate(pipeline.snapshots):
        for team, elo in snap["elo"].items():
            session.add(RatingSnapshot(
                tournament_id=tournament.id, team_id=tid(team), step=step,
                elo=elo, bayes_mean=snap["bayes"].get(team, 0.5)))
            n += 1
    final_step = len(pipeline.snapshots)
    for row in pipeline.combined_leaderboard():
        session.add(RatingSnapshot(
            tournament_id=tournament.id, team_id=tid(row["team"]),
            step=final_step, elo=row["elo"], bayes_mean=row["bayes_mean"],
            bayes_lo=row["bayes_lo"], bayes_hi=row["bayes_hi"]))
        n += 1
    session.commit()
    return n
```

- [ ] **Step 4: Correr todos los tests de ingest**

Run: `uv run pytest tests/test_ingest.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Correr toda la suite**

Run: `uv run pytest -q`
Expected: PASS (test_pipeline + test_models + test_ingest).

- [ ] **Step 6: Commit**

```bash
git add src/ingest.py tests/test_ingest.py
git commit -m "feat: ingest layer (scraper<->DB<->pipeline) with backtest fallback"
```

---

## Task 6: Cablear `app.py` a la base de datos

**Files:**
- Modify: `app/app.py`

- [ ] **Step 1: Reemplazar imports y carga de partidos**

En `app/app.py`, sustituir el bloque de imports de cabecera (líneas ~18-24, las que importan `Pipeline`, `FIFA_SNAPSHOT_EXAMPLE`, `QATAR_2022_SAMPLE`) por:
```python
from __future__ import annotations
import streamlit as st
import pandas as pd
from sqlmodel import Session, select

from src.pipeline import Pipeline
from src.elo import EloSystem
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE
from src.db import get_engine, init_db
from src.models import Match, Tournament
from src.ingest import ingest_qatar_backtest, ingest_live, load_matches
from src.scraper import fetch_via_playwright, fetch_via_requests
```
(Eliminar el import de `QATAR_2022_SAMPLE` y el import tardío de `EloSystem` que estaba más abajo en el archivo.)

- [ ] **Step 2: Renombrar la variable del selectbox del scraper para evitar colisión con el engine de la DB**

En el sidebar, cambiar:
```python
        engine = st.selectbox("Scraper", ["Playwright", "requests (fallback)"])
```
por:
```python
        scraper_engine = st.selectbox("Scraper", ["Playwright", "requests (fallback)"])
```

- [ ] **Step 3: Añadir el engine de la DB (cacheado) tras configurar el sidebar**

Justo después del bloque `with st.sidebar:` (antes de la sección "Carga de partidos"), añadir:
```python
@st.cache_resource
def get_db():
    eng = get_engine()
    init_db(eng)
    return eng

db_engine = get_db()
```

- [ ] **Step 4: Reemplazar la sección "Carga de partidos"**

Borrar el bloque actual que va desde `@st.cache_data ... def get_qatar_matches()` hasta el `st.success(...)` del scrape (la función `scrape_live`, `get_qatar_matches` y el `if mode == ...` de carga), y poner en su lugar:
```python
# ----------------------------------------------------------------------
# Carga de partidos (DB = fuente de verdad)
# ----------------------------------------------------------------------
if mode == "Backtest Qatar 2022":
    with Session(db_engine) as s:
        t = s.exec(select(Tournament).where(
            Tournament.name == "Qatar 2022")).first()
        has_matches = t and s.exec(select(Match).where(
            Match.tournament_id == t.id)).first()
        if not has_matches:
            with st.spinner("Sembrando DB con Qatar 2022…"):
                t = ingest_qatar_backtest(s, fifa_points=fifa_points,
                                          prefer_scrape=False)
        matches = load_matches(s, t)
else:
    matches = []
    if run_scrape:
        fn = (fetch_via_playwright if scraper_engine == "Playwright"
              else fetch_via_requests)
        with st.spinner("Scrapeando ESPN y guardando en DB…"):
            with Session(db_engine) as s:
                t = ingest_live(s, date_range, scrape_fn=fn,
                                fifa_points=fifa_points)
                matches = load_matches(s, t)
        st.success(f"{len(matches)} partidos finalizados guardados.")
    else:
        with Session(db_engine) as s:
            t = s.exec(select(Tournament).where(
                Tournament.name == "World Cup 2026")).first()
            matches = load_matches(s, t) if t else []

if not matches:
    st.info("Sin partidos cargados todavía. (En vivo: pulsa «Actualizar jornada».)")
    st.stop()
```

- [ ] **Step 5: Eliminar el import tardío de EloSystem**

Más abajo, donde dice `from src.elo import EloSystem` (justo antes de crear el `Pipeline`), borrar esa línea (ya se importa arriba). El `pipe = Pipeline(elo=EloSystem(...))` se mantiene igual.

- [ ] **Step 6: Verificar que compila**

Run: `uv run python -m py_compile app.py`
Expected: sin salida (exit 0). Confirma que no hay errores de sintaxis ni de import a nivel de módulo.

- [ ] **Step 7: Smoke test manual (opcional, requиere navegador para modo en vivo)**

Run: `uv run streamlit run app.py`
Expected: arranca; en "Backtest Qatar 2022" siembra la DB en `app/data/worldcup.db` y muestra la tabla, KPIs y pestañas. (Modo en vivo necesita `uv run playwright install chromium`.) Cerrar con Ctrl+C.

- [ ] **Step 8: Commit**

```bash
git add app.py
git commit -m "feat: wire Streamlit app to SQLite DB via ingest layer"
```

---

## Task 7: Actualizar documentación

**Files:**
- Modify: `app/README.md`
- Modify: `CLAUDE.md` (raíz)

- [ ] **Step 1: Actualizar `app/README.md`**

- Cambiar la sección "Uso" para reflejar uv:
```bash
cd app
uv sync
uv run playwright install chromium     # solo modo "En vivo 2026"
uv run streamlit run app.py
uv run pytest -q
```
- Cambiar la sección "Estructura" para añadir `src/models.py`, `src/db.py`, `src/ingest.py` y describir que la DB SQLite es la fuente de verdad.
- Quitar la "Limitación conocida" sobre el layout (ya resuelta).

- [ ] **Step 2: Actualizar `CLAUDE.md`**

- Eliminar la sección "⚠️ Gotcha: layout vs. imports" (ya no aplica).
- Actualizar la tabla de arquitectura: añadir `src/models.py`, `src/db.py`, `src/ingest.py`.
- Reemplazar la sección "Comandos" por los comandos `uv` (igual que el README).
- Añadir una frase: "La DB SQLite (`app/data/worldcup.db`) es la fuente de verdad; el scraper la llena y el pipeline lee de ella."

- [ ] **Step 3: Verificar suite completa una última vez**

Run: `uv run pytest -q`
Expected: PASS (todos).

- [ ] **Step 4: Commit**

```bash
git add ../CLAUDE.md README.md
git commit -m "docs: update README + CLAUDE.md for uv + SQLite layout"
```

---

## Notas de verificación final

- `uv run pytest -q` verde (pipeline + models + ingest), sin red.
- `uv run python -m py_compile app.py` sin errores.
- `app/data/worldcup.db` se crea al arrancar el backtest y queda gitignored.
- El scraping nunca se ejercita en tests (se inyecta `scrape_fn` o se parsean payloads guardados).
