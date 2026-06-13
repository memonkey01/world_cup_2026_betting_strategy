"""Tests minimos del pipeline. Correr: python -m pytest tests/ -q"""
from src.elo import expected_score, match_scores, EloSystem
from src.bayes import BetaBelief, brier_score
from src.pipeline import Pipeline
from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE, fifa_to_elo
from src.qatar_fixture import QATAR_2022_SAMPLE


def test_expected_score_symmetry():
    assert abs(expected_score(1500, 1500) - 0.5) < 1e-9
    assert expected_score(1700, 1500) > 0.5
    assert abs(expected_score(1700, 1500) + expected_score(1500, 1700) - 1.0) < 1e-9


def test_draw_is_half():
    assert match_scores(1, 1) == (0.5, 0.5)
    assert match_scores(2, 0) == (1.0, 0.0)


def test_elo_zero_sum_without_margin():
    e = EloSystem(k=32, use_margin=False)
    e.seed({"A": 1500, "B": 1500})
    before = e.get("A") + e.get("B")
    e.update_match("A", "B", 1, 0)
    assert abs((e.get("A") + e.get("B")) - before) < 1e-6  # Elo conserva masa


def test_beta_update():
    b = BetaBelief(2, 2)
    b.update(1.0)
    assert b.mean > 0.5
    b.update(0.5)  # empate
    assert 0 < b.mean < 1


def test_seed_centers_at_1500():
    elo = fifa_to_elo(FIFA_SNAPSHOT_EXAMPLE)
    avg = sum(elo.values()) / len(elo)
    assert abs(avg - 1500) < 1.0


def test_full_pipeline_calibration():
    p = Pipeline()
    p.seed(FIFA_SNAPSHOT_EXAMPLE)
    p.process_all(QATAR_2022_SAMPLE)
    rep = p.calibration_report()
    assert rep["n_matches"] == len(QATAR_2022_SAMPLE)
    assert rep["brier"] < 0.25  # mejor que el azar
    assert len(p.combined_leaderboard()) > 0
