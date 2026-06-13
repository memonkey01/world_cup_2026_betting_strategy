"""Tests del motor puro de apuestas."""
from src.betting import BetParams, pick_side, stake_amount, simulate, recommend_bet


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


def test_stake_flat():
    p = BetParams(sizing="flat", base_fraction=0.05)
    assert abs(stake_amount(p, 1000.0, 0.7) - 50.0) < 1e-9


def test_stake_confidence_scales_with_p():
    p = BetParams(sizing="confidence", base_fraction=0.10)
    # conf = clip((0.75-0.5)*2,0,1) = 0.5 -> 0.10*1000*0.5 = 50
    assert abs(stake_amount(p, 1000.0, 0.75) - 50.0) < 1e-9
    # p<=0.5 -> conf 0 -> stake 0
    assert stake_amount(p, 1000.0, 0.5) == 0.0


def test_stake_kelly_zero_without_edge():
    p = BetParams(sizing="kelly", odds=2.0, kelly_fraction=1.0)
    # odds 2.0 -> b=1 -> edge requiere p>0.5; p=0.5 -> f*=0
    assert stake_amount(p, 1000.0, 0.5) == 0.0
    assert stake_amount(p, 1000.0, 0.4) == 0.0


def test_stake_kelly_positive_with_edge():
    p = BetParams(sizing="kelly", odds=2.0, kelly_fraction=1.0)
    # b=1, p=0.7 -> f* = (1*0.7 - 0.3)/1 = 0.4 -> 0.4*1000 = 400
    assert abs(stake_amount(p, 1000.0, 0.7) - 400.0) < 1e-9
    # con kelly_fraction 0.25 -> 100
    p2 = BetParams(sizing="kelly", odds=2.0, kelly_fraction=0.25)
    assert abs(stake_amount(p2, 1000.0, 0.7) - 100.0) < 1e-9


def test_simulate_settlement_and_skips():
    log = [
        rec(home="A", away="B", p_home=0.7, home_win=True, away_win=False,
            home_match_no=1, away_match_no=1),   # jornada 1 -> se salta
        rec(home="A", away="C", p_home=0.7, home_win=True, away_win=False,
            home_match_no=2, away_match_no=1),   # apuesta a A (gana)
        rec(home="A", away="D", p_home=0.7, home_win=False, away_win=True,
            home_match_no=3, away_match_no=1),   # apuesta a A (pierde)
    ]
    p = BetParams(bankroll0=1000.0, odds=2.0, sizing="flat", base_fraction=0.10,
                  start_match_no=2, side_criterion="elo", use_bayes_filter=False)
    out = simulate(log, p)
    # 2 apuestas (la jornada 1 se salta). Apuesta1: 100 -> +100 (1100).
    # Apuesta2: 110 (10% de 1100) -> -110 (990).
    assert out["n_bets"] == 2
    assert out["wins"] == 1
    assert abs(out["bankroll_final"] - 990.0) < 1e-6
    assert abs(out["total_staked"] - 210.0) < 1e-6
    assert len(out["curve"]) == out["n_bets"] + 1  # incluye punto inicial


def test_simulate_bayes_filter_reduces_bets():
    log = [
        rec(home="A", away="B", p_home=0.7, bayes_home=0.40,
            home_win=True, away_win=False, home_match_no=2, away_match_no=2),
        rec(home="A", away="C", p_home=0.7, bayes_home=0.65,
            home_win=True, away_win=False, home_match_no=3, away_match_no=2),
    ]
    base = dict(bankroll0=1000.0, odds=2.0, sizing="flat", base_fraction=0.10,
                start_match_no=2, side_criterion="elo")
    no_filter = simulate(log, BetParams(use_bayes_filter=False, **base))
    filtered = simulate(log, BetParams(use_bayes_filter=True,
                                       bayes_threshold=0.5, **base))
    assert no_filter["n_bets"] == 2
    assert filtered["n_bets"] == 1   # solo el segundo (bayes 0.65 > 0.5)


def test_simulate_stake_never_exceeds_bankroll():
    log = [rec(home="A", away="B", p_home=0.99, home_win=False, away_win=True,
               home_match_no=2, away_match_no=2)]
    p = BetParams(bankroll0=100.0, odds=2.0, sizing="flat", base_fraction=2.0,
                  start_match_no=2)
    out = simulate(log, p)
    # base_fraction 2.0 pediría 200 pero el bankroll es 100 -> apuesta 100 y pierde
    assert abs(out["bankroll_final"] - 0.0) < 1e-6
    assert abs(out["total_staked"] - 100.0) < 1e-6


