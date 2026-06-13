"""Tests del modelo TrueSkill (wrapper sobre la librería trueskill)."""
from src.trueskill_model import TrueSkillSystem


def _seeded():
    ts = TrueSkillSystem()
    ts.seed_from_elo({"Fuerte": 1900.0, "Media": 1500.0, "Debil": 1300.0})
    return ts


def test_seed_orders_mu_by_elo():
    ts = _seeded()
    assert ts.get("Fuerte").mu > ts.get("Media").mu > ts.get("Debil").mu
    assert abs(ts.get("Media").mu - 25.0) < 1e-9   # equipo en la media -> μ=25


def test_win_probability_favours_stronger_and_is_symmetric():
    ts = _seeded()
    p = ts.win_probability("Fuerte", "Debil")
    assert p > 0.5
    # P(A gana B) + P(B gana A) ≈ 1
    assert abs(p + ts.win_probability("Debil", "Fuerte") - 1.0) < 1e-6


def test_update_match_moves_ratings():
    ts = _seeded()
    mu_before = ts.get("Debil").mu
    ts.update_match("Debil", "Fuerte", 2, 0)   # el débil gana
    assert ts.get("Debil").mu > mu_before       # sube el ganador
    # la incertidumbre baja tras observar un partido
    assert ts.get("Debil").sigma < TrueSkillSystem().get("X").sigma


def test_draw_is_native():
    ts = _seeded()
    mu_f, mu_d = ts.get("Fuerte").mu, ts.get("Debil").mu
    ts.update_match("Fuerte", "Debil", 1, 1)    # empate
    # el favorito pierde algo de μ y el débil gana algo (se acercan)
    assert ts.get("Fuerte").mu < mu_f
    assert ts.get("Debil").mu > mu_d


def test_expose_is_mu_minus_3sigma():
    ts = _seeded()
    r = ts.get("Fuerte")
    assert abs(ts.expose("Fuerte") - (r.mu - 3 * r.sigma)) < 1e-9


def test_leaderboard_sorted_desc():
    ts = _seeded()
    lb = ts.leaderboard()
    vals = [v for _, v in lb]
    assert vals == sorted(vals, reverse=True)
    assert lb[0][0] == "Fuerte"
