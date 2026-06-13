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


SAMPLE_CALENDAR = {
    "events": [
        {
            "id": "501", "date": "2026-06-11T18:00Z",
            "competitions": [{
                "status": {"type": {"name": "STATUS_FULL_TIME"}},
                "notes": [{"headline": "Group A"}],
                "competitors": [
                    {"homeAway": "home", "score": "3", "team": {"displayName": "Mexico"}},
                    {"homeAway": "away", "score": "0", "team": {"displayName": "Canada"}},
                ],
            }],
        },
        {
            "id": "502", "date": "2026-06-12T18:00Z",
            "competitions": [{
                "status": {"type": {"name": "STATUS_SCHEDULED"}},
                "notes": [{"headline": "Group A"}],
                "competitors": [
                    {"homeAway": "home", "score": "0", "team": {"displayName": "Argentina"}},
                    {"homeAway": "away", "score": "0", "team": {"displayName": "Mexico"}},
                ],
            }],
        },
    ]
}


def test_ingest_calendar_persists_all_and_load_splits():
    from src.ingest import ingest_calendar, load_calendar
    s = make_session()
    t = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
    results = parse_scoreboard_json(SAMPLE_CALENDAR)
    ingest_calendar(s, t, results)

    cal = load_calendar(s, t)                 # todos (2)
    assert len(cal) == 2
    assert {c["status_finished"] for c in cal} == {True, False}

    finished = load_matches(s, t)             # solo finalizados (1)
    assert len(finished) == 1
    assert finished[0][2] == "Mexico" and finished[0][3] == "Canada"


def test_ingest_calendar_updates_scheduled_to_finished():
    from src.ingest import ingest_calendar, load_calendar
    s = make_session()
    t = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
    ingest_calendar(s, t, parse_scoreboard_json(SAMPLE_CALENDAR))
    # el evento 502 (Argentina vs Mexico) ahora termina 2-1
    SAMPLE_CALENDAR["events"][1]["competitions"][0]["status"]["type"]["name"] = "STATUS_FULL_TIME"
    SAMPLE_CALENDAR["events"][1]["competitions"][0]["competitors"][0]["score"] = "2"
    SAMPLE_CALENDAR["events"][1]["competitions"][0]["competitors"][1]["score"] = "1"
    ingest_calendar(s, t, parse_scoreboard_json(SAMPLE_CALENDAR))

    cal = load_calendar(s, t)
    assert len(cal) == 2                       # sin duplicar (dedup event_id)
    assert len(load_matches(s, t)) == 2        # ahora ambos finalizados
    # restaurar el payload para no afectar otros tests
    SAMPLE_CALENDAR["events"][1]["competitions"][0]["status"]["type"]["name"] = "STATUS_SCHEDULED"
    SAMPLE_CALENDAR["events"][1]["competitions"][0]["competitors"][0]["score"] = "0"
    SAMPLE_CALENDAR["events"][1]["competitions"][0]["competitors"][1]["score"] = "0"


def test_clear_snapshots():
    from src.pipeline import Pipeline
    from src.ingest import clear_snapshots, persist_snapshots
    from src.models import RatingSnapshot
    s = make_session()
    seed_teams(s, FIFA_SNAPSHOT_EXAMPLE)
    t = get_or_create_tournament(s, "Qatar 2022", 2022, "backtest")
    ingest_matches(s, t, fixture_to_results(QATAR_2022_SAMPLE), source="fixture")
    pipe = Pipeline()
    pipe.seed(FIFA_SNAPSHOT_EXAMPLE)
    pipe.process_all(load_matches(s, t))
    persist_snapshots(s, t, pipe)
    assert len(s.exec(select(RatingSnapshot)).all()) > 0
    removed = clear_snapshots(s, t)
    assert removed > 0
    assert s.exec(select(RatingSnapshot)).all() == []
