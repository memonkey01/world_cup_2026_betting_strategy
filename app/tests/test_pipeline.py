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


def test_match_log_prematch_snapshot():
    p = Pipeline()
    p.seed(FIFA_SNAPSHOT_EXAMPLE)
    p.process_all(QATAR_2022_SAMPLE)
    log = p.match_log
    assert len(log) == len(QATAR_2022_SAMPLE)

    first = log[0]  # ("2022-11-20", "group", "Qatar", "Ecuador", 0, 2)
    assert first["home"] == "Qatar" and first["away"] == "Ecuador"
    assert first["home_match_no"] == 1 and first["away_match_no"] == 1
    # Ecuador ganó 2-0
    assert first["home_win"] is False and first["away_win"] is True
    # Bayes pre-partido del 1er partido == media del prior (seed_from_elo)
    from src.bayes import elo_to_prior, BetaBelief
    a, b = elo_to_prior(p.initial_elo["Qatar"])
    assert abs(first["bayes_home"] - BetaBelief(a, b).mean) < 1e-9
    # p_home es una probabilidad
    assert 0.0 < first["p_home"] < 1.0

    # Argentina jugó 6 partidos en el sample -> match_no 1..6
    arg_matches = [r for r in log
                   if r["home"] == "Argentina" or r["away"] == "Argentina"]
    nos = [r["home_match_no"] if r["home"] == "Argentina" else r["away_match_no"]
           for r in arg_matches]
    assert nos == [1, 2, 3, 4, 5, 6]


def test_prematch_rec_uses_current_state():
    p = Pipeline()
    p.seed(FIFA_SNAPSHOT_EXAMPLE)
    p.process_all(QATAR_2022_SAMPLE)
    # Argentina jugó 6 -> su próximo sería el nº 7
    rec = p.prematch_rec("Argentina", "France")
    assert rec["home"] == "Argentina" and rec["away"] == "France"
    assert 0.0 < rec["p_home"] < 1.0
    assert 0.0 <= rec["bayes_home"] <= 1.0 and 0.0 <= rec["bayes_away"] <= 1.0
    assert rec["home_match_no"] == 7
    # equipo que no jugó -> match_no 1
    rec2 = p.prematch_rec("Atlantis", "France")
    assert rec2["home_match_no"] == 1


def test_pipeline_tracks_trueskill():
    p = Pipeline()
    p.seed(FIFA_SNAPSHOT_EXAMPLE)
    p.process_all(QATAR_2022_SAMPLE)
    # match_log expone la prob TrueSkill pre-partido (suma a 1 con el rival)
    first = p.match_log[0]
    assert 0.0 < first["ts_home"] < 1.0
    assert abs(first["ts_home"] + first["ts_away"] - 1.0) < 1e-9
    # prematch_rec también
    rec = p.prematch_rec("Argentina", "France")
    assert 0.0 < rec["ts_home"] < 1.0
    # el leaderboard combinado trae μ y σ de TrueSkill
    lb = p.combined_leaderboard()
    assert "ts_mu" in lb[0] and "ts_sigma" in lb[0]


def test_team_evolution_per_team_match_index():
    p = Pipeline()
    p.seed(FIFA_SNAPSHOT_EXAMPLE)
    p.process_all(QATAR_2022_SAMPLE)
    ev = p.team_evolution()
    # una fila por aparición de equipo (2 equipos por partido)
    assert len(ev) == 2 * len(QATAR_2022_SAMPLE)
    # Argentina jugó 6 partidos en el sample -> match_no 1..6 consecutivos
    arg = [r for r in ev if r["team"] == "Argentina"]
    assert [r["match_no"] for r in arg] == [1, 2, 3, 4, 5, 6]
    # rangos plausibles
    assert all(1000 < r["elo"] < 2300 for r in ev)
    assert all(0.0 <= r["bayes"] <= 1.0 for r in ev)
