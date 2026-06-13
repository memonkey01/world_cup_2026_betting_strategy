"""
Sistema Elo para el Mundial con empates estilo ajedrez (medio punto).

Score real S_A en {1.0, 0.5, 0.0}:
  - victoria de A -> 1.0
  - empate        -> 0.5
  - derrota de A  -> 0.0

Actualizacion estandar: R' = R + K * (S - E)
donde E es la probabilidad esperada de "ganar" segun la sigmoide logistica.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import math


def expected_score(rating_a: float, rating_b: float) -> float:
    """Probabilidad logistica de que A gane (la E de Elo)."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def match_scores(goals_a: int, goals_b: int) -> tuple[float, float]:
    """Convierte marcador a scores Elo (empate = 0.5)."""
    if goals_a > goals_b:
        return 1.0, 0.0
    if goals_a < goals_b:
        return 0.0, 1.0
    return 0.5, 0.5


def margin_multiplier(goals_a: int, goals_b: int, rating_a: float, rating_b: float) -> float:
    """
    Multiplicador por margen de victoria (FiveThirtyEight-style).
    Amplifica K cuando la goleada es grande, pero corrige por la
    diferencia de rating para no inflar a favoritos. Para empates = 1.
    """
    diff = abs(goals_a - goals_b)
    if diff == 0:
        return 1.0
    elo_diff = abs(rating_a - rating_b)
    return math.log(diff + 1.0) * (2.2 / ((elo_diff * 0.001) + 2.2))


@dataclass
class EloSystem:
    k: float = 40.0  # K mas alto: el Mundial son pocos partidos, queremos que se mueva
    use_margin: bool = True
    ratings: dict[str, float] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    def seed(self, initial: dict[str, float]) -> None:
        """Inicializa ratings (tipicamente desde ranking FIFA convertido a Elo)."""
        self.ratings = dict(initial)

    def get(self, team: str) -> float:
        return self.ratings.get(team, 1500.0)

    def update_match(self, team_a: str, team_b: str, goals_a: int, goals_b: int,
                     stage: str = "group", match_date: str | None = None) -> dict:
        ra, rb = self.get(team_a), self.get(team_b)
        ea = expected_score(ra, rb)
        eb = 1.0 - ea
        sa, sb = match_scores(goals_a, goals_b)

        k_eff = self.k
        if self.use_margin:
            k_eff *= margin_multiplier(goals_a, goals_b, ra, rb)

        new_ra = ra + k_eff * (sa - ea)
        new_rb = rb + k_eff * (sb - eb)
        self.ratings[team_a] = new_ra
        self.ratings[team_b] = new_rb

        record = {
            "date": match_date, "stage": stage,
            "team_a": team_a, "team_b": team_b,
            "goals_a": goals_a, "goals_b": goals_b,
            "ra_before": ra, "rb_before": rb,
            "ra_after": new_ra, "rb_after": new_rb,
            "expected_a": ea, "k_eff": k_eff,
        }
        self.history.append(record)
        return record

    def leaderboard(self) -> list[tuple[str, float]]:
        return sorted(self.ratings.items(), key=lambda kv: kv[1], reverse=True)
