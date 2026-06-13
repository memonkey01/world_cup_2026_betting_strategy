"""
Motor puro de backtest de apuestas al ganador (sin Streamlit).

Consume el match_log del Pipeline (foto pre-partido) y simula la evolución del
bankroll según BetParams. La meta-estrategia es configurable: el criterio de
selección de lado (elo|bayes|blend), el filtro de Bayes, el sizing y la cuota.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class BetParams:
    bankroll0: float = 1000.0
    odds: float = 2.0
    sizing: str = "flat"          # 'flat' | 'confidence' | 'kelly'
    base_fraction: float = 0.05   # fracción del bankroll para flat/confidence
    kelly_fraction: float = 0.25  # fracción de Kelly aplicada
    start_match_no: int = 2       # arranca en la 2ª aparición del lado elegido
    side_criterion: str = "elo"   # 'elo' | 'bayes' | 'blend'
    blend_weight: float = 0.5     # peso de Elo en 'blend' (1-w para Bayes)
    use_bayes_filter: bool = False
    bayes_threshold: float = 0.5


def pick_side(rec: dict, side_criterion: str, blend_weight: float
              ) -> tuple[str, float, float, int]:
    """
    Devuelve (side, p_pick, bayes_pick, match_no) para el partido.
    p_pick = prob. Elo del lado elegido (estimación de P(ganar)).
    bayes_pick = media Bayes pre-partido del lado elegido.
    """
    p_home = rec["p_home"]
    elo_home, elo_away = p_home, 1.0 - p_home
    bayes_home, bayes_away = rec["bayes_home"], rec["bayes_away"]

    if side_criterion == "bayes":
        home_score, away_score = bayes_home, bayes_away
    elif side_criterion == "blend":
        w = blend_weight
        home_score = w * elo_home + (1 - w) * bayes_home
        away_score = w * elo_away + (1 - w) * bayes_away
    else:  # 'elo'
        home_score, away_score = elo_home, elo_away

    if home_score >= away_score:
        return "home", elo_home, bayes_home, rec["home_match_no"]
    return "away", elo_away, bayes_away, rec["away_match_no"]


def stake_amount(params: BetParams, bankroll: float, p_pick: float) -> float:
    """Monto a apostar según el método de sizing (>= 0)."""
    if params.sizing == "confidence":
        conf = (p_pick - 0.5) * 2.0
        conf = min(max(conf, 0.0), 1.0)
        return params.base_fraction * bankroll * conf
    if params.sizing == "kelly":
        b = params.odds - 1.0
        if b <= 0:
            return 0.0
        f_star = (b * p_pick - (1.0 - p_pick)) / b
        f_star = max(f_star, 0.0) * params.kelly_fraction
        return f_star * bankroll
    # 'flat' (default)
    return params.base_fraction * bankroll


def simulate(match_log: list[dict], params: BetParams) -> dict:
    """Recorre el log y simula el bankroll. Devuelve métricas + curva + apuestas."""
    bankroll = params.bankroll0
    peak = bankroll
    max_dd = 0.0
    bets: list[dict] = []
    curve = [{"bet_no": 0, "bankroll": bankroll}]
    total_staked = 0.0
    wins = 0

    for rec in match_log:
        side, p_pick, bayes_pick, match_no = pick_side(
            rec, params.side_criterion, params.blend_weight)
        if match_no < params.start_match_no:
            continue
        if params.use_bayes_filter and bayes_pick < params.bayes_threshold:
            continue
        stake = min(stake_amount(params, bankroll, p_pick), bankroll)
        if stake <= 0:
            continue

        won = rec["home_win"] if side == "home" else rec["away_win"]
        if won:
            bankroll += stake * (params.odds - 1.0)
            wins += 1
        else:
            bankroll -= stake
        total_staked += stake

        peak = max(peak, bankroll)
        max_dd = max(max_dd, peak - bankroll)
        bets.append({
            "date": rec["date"], "match": f'{rec["home"]} vs {rec["away"]}',
            "side": side, "pick": rec[side], "p_pick": round(p_pick, 4),
            "bayes_pick": round(bayes_pick, 4), "stake": round(stake, 2),
            "won": won, "bankroll": round(bankroll, 2),
        })
        curve.append({"bet_no": len(bets), "bankroll": bankroll})

    n_bets = len(bets)
    profit = bankroll - params.bankroll0
    return {
        "bankroll_final": bankroll,
        "profit": profit,
        "roi": profit / params.bankroll0 if params.bankroll0 else 0.0,
        "n_bets": n_bets,
        "wins": wins,
        "win_rate": wins / n_bets if n_bets else 0.0,
        "total_staked": total_staked,
        "yield": profit / total_staked if total_staked else 0.0,
        "max_drawdown": max_dd,
        "curve": curve,
        "bets": bets,
    }


def recommend_bet(rec: dict, bankroll: float, params: BetParams) -> dict:
    """Recomendación para UN partido próximo (rec sin resultado).
    Aplica pick_side + filtros (warm-up, umbral Bayes) + stake_amount."""
    side, p_pick, bayes_pick, match_no = pick_side(
        rec, params.side_criterion, params.blend_weight)
    skip_warmup = match_no < params.start_match_no
    filtered_out = params.use_bayes_filter and bayes_pick < params.bayes_threshold
    if skip_warmup or filtered_out:
        stake = 0.0
    else:
        stake = min(stake_amount(params, bankroll, p_pick), bankroll)
    return {
        "side": side, "pick": rec[side],
        "p_pick": p_pick, "bayes_pick": bayes_pick, "match_no": match_no,
        "stake": stake,
        "skip_warmup": skip_warmup, "filtered_out": filtered_out,
        "bet": stake > 0,
    }
