"""
Capa de cuotas: dataclass normalizada, conversores y parsers puros para
Polymarket (API) y Codere (Playwright). Los fetchers tocan la red y son
best-effort (selectores/endpoint a validar en vivo); el parseo es puro y testeable.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import re

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


_VERSUS_PATTERNS = [
    re.compile(r"^will\s+(.+?)\s+beat\s+(.+?)\??$", re.I),
    re.compile(r"^will\s+(.+?)\s+win\s+vs\.?\s+(.+?)\??$", re.I),
    re.compile(r"^will\s+(.+?)\s+win\s+against\s+(.+?)\??$", re.I),
    re.compile(r"^(.+?)\s+vs\.?\s+(.+?)\??$", re.I),
]


def _parse_versus(question: str) -> tuple[str, str] | None:
    """Extrae (equipo, rival) de la pregunta de un mercado Yes/No. None si no aplica."""
    q = (question or "").strip()
    for pat in _VERSUS_PATTERNS:
        m = pat.match(q)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return None


def parse_polymarket(payload: list, fetched_at: str) -> list[OddsQuote]:
    """Soporta (1) mercados de 2 outcomes = equipos, y (2) mercados Yes/No
    'Will X beat Y' que se emparejan por partido (clave frozenset{equipos})."""
    out: list[OddsQuote] = []
    pending: dict[frozenset, tuple[str, float]] = {}  # par -> (equipo, P(Yes))
    for mkt in payload:
        try:
            outcomes = json.loads(mkt["outcomes"])
            prices = [float(p) for p in json.loads(mkt["outcomePrices"])]
        except (KeyError, ValueError, TypeError):
            continue
        if len(outcomes) != 2 or len(prices) != 2:
            continue
        labels = [str(o).strip().lower() for o in outcomes]
        if set(labels) == {"yes", "no"}:
            vs = _parse_versus(mkt.get("question", ""))
            if not vs:
                continue
            team, opp = normalize_es(vs[0]), normalize_es(vs[1])
            p_yes = prices[labels.index("yes")]
            key = frozenset((team, opp))
            if key in pending:
                home, p_home = pending.pop(key)
                away = opp if home == team else team
                out.append(_quote("polymarket", home, away,
                                  price_to_decimal(p_home), price_to_decimal(p_yes),
                                  None, fetched_at))
            else:
                pending[key] = (team, p_yes)
        else:
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


# ----------------------------------------------------------------------
# Fetchers de red (best-effort; selectores/endpoint a validar en vivo).
# No se cubren con unit-tests: el parseo (arriba) sí.
# ----------------------------------------------------------------------
POLYMARKET_GAMMA = "https://gamma-api.polymarket.com/markets"


def fetch_polymarket(query: str = "World Cup", limit: int = 100) -> list:
    """Consulta la Gamma API de Polymarket y devuelve la lista de mercados (cruda).
    El filtrado/forma exacta puede requerir ajuste contra la API real."""
    import urllib.parse
    import urllib.request
    params = urllib.parse.urlencode({"active": "true", "closed": "false",
                                     "limit": limit, "search": query})
    url = f"{POLYMARKET_GAMMA}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data if isinstance(data, list) else data.get("data", [])
    except Exception as e:  # noqa: BLE001
        print(f"[warn] polymarket fetch falló: {e}")
        return []


CODERE_URL = "https://www.codere.mx/apuestas-deportivas/deportes/futbol"


def fetch_codere(url: str = CODERE_URL) -> dict:
    """Carga Codere con Playwright y extrae cuotas. Devuelve el payload normalizado
    {events:[{home,away,odds:{home,draw,away}}]}. Los selectores son best-effort."""
    from playwright.sync_api import sync_playwright
    events: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"))
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            # best-effort: cada evento con dos equipos y 3 cuotas (1-X-2)
            for ev in page.query_selector_all("[data-testid='event'], .event"):
                names = ev.query_selector_all(
                    "[data-testid='participant'], .participant-name")
                odds = ev.query_selector_all(
                    "[data-testid='odd'], .odd-value, .sportsbook-odds")
                if len(names) >= 2 and len(odds) >= 3:
                    def num(el):
                        try:
                            return float(el.inner_text().strip().replace(",", "."))
                        except ValueError:
                            return 0.0
                    events.append({
                        "home": names[0].inner_text().strip(),
                        "away": names[1].inner_text().strip(),
                        "odds": {"home": num(odds[0]), "draw": num(odds[1]),
                                 "away": num(odds[2])},
                    })
        except Exception as e:  # noqa: BLE001
            print(f"[warn] codere scrape falló: {e}")
        browser.close()
    return {"events": events}
