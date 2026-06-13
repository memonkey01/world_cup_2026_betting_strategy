"""Tests de persistencia de la estrategia activa."""
from sqlmodel import Session, select

from src.db import get_engine, init_db
from src.models import Strategy
from src.betting import BetParams
from src.strategies import (strategy_to_params, save_active_strategy,
                            load_active_strategy)


def make_session() -> Session:
    engine = get_engine(":memory:")
    init_db(engine)
    return Session(engine)


def test_strategy_table_exists_and_defaults():
    s = make_session()
    row = Strategy(label="x", bankroll0=1000.0, odds=2.0, sizing="kelly",
                   base_fraction=0.05, kelly_fraction=0.25, start_match_no=2,
                   side_criterion="elo", blend_weight=0.5,
                   use_bayes_filter=False, bayes_threshold=0.5)
    s.add(row); s.commit()
    assert row.id is not None
    assert row.active is False


def test_save_and_load_roundtrip():
    s = make_session()
    params = BetParams(sizing="kelly", side_criterion="blend",
                       use_bayes_filter=True, bayes_threshold=0.55,
                       odds=1.9, base_fraction=0.08, kelly_fraction=0.5,
                       start_match_no=3, blend_weight=0.7, bankroll0=2000.0)
    save_active_strategy(s, params, "ganadora", yield_=0.12, roi=0.30)
    loaded = load_active_strategy(s)
    assert loaded is not None and loaded.label == "ganadora"
    assert loaded.backtest_yield == 0.12
    assert strategy_to_params(loaded) == params  # BetParams reconstruido igual


def test_only_one_active():
    s = make_session()
    save_active_strategy(s, BetParams(sizing="flat"), "v1")
    save_active_strategy(s, BetParams(sizing="kelly"), "v2")
    active = load_active_strategy(s)
    assert active.label == "v2" and active.sizing == "kelly"
    actives = s.exec(select(Strategy).where(Strategy.active == True)).all()  # noqa: E712
    assert len(actives) == 1
