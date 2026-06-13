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
    """Tuplas (date, stage, home, away, hg, ag) de partidos FINALIZADOS, por fecha."""
    from .models import FINISHED_STATUSES
    names = {t.id: t.name for t in session.exec(select(Team)).all()}
    rows = session.exec(select(Match).where(
        Match.tournament_id == tournament.id,
        Match.status.in_(FINISHED_STATUSES))).all()
    out = [(m.date, m.stage, names[m.home_team_id], names[m.away_team_id],
            m.home_goals, m.away_goals) for m in rows]
    return sorted(out, key=lambda x: x[0])


def load_calendar(session: Session, tournament: Tournament) -> list[dict]:
    """Todos los partidos (calendario) ordenados por fecha, con status y goles."""
    from .models import FINISHED_STATUSES
    names = {t.id: t.name for t in session.exec(select(Team)).all()}
    rows = session.exec(select(Match).where(
        Match.tournament_id == tournament.id)).all()
    out = [{
        "date": m.date, "stage": m.stage,
        "home": names[m.home_team_id], "away": names[m.away_team_id],
        "home_goals": m.home_goals, "away_goals": m.away_goals,
        "status": m.status, "status_finished": m.status in FINISHED_STATUSES,
    } for m in rows]
    return sorted(out, key=lambda r: r["date"])


def ingest_calendar(session: Session, tournament: Tournament,
                    results: list[MatchResult]) -> int:
    """Persiste TODOS los partidos (finalizados + programados). Upsert por event_id."""
    return ingest_matches(session, tournament, results, source="espn")


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
