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
