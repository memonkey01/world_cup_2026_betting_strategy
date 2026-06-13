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
