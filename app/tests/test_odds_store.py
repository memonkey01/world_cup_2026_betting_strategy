"""Tests de persistencia de cuotas."""
from sqlmodel import Session

from src.db import get_engine, init_db
from src.odds import OddsQuote
from src.odds_store import ingest_odds, latest_odds, latest_scrape_iso
from src.ingest import get_or_create_tournament, seed_teams
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE


def make_session() -> Session:
    engine = get_engine(":memory:")
    init_db(engine)
    return Session(engine)


def q(source, home, away, hd, ad, fetched_at):
    return OddsQuote(source=source, home=home, away=away, home_decimal=hd,
                     away_decimal=ad, draw_decimal=None,
                     home_prob=1 / hd, away_prob=1 / ad, fetched_at=fetched_at)


def test_ingest_and_latest():
    s = make_session()
    seed_teams(s, FIFA_SNAPSHOT_EXAMPLE)
    t = get_or_create_tournament(s, "World Cup 2026", 2026, "live")
    # dos scrapes del mismo partido (Polymarket) + uno de Codere
    ingest_odds(s, t, [q("polymarket", "Argentina", "France", 1.8, 2.2,
                         "2026-06-13T08:00:00")])
    ingest_odds(s, t, [q("polymarket", "Argentina", "France", 1.7, 2.3,
                         "2026-06-13T12:00:00")])
    ingest_odds(s, t, [q("codere", "Argentina", "France", 1.85, 2.1,
                         "2026-06-13T09:00:00")])

    poly = latest_odds(s, t, source="polymarket")
    assert len(poly) == 1                       # una por (partido, fuente)
    assert abs(poly[0]["home_decimal"] - 1.7) < 1e-9   # la más reciente (12:00)

    todas = latest_odds(s, t)
    assert len(todas) == 2                       # polymarket + codere

    assert latest_scrape_iso(s, t, "polymarket") == "2026-06-13T12:00:00"
    assert latest_scrape_iso(s, t, "codere") == "2026-06-13T09:00:00"
    assert latest_scrape_iso(s, t, "bet365") is None
