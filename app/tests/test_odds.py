"""Tests de la capa pura de cuotas (conversores + parsers con fixtures)."""
from src.odds import (OddsQuote, price_to_decimal, american_to_decimal,
                      implied_prob, normalize_es, parse_polymarket, parse_codere,
                      _parse_versus, detect_source, select_markets,
                      parse_polymarket_events)


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


def test_normalize_homologa_polymarket():
    # Variantes de Polymarket -> canónico del calendario (ESPN). Homologación.
    assert normalize_es("Cabo Verde") == "Cape Verde"
    assert normalize_es("Côte d'Ivoire") == "Ivory Coast"
    assert normalize_es("DR Congo") == "Congo DR"
    assert normalize_es("Bosnia and Herzegovina") == "Bosnia-Herzegovina"
    assert normalize_es("South Korea") == "Korea Republic"


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


def test_parse_versus_patterns():
    assert _parse_versus("Will Argentina beat France?") == ("Argentina", "France")
    assert _parse_versus("Will Mexico win vs Canada") == ("Mexico", "Canada")
    assert _parse_versus("Brazil vs Croatia") == ("Brazil", "Croatia")
    assert _parse_versus("Who wins the World Cup?") is None


# Dos mercados Yes/No del mismo partido -> un OddsQuote emparejado.
POLY_YESNO = [
    {"question": "Will Argentina beat France?",
     "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.6\", \"0.4\"]"},
    {"question": "Will France beat Argentina?",
     "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.4\", \"0.6\"]"},
]


def test_parse_polymarket_yesno_pairs():
    quotes = parse_polymarket(POLY_YESNO, "2026-06-13T08:00:00")
    assert len(quotes) == 1
    q = quotes[0]
    assert {q.home, q.away} == {"Argentina", "France"}
    if q.home == "Argentina":
        assert abs(q.home_prob - 0.6) < 1e-6
        assert abs(q.away_prob - 0.4) < 1e-6


def test_parse_polymarket_yesno_unpaired_ignored():
    one = [{"question": "Will Argentina beat France?",
            "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.6\", \"0.4\"]"}]
    assert parse_polymarket(one, "2026-06-13T08:00:00") == []


def test_detect_source():
    assert detect_source("https://www.codere.mx/apuestas/futbol") == "codere"
    assert detect_source("https://polymarket.com/event/world-cup") == "polymarket"
    assert detect_source("https://www.espn.com/soccer") is None
    assert detect_source("") is None


# Estructura real de un partido en Polymarket: un evento "X vs. Y" con tres
# mercados Yes/No ("Will X win…", "Will Y win…", "…end in a draw?").
POLY_EVENTS = [{
    "title": "Qatar vs. Switzerland",
    "slug": "fifwc-qat-che-2026-06-13",
    "markets": [
        {"question": "Will Qatar vs. Switzerland end in a draw?",
         "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.135\", \"0.865\"]"},
        {"question": "Will Switzerland win on 2026-06-13?",
         "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.815\", \"0.185\"]"},
        {"question": "Will Qatar win on 2026-06-13?",
         "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.0605\", \"0.9395\"]"},
    ],
}]


def test_parse_polymarket_events():
    quotes = parse_polymarket_events(POLY_EVENTS, "2026-06-13T08:00:00")
    assert len(quotes) == 1
    q = quotes[0]
    assert q.home == "Qatar" and q.away == "Switzerland"
    assert abs(q.home_prob - 0.0605) < 1e-6        # P(Qatar gana)
    assert abs(q.away_prob - 0.815) < 1e-6         # P(Switzerland gana)
    assert q.draw_decimal is not None and abs(q.draw_decimal - 1 / 0.135) < 1e-6


def test_parse_polymarket_events_homologa_y_ignora_subeventos():
    events = [
        # Partido con nombre que difiere del calendario -> debe homologarse.
        {"title": "Spain vs. Cabo Verde",
         "markets": [
             {"question": "Will Spain win on 2026-06-20?",
              "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.9\", \"0.1\"]"},
             {"question": "Will Cabo Verde win on 2026-06-20?",
              "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.05\", \"0.95\"]"},
         ]},
        # Sub-evento con sufijo: no trae mercados de ganador -> se ignora.
        {"title": "Spain vs. Cabo Verde - Exact Score",
         "markets": [{"question": "Spain 2-0", "outcomes": "[\"Yes\", \"No\"]",
                      "outcomePrices": "[\"0.1\", \"0.9\"]"}]},
    ]
    quotes = parse_polymarket_events(events, "t")
    assert len(quotes) == 1
    assert quotes[0].home == "Spain" and quotes[0].away == "Cape Verde"


def test_parse_polymarket_events_skips_non_match():
    # Mercado de campeón (no es un partido) -> sin título "X vs Y" -> ignorado.
    champ = [{"title": "Will Spain win the 2026 FIFA World Cup?",
              "markets": [{"question": "Will Spain win the 2026 FIFA World Cup?",
                           "outcomes": "[\"Yes\", \"No\"]",
                           "outcomePrices": "[\"0.16\", \"0.84\"]"}]}]
    assert parse_polymarket_events(champ, "t") == []


# Mercado de 3 outcomes (Equipo A / Empate / Equipo B) -> incluye draw_decimal.
POLY_3WAY = [{
    "question": "Mexico vs Canada",
    "outcomes": "[\"Mexico\", \"Draw\", \"Canada\"]",
    "outcomePrices": "[\"0.5\", \"0.3\", \"0.2\"]",
}]


def test_parse_polymarket_threeway():
    quotes = parse_polymarket(POLY_3WAY, "2026-06-13T08:00:00")
    assert len(quotes) == 1
    q = quotes[0]
    assert q.home == "Mexico" and q.away == "Canada"
    assert abs(q.home_prob - 0.5) < 1e-6
    assert abs(q.away_prob - 0.2) < 1e-6
    assert q.draw_decimal is not None and abs(q.draw_decimal - 1 / 0.3) < 1e-6


def test_select_markets_regex():
    payload = [
        {"question": "Argentina vs France"},
        {"question": "Will Brazil win the World Cup?"},
        {"slug": "mexico-vs-canada-2026"},
    ]
    assert len(select_markets(payload, None)) == 3      # sin patrón -> todos
    assert len(select_markets(payload, "")) == 3
    out = select_markets(payload, r"argentina|mexico")  # casa question y slug
    assert len(out) == 2
    assert {m.get("question", m.get("slug")) for m in out} == {
        "Argentina vs France", "mexico-vs-canada-2026"}
    assert select_markets(payload, "[bad(") == payload  # regex inválida -> todos
