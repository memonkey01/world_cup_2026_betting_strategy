"""
TrueSkill (https://trueskill.org/) como modelo de rating alternativo a Elo.

TrueSkill es el sistema bayesiano de Microsoft Research: la habilidad de cada
equipo es una gaussiana `N(μ, σ²)` (μ = habilidad estimada, σ = incertidumbre).
Tras cada partido el sistema actualiza ambos por inferencia bayesiana (factor
graph). Maneja **empates de forma nativa** (ideal para fútbol) y da un rating
conservador `μ − 3σ` (`expose`), útil cuando aún hay incertidumbre.

A diferencia del Elo (un solo número, paso fijo K), TrueSkill modela también la
*confianza* en el rating: σ arranca alta y se encoge con los partidos.

Sembramos μ desde el Elo inicial (que viene del ranking FIFA) para un arranque
caliente en un torneo de pocos partidos. La probabilidad de victoria usa la
receta oficial:  P(A gana) = Φ( (μ_A − μ_B) / sqrt(2β² + σ_A² + σ_B²) ).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import math

from trueskill import TrueSkill, Rating, rate_1vs1

# Fracción de empates típica en fase de grupos de un Mundial (~26%).
DEFAULT_DRAW_PROBABILITY = 0.26


@dataclass
class TrueSkillSystem:
    draw_probability: float = DEFAULT_DRAW_PROBABILITY
    elo_per_mu: float = 40.0          # puntos Elo equivalentes a 1 de μ al sembrar
    mean_elo: float = 1500.0
    ratings: dict[str, Rating] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._env = TrueSkill(draw_probability=self.draw_probability)

    # -- semilla --------------------------------------------------------
    def seed_from_elo(self, initial_elo: dict[str, float]) -> None:
        """μ inicial = 25 + (Elo − media) / elo_per_mu; σ por defecto del entorno."""
        self.ratings = {
            team: self._env.create_rating(
                mu=25.0 + (elo - self.mean_elo) / self.elo_per_mu)
            for team, elo in initial_elo.items()
        }

    # -- consultas ------------------------------------------------------
    def get(self, team: str) -> Rating:
        return self.ratings.get(team) or self._env.create_rating()

    def expose(self, team: str) -> float:
        """Rating conservador μ − 3σ (penaliza la incertidumbre)."""
        return self._env.expose(self.get(team))

    def win_probability(self, home: str, away: str) -> float:
        """P(home gana a away) con la receta oficial de TrueSkill."""
        a, b = self.get(home), self.get(away)
        denom = math.sqrt(2 * self._env.beta ** 2 + a.sigma ** 2 + b.sigma ** 2)
        if denom == 0:
            return 0.5
        return self._env.cdf((a.mu - b.mu) / denom)

    # -- actualización --------------------------------------------------
    def update_match(self, home: str, away: str, hg: int, ag: int,
                     stage: str = "group", match_date: str | None = None) -> dict:
        rh, ra = self.get(home), self.get(away)
        if hg == ag:                                  # empate (nativo)
            nh, na = rate_1vs1(rh, ra, drawn=True, env=self._env)
        elif hg > ag:                                 # gana local
            nh, na = rate_1vs1(rh, ra, env=self._env)
        else:                                         # gana visitante
            na, nh = rate_1vs1(ra, rh, env=self._env)
        self.ratings[home], self.ratings[away] = nh, na
        record = {
            "date": match_date, "stage": stage, "home": home, "away": away,
            "mu_home_before": rh.mu, "mu_away_before": ra.mu,
            "mu_home_after": nh.mu, "mu_away_after": na.mu,
        }
        self.history.append(record)
        return record

    def leaderboard(self) -> list[tuple[str, float]]:
        """Equipos ordenados por rating conservador (μ − 3σ) desc."""
        return sorted(((t, self.expose(t)) for t in self.ratings),
                      key=lambda kv: kv[1], reverse=True)
