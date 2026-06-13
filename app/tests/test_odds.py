"""Tests de la capa pura de cuotas (conversores + parsers con fixtures)."""
from src.odds import (OddsQuote, price_to_decimal, american_to_decimal,
                      implied_prob, normalize_es, parse_polymarket, parse_codere)


def test_converters():
    assert abs(price_to_decimal(0.5) - 2.0) < 1e-9
    assert abs(price_to_decimal(0.8) - 1.25) < 1e-9
    assert abs(american_to_decimal(150) - 2.5) < 1e-9
    assert abs(american_to_decimal(-200) - 1.5) < 1e-9
    assert abs(implied_prob(2.0) - 0.5) < 1e-9


def test_normalize_es():
    assert normalize_es("México") == "Mexico"
    assert normalize_es("Estados Unidos") == "USA"
    assert normalize_es("Argentina") == "Argentina"


# Polymarket Gamma: un mercado de ganador con dos outcomes (equipos) y precios.
POLY_PAYLOAD = [
    {
        "question": "Argentina vs Mexico - Winner",
        "outcomes": "[\"Argentina\", \"Mexico\"]",
        "outcomePrices": "[\"0.6\", \"0.4\"]",
    }
]


def test_parse_polymarket():
    quotes = parse_polymarket(POLY_PAYLOAD, "2026-06-13T08:00:00")
    assert len(quotes) == 1
    q = quotes[0]
    assert q.source == "polymarket"
    assert q.home == "Argentina" and q.away == "Mexico"
    assert abs(q.home_decimal - (1 / 0.6)) < 1e-6
    assert abs(q.away_decimal - (1 / 0.4)) < 1e-6
    assert abs(q.home_prob - 0.6) < 1e-6          # prob = 1/decimal
    assert q.draw_decimal is None
    assert q.fetched_at == "2026-06-13T08:00:00"


# Codere: forma normalizada {events:[{home,away,odds:{home,draw,away}}]} (decimal).
CODERE_PAYLOAD = {
    "events": [
        {"home": "México", "away": "Canadá",
         "odds": {"home": 2.10, "draw": 3.20, "away": 3.50}},
    ]
}


def test_parse_codere():
    quotes = parse_codere(CODERE_PAYLOAD, "2026-06-13T08:00:00")
    assert len(quotes) == 1
    q = quotes[0]
    assert q.source == "codere"
    assert q.home == "Mexico" and q.away == "Canada"     # normalizados
    assert abs(q.home_decimal - 2.10) < 1e-9
    assert abs(q.draw_decimal - 3.20) < 1e-9
    assert abs(q.away_prob - (1 / 3.50)) < 1e-9
