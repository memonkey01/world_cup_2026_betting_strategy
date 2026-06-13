"""Persistencia de cuotas (histórico) y consultas de la última."""
from __future__ import annotations

from sqlmodel import Session, select

from .models import Odds, Team
from .ingest import get_or_create_team


def ingest_odds(session: Session, tournament, quotes) -> int:
    """Inserta una fila por quote (histórico). Resuelve equipos por nombre."""
    n = 0
    for qt in quotes:
        home = get_or_create_team(session, qt.home)
        away = get_or_create_team(session, qt.away)
        session.add(Odds(
            tournament_id=tournament.id, home_team_id=home.id, away_team_id=away.id,
            source=qt.source, home_decimal=qt.home_decimal,
            away_decimal=qt.away_decimal, draw_decimal=qt.draw_decimal,
            home_prob=qt.home_prob, away_prob=qt.away_prob, fetched_at=qt.fetched_at))
        n += 1
    session.commit()
    return n


def latest_odds(session: Session, tournament, source: str | None = None) -> list[dict]:
    """La fila más reciente por (home, away, source). Si `source`, filtra por fuente."""
    names = {t.id: t.name for t in session.exec(select(Team)).all()}
    stmt = select(Odds).where(Odds.tournament_id == tournament.id)
    if source is not None:
        stmt = stmt.where(Odds.source == source)
    rows = session.exec(stmt).all()
    best: dict[tuple, Odds] = {}
    for o in rows:
        key = (o.home_team_id, o.away_team_id, o.source)
        if key not in best or o.fetched_at > best[key].fetched_at:
            best[key] = o
    out = []
    for o in best.values():
        out.append({
            "home": names.get(o.home_team_id), "away": names.get(o.away_team_id),
            "source": o.source, "home_decimal": o.home_decimal,
            "away_decimal": o.away_decimal, "draw_decimal": o.draw_decimal,
            "home_prob": o.home_prob, "away_prob": o.away_prob,
            "fetched_at": o.fetched_at,
        })
    return out


def latest_scrape_iso(session: Session, tournament, source: str) -> str | None:
    """Máximo fetched_at para esa fuente (drive del TTL 24h)."""
    rows = session.exec(select(Odds).where(
        Odds.tournament_id == tournament.id, Odds.source == source)).all()
    return max((o.fetched_at for o in rows), default=None)
