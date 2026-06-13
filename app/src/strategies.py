"""Persistencia de la estrategia activa (la elegida en el laboratorio)."""
from __future__ import annotations

from sqlmodel import Session, select

from .models import Strategy
from .betting import BetParams

_PARAM_FIELDS = ("bankroll0", "odds", "sizing", "base_fraction", "kelly_fraction",
                 "start_match_no", "side_criterion", "blend_weight",
                 "use_bayes_filter", "bayes_threshold")


def strategy_to_params(strategy: Strategy) -> BetParams:
    return BetParams(**{f: getattr(strategy, f) for f in _PARAM_FIELDS})


def save_active_strategy(session: Session, params: BetParams, label: str,
                         *, yield_: float | None = None,
                         roi: float | None = None) -> Strategy:
    """Desactiva las previas y guarda `params` como la única estrategia activa."""
    for prev in session.exec(select(Strategy).where(Strategy.active == True)).all():  # noqa: E712
        prev.active = False
    row = Strategy(label=label, active=True,
                   backtest_yield=yield_, backtest_roi=roi,
                   **{f: getattr(params, f) for f in _PARAM_FIELDS})
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def load_active_strategy(session: Session) -> Strategy | None:
    return session.exec(select(Strategy).where(Strategy.active == True)).first()  # noqa: E712
