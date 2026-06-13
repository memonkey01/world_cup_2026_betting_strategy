"""Tests de los helpers de inspección de la DB."""
from sqlmodel import Session

from src.db import get_engine, init_db
from src.models import Team, Match, Tournament
from src.dbview import table_schema, table_rows
from src.ingest import (seed_teams, get_or_create_tournament, ingest_matches,
                        fixture_to_results)
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE
from src.qatar_fixture import QATAR_2022_SAMPLE


def make_session() -> Session:
    engine = get_engine(":memory:")
    init_db(engine)
    return Session(engine)


def test_table_schema_match():
    cols = {c["columna"]: c for c in table_schema(Match)}
    assert cols["id"]["pk"] is True
    assert cols["home_goals"]["nullable"] is True
    assert "espn_event_id" in cols
    assert "tipo" in cols["home_goals"]


def test_table_rows_counts_and_filters():
    s = make_session()
    seed_teams(s, FIFA_SNAPSHOT_EXAMPLE)
    t = get_or_create_tournament(s, "Qatar 2022", 2022, "backtest")
    ingest_matches(s, t, fixture_to_results(QATAR_2022_SAMPLE), source="fixture")

    teams = table_rows(s, Team)
    assert len(teams) >= 30                       # Team no se filtra por torneo

    all_matches = table_rows(s, Match)
    filtered = table_rows(s, Match, tournament_id=t.id)
    assert len(all_matches) == len(QATAR_2022_SAMPLE)
    assert len(filtered) == len(QATAR_2022_SAMPLE)

    # otro torneo sin partidos -> filtro devuelve 0
    t2 = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
    assert table_rows(s, Match, tournament_id=t2.id) == []
