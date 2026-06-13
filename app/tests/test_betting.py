"""Tests del motor puro de apuestas."""
from src.betting import BetParams, pick_side, stake_amount, simulate


def rec(home="A", away="B", p_home=0.7, bayes_home=0.6, bayes_away=0.4,
        home_win=True, away_win=False, home_match_no=2, away_match_no=2):
    return {"date": "d", "stage": "group", "home": home, "away": away,
            "p_home": p_home, "bayes_home": bayes_home, "bayes_away": bayes_away,
            "home_goals": 1, "away_goals": 0,
            "home_win": home_win, "away_win": away_win,
            "home_match_no": home_match_no, "away_match_no": away_match_no}


def test_pick_side_elo_picks_favorite():
    side, p_pick, bayes_pick, mno = pick_side(rec(p_home=0.7), "elo", 0.5)
    assert side == "home" and abs(p_pick - 0.7) < 1e-9
    side, p_pick, _, _ = pick_side(rec(p_home=0.3), "elo", 0.5)
    assert side == "away" and abs(p_pick - 0.7) < 1e-9


def test_pick_side_bayes_picks_higher_mean():
    side, p_pick, bayes_pick, _ = pick_side(
        rec(p_home=0.7, bayes_home=0.3, bayes_away=0.8), "bayes", 0.5)
    assert side == "away"               # away tiene mayor Bayes
    assert abs(bayes_pick - 0.8) < 1e-9
    assert abs(p_pick - 0.3) < 1e-9     # p_pick sigue siendo prob Elo del lado


def test_pick_side_blend_respects_weight():
    # home: elo 0.55, bayes 0.20 ; away: elo 0.45, bayes 0.80
    r = rec(p_home=0.55, bayes_home=0.20, bayes_away=0.80)
    # w=1.0 -> solo Elo -> home (0.55 > 0.45)
    assert pick_side(r, "blend", 1.0)[0] == "home"
    # w=0.0 -> solo Bayes -> away (0.80 > 0.20)
    assert pick_side(r, "blend", 0.0)[0] == "away"
