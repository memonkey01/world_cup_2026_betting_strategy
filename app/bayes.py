"""
Capa bayesiana sobre juego binario (gana / no-gana, empate = 0.5 exito).

Dos cosas distintas que la gente confunde:

1) MODELO DE CREENCIA POR EQUIPO (Beta-Bernoulli):
   Cada equipo tiene una "tasa de victoria latente" theta ~ Beta(a, b).
   Prior anclado al Elo inicial (equipos fuertes -> prior con media alta).
   Cada partido es un ensayo Bernoulli; empate cuenta como 0.5 exito.
   Posterior conjugado: Beta(a + exitos, b + fracasos). Da intervalos de
   credibilidad sobre la fuerza, no solo un punto.

2) VALIDACION DE LA DISTRIBUCION (calibracion):
   El Elo emite una probabilidad P(A gana) por partido. Tras la jornada,
   comparamos esas probabilidades contra los resultados reales:
     - Brier score (menor = mejor)
     - Log loss
     - Calibracion por bins (reliability)
   Esto valida que la "distribucion" predicha por Elo este bien calibrada.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import math


# ----------------------------------------------------------------------
# 1) Creencia Beta-Bernoulli por equipo
# ----------------------------------------------------------------------

def elo_to_prior(elo: float, strength: float = 4.0, mean_elo: float = 1500.0) -> tuple[float, float]:
    """
    Convierte un Elo en parametros (a, b) de un prior Beta.
    'strength' = tamano de muestra equivalente del prior (cuanto pesa).
    Equipo con Elo > media -> prior sesgado a ganar.
    """
    # media del prior = sigmoide del Elo re-escalado a [0,1]
    p = 1.0 / (1.0 + 10 ** ((mean_elo - elo) / 400.0))
    p = min(max(p, 0.05), 0.95)
    a = p * strength
    b = (1.0 - p) * strength
    return a, b


@dataclass
class BetaBelief:
    alpha: float
    beta: float

    def update(self, success: float) -> None:
        """success en {1.0 (gana), 0.5 (empate), 0.0 (pierde)}."""
        self.alpha += success
        self.beta += (1.0 - success)

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def var(self) -> float:
        a, b = self.alpha, self.beta
        return (a * b) / ((a + b) ** 2 * (a + b + 1))

    def credible_interval(self, mass: float = 0.95) -> tuple[float, float]:
        """Intervalo de credibilidad via cuantiles Beta (Wilson-Hilferty aprox)."""
        from statistics import NormalDist
        # aproximacion normal del Beta para evitar dependencia de scipy
        m, v = self.mean, self.var
        sd = math.sqrt(v)
        z = NormalDist().inv_cdf(1 - (1 - mass) / 2)
        lo, hi = max(0.0, m - z * sd), min(1.0, m + z * sd)
        return lo, hi


@dataclass
class BayesianLeague:
    beliefs: dict[str, BetaBelief] = field(default_factory=dict)

    def seed_from_elo(self, elo_ratings: dict[str, float], strength: float = 4.0) -> None:
        self.beliefs = {team: BetaBelief(*elo_to_prior(elo, strength))
                        for team, elo in elo_ratings.items()}

    def get(self, team: str) -> BetaBelief:
        if team not in self.beliefs:
            self.beliefs[team] = BetaBelief(2.0, 2.0)
        return self.beliefs[team]

    def update_match(self, team_a: str, team_b: str, goals_a: int, goals_b: int) -> None:
        if goals_a > goals_b:
            sa, sb = 1.0, 0.0
        elif goals_a < goals_b:
            sa, sb = 0.0, 1.0
        else:
            sa, sb = 0.5, 0.5
        self.get(team_a).update(sa)
        self.get(team_b).update(sb)

    def leaderboard(self) -> list[tuple[str, float, float, float]]:
        rows = []
        for team, belief in self.beliefs.items():
            lo, hi = belief.credible_interval()
            rows.append((team, belief.mean, lo, hi))
        return sorted(rows, key=lambda r: r[1], reverse=True)


# ----------------------------------------------------------------------
# 2) Validacion / calibracion de las probabilidades del Elo
# ----------------------------------------------------------------------

def brier_score(probs: list[float], outcomes: list[float]) -> float:
    """outcomes en {1,0.5,0}. Brier = media de (p - o)^2."""
    return sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / len(probs)


def log_loss(probs: list[float], outcomes: list[float], eps: float = 1e-12) -> float:
    total = 0.0
    for p, o in zip(probs, outcomes):
        p = min(max(p, eps), 1 - eps)
        total += -(o * math.log(p) + (1 - o) * math.log(1 - p))
    return total / len(probs)


def reliability_bins(probs: list[float], outcomes: list[float], n_bins: int = 10) -> list[dict]:
    """Curva de calibracion: agrupa por probabilidad predicha y compara con frecuencia real."""
    bins = [{"lo": i / n_bins, "hi": (i + 1) / n_bins, "preds": [], "obs": []}
            for i in range(n_bins)]
    for p, o in zip(probs, outcomes):
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx]["preds"].append(p)
        bins[idx]["obs"].append(o)
    out = []
    for b in bins:
        if b["preds"]:
            out.append({
                "bin": f'{b["lo"]:.1f}-{b["hi"]:.1f}',
                "avg_pred": sum(b["preds"]) / len(b["preds"]),
                "avg_obs": sum(b["obs"]) / len(b["obs"]),
                "n": len(b["preds"]),
            })
    return out