def prec(home="A", away="B", p_home=0.7, bayes_home=0.6, bayes_away=0.4,
         home_match_no=2, away_match_no=2):
    """rec pre-partido (sin resultado) para recommend_bet."""
    return {"home": home, "away": away, "p_home": p_home,
            "bayes_home": bayes_home, "bayes_away": bayes_away,
            "home_match_no": home_match_no, "away_match_no": away_match_no}


def test_recommend_bet_places_bet():
    p = BetParams(sizing="flat", base_fraction=0.10, start_match_no=2,
                  side_criterion="elo")
    out = recommend_bet(prec(p_home=0.7), 1000.0, p)
    assert out["bet"] is True
    assert out["side"] == "home" and out["pick"] == "A"
    assert abs(out["stake"] - 100.0) < 1e-9
    assert out["skip_warmup"] is False and out["filtered_out"] is False


def test_recommend_bet_skips_warmup():
    p = BetParams(sizing="flat", base_fraction=0.10, start_match_no=2)
    out = recommend_bet(prec(p_home=0.7, home_match_no=1, away_match_no=1),
                        1000.0, p)
    assert out["skip_warmup"] is True
    assert out["bet"] is False and out["stake"] == 0.0


def test_recommend_bet_bayes_filter():
    p = BetParams(sizing="flat", base_fraction=0.10, start_match_no=2,
                  side_criterion="elo", use_bayes_filter=True, bayes_threshold=0.5)
    out = recommend_bet(prec(p_home=0.7, bayes_home=0.40), 1000.0, p)
    assert out["filtered_out"] is True and out["bet"] is False


def test_recommend_bet_stake_capped_by_bankroll():
    p = BetParams(sizing="flat", base_fraction=2.0, start_match_no=2)
    out = recommend_bet(prec(p_home=0.7), 100.0, p)
    assert abs(out["stake"] - 100.0) < 1e-9  # no excede el bankroll


def test_recommend_bet_uses_match_odds():
    # Kelly: b=odds-1, p=0.7. Con odds 2.0 -> f*=0.4 ; con odds 3.0 -> f*=0.55
    p = BetParams(sizing="kelly", kelly_fraction=1.0, start_match_no=2,
                  side_criterion="elo", odds=2.0)
    base = recommend_bet(prec(p_home=0.7), 1000.0, p)
    withodds = recommend_bet(prec(p_home=0.7), 1000.0, p,
                             match_odds={"home": 3.0, "away": 1.5})
    assert abs(base["odds"] - 2.0) < 1e-9
    assert abs(withodds["odds"] - 3.0) < 1e-9          # usa la cuota del lado home
    assert withodds["stake"] > base["stake"]           # más cuota -> más Kelly


def test_recommend_bet_match_odds_missing_side_falls_back():
    p = BetParams(sizing="flat", base_fraction=0.1, start_match_no=2,
                  side_criterion="elo", odds=2.0)
    # elige home pero solo hay cuota de away -> cae a params.odds
    out = recommend_bet(prec(p_home=0.7), 1000.0, p, match_odds={"away": 1.5})
    assert abs(out["odds"] - 2.0) < 1e-9


def test_sweep_strategies_ranks_by_yield():
    from src.betting import sweep_strategies
    # log de 6 partidos, equipos ya con match_no>=2 (sin warm-up)
    log = [rec(home="A", away="B", p_home=0.7,
               bayes_home=0.6, bayes_away=0.4,
               home_win=(i % 2 == 0), away_win=(i % 2 == 1),
               home_match_no=2 + i, away_match_no=2 + i)
           for i in range(6)]
    base = BetParams(bankroll0=1000.0, odds=2.0, base_fraction=0.1,
                     kelly_fraction=0.25, start_match_no=2,
                     blend_weight=0.5, bayes_threshold=0.5)
    rows = sweep_strategies(log, base)
    # 3 sizing x 3 criterio x 2 filtro = 18 combinaciones
    assert len(rows) == 18
    # ordenadas por yield desc
    ys = [r["metrics"]["yield"] for r in rows]
    assert ys == sorted(ys, reverse=True)
    # cada fila trae los params (BetParams) y las claves del combo
    top = rows[0]
    assert isinstance(top["params"], BetParams)
    assert top["sizing"] in ("flat", "confidence", "kelly")
    assert top["side_criterion"] in ("elo", "bayes", "blend")
    assert top["use_bayes_filter"] in (True, False)
    assert "curve" not in top["metrics"]  # métricas livianas (sin curva/apuestas)
