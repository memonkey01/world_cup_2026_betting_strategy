"""
Pipeline orquestador. Une todo:
  1. Semilla desde ranking FIFA -> Elo inicial.
  2. Procesa partidos jornada por jornada (Elo + Bayes en paralelo).
  3. Para cada partido, registra la prob predicha ANTES de jugarse -> calibracion.
  4. Expone snapshots por jornada para el monitor Streamlit.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from .elo import EloSystem, expected_score, match_scores
from .bayes import BayesianLeague, brier_score, log_loss, reliability_bins
from .fifa_seed import fifa_to_elo


# orden canonico de etapas para agrupar "jornadas"
STAGE_ORDER = ["group", "R16", "QF", "SF", "3rd", "final"]


@dataclass
class Pipeline:
    elo: EloSystem = field(default_factory=lambda: EloSystem(k=40.0))
    bayes: BayesianLeague = field(default_factory=BayesianLeague)
    pred_probs: list[float] = field(default_factory=list)   # prob A gana (pre-match)
    pred_outcomes: list[float] = field(default_factory=list)  # score real de A
    snapshots: list[dict] = field(default_factory=list)
    initial_elo: dict[str, float] = field(default_factory=dict)
    match_log: list[dict] = field(default_factory=list)        # foto pre-partido
    _appearances: dict[str, int] = field(default_factory=dict)

    def seed(self, fifa_points: dict[str, float]) -> None:
        self.initial_elo = fifa_to_elo(fifa_points)
        self.elo.seed(self.initial_elo)
        self.bayes.seed_from_elo(self.initial_elo)

    def process_match(self, home: str, away: str, hg: int, ag: int,
                      stage: str = "group", date: str | None = None) -> dict:
        # 1) prediccion ANTES de actualizar (para calibracion + apuestas)
        p_home = expected_score(self.elo.get(home), self.elo.get(away))
        s_home, _ = match_scores(hg, ag)
        self.pred_probs.append(p_home)
        self.pred_outcomes.append(s_home)
        # foto Bayes pre-partido y numero de aparicion por equipo
        bayes_home = self.bayes.get(home).mean
        bayes_away = self.bayes.get(away).mean
        self._appearances[home] = self._appearances.get(home, 0) + 1
        self._appearances[away] = self._appearances.get(away, 0) + 1
        self.match_log.append({
            "date": date, "stage": stage, "home": home, "away": away,
            "p_home": p_home,
            "bayes_home": bayes_home, "bayes_away": bayes_away,
            "home_goals": hg, "away_goals": ag,
            "home_win": hg > ag, "away_win": ag > hg,
            "home_match_no": self._appearances[home],
            "away_match_no": self._appearances[away],
        })
        # 2) actualizar ambos sistemas
        rec = self.elo.update_match(home, away, hg, ag, stage=stage, match_date=date)
        self.bayes.update_match(home, away, hg, ag)
        rec["pred_home_win"] = p_home
        return rec

    def process_all(self, matches: list[tuple]) -> None:
        """matches: lista de (date, stage, home, away, hg, ag)."""
        for (date, stage, home, away, hg, ag) in matches:
            self.process_match(home, away, hg, ag, stage=stage, date=date)
            self.snapshots.append(self._snapshot(date, stage))

    def _snapshot(self, date: str, stage: str) -> dict:
        return {
            "date": date, "stage": stage,
            "elo": dict(self.elo.ratings),
            "bayes": {t: self.bayes.get(t).mean for t in self.bayes.beliefs},
        }

    def calibration_report(self) -> dict:
        if not self.pred_probs:
            return {}
        return {
            "n_matches": len(self.pred_probs),
            "brier": brier_score(self.pred_probs, self.pred_outcomes),
            "log_loss": log_loss(self.pred_probs, self.pred_outcomes),
            "reliability": reliability_bins(self.pred_probs, self.pred_outcomes),
        }

    def team_evolution(self) -> list[dict]:
        """
        Serie temporal por equipo para graficar Elo y Bayes con eje X = partido
        jugado por el equipo. Devuelve filas {team, match_no, elo, bayes}.

        elo.history y snapshots van parejos por índice (uno por partido). Para
        cada partido, sus dos equipos suman un partido a su contador propio.
        """
        rows = []
        counts: dict[str, int] = {}
        for i, rec in enumerate(self.elo.history):
            snap = self.snapshots[i]
            for team in (rec["team_a"], rec["team_b"]):
                counts[team] = counts.get(team, 0) + 1
                rows.append({
                    "team": team,
                    "match_no": counts[team],
                    "elo": snap["elo"][team],
                    "bayes": snap["bayes"].get(team, 0.5),
                })
        return rows

    def combined_leaderboard(self) -> list[dict]:
        """Tabla unificada: Elo + media bayesiana + intervalo de credibilidad."""
        rows = []
        for team in self.elo.ratings:
            b = self.bayes.get(team)
            lo, hi = b.credible_interval()
            rows.append({
                "team": team,
                "elo": round(self.elo.get(team), 1),
                "elo_init": round(self.initial_elo.get(team, 1500), 1),
                "elo_delta": round(self.elo.get(team) - self.initial_elo.get(team, 1500), 1),
                "bayes_mean": round(b.mean, 3),
                "bayes_lo": round(lo, 3),
                "bayes_hi": round(hi, 3),
            })
        return sorted(rows, key=lambda r: r["elo"], reverse=True)
