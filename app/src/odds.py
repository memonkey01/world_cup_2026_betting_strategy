"""
Capa de cuotas: dataclass normalizada, conversores y parsers puros para
Polymarket (API) y Codere (Playwright). Los fetchers tocan la red y son
best-effort (selectores/endpoint a validar en vivo); el parseo es puro y testeable.
"""
from __future__ import annotations
from dataclasses import dataclass
import json

from .scraper import normalize_team

# Nombres en español (Codere) -> canónico del proyecto.
ES_NAME_MAP = {
    "México": "Mexico", "Mexico": "Mexico",
    "Estados Unidos": "USA", "EE.UU.": "USA",
    "Canadá": "Canada", "Canada": "Canada",
    "Corea del Sur": "Korea Republic",
    "Inglaterra": "England", "Brasil": "Brazil", "Países Bajos": "Netherlands",
    "Croacia": "Croatia", "Bélgica": "Belgium", "Alemania": "Germany",
    "España": "Spain", "Francia": "France", "Marruecos": "Morocco",
}


@dataclass
class OddsQuote:
    source: str            # 'codere' | 'polymarket'
    home: str
    away: str
    home_decimal: float
    away_decimal: float
    draw_decimal: float | None
    home_prob: float
    away_prob: float
    fetched_at: str        # ISO


def price_to_decimal(p: float) -> float:
    """Precio de mercado (0..1) -> cuota decimal."""
    return 1.0 / p if p > 0 else 0.0


def american_to_decimal(a: int) -> float:
    return 1.0 + (a / 100.0 if a > 0 else 100.0 / abs(a))


def implied_prob(decimal: float) -> float:
    return 1.0 / decimal if decimal > 0 else 0.0


def normalize_es(name: str) -> str:
    n = (name or "").strip()
    return normalize_team(ES_NAME_MAP.get(n, n))


def _quote(source, home, away, home_dec, away_dec, draw_dec, fetched_at) -> OddsQuote:
    return OddsQuote(
        source=source, home=home, away=away,
        home_decimal=home_dec, away_decimal=away_dec, draw_decimal=draw_dec,
        home_prob=implied_prob(home_dec), away_prob=implied_prob(away_dec),
        fetched_at=fetched_at,
    )


def parse_polymarket(payload: list, fetched_at: str) -> list[OddsQuote]:
    """payload: lista de mercados Gamma. Cada uno con 'outcomes' (JSON de 2 equipos)
    y 'outcomePrices' (JSON de 2 precios). El primer outcome = home."""
    out: list[OddsQuote] = []
    for mkt in payload:
        try:
            outcomes = json.loads(mkt["outcomes"])
            prices = [float(p) for p in json.loads(mkt["outcomePrices"])]
        except (KeyError, ValueError, TypeError):
            continue
        if len(outcomes) != 2 or len(prices) != 2:
            continue
        home, away = normalize_es(outcomes[0]), normalize_es(outcomes[1])
        out.append(_quote("polymarket", home, away,
                          price_to_decimal(prices[0]), price_to_decimal(prices[1]),
                          None, fetched_at))
    return out


def parse_codere(payload: dict, fetched_at: str) -> list[OddsQuote]:
    """payload normalizado: {events:[{home, away, odds:{home, draw, away}}]} decimal."""
    out: list[OddsQuote] = []
    for ev in payload.get("events", []):
        o = ev.get("odds", {})
        try:
            home_dec, away_dec = float(o["home"]), float(o["away"])
        except (KeyError, ValueError, TypeError):
            continue
        draw_dec = float(o["draw"]) if o.get("draw") is not None else None
        out.append(_quote("codere", normalize_es(ev.get("home", "")),
                          normalize_es(ev.get("away", "")),
                          home_dec, away_dec, draw_dec, fetched_at))
    return out
