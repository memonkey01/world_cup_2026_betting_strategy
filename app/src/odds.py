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


def detect_source(url: str) -> str | None:
    """Detecta la fuente de cuotas por dominio: 'codere' | 'polymarket' | None."""
    u = (url or "").lower()
    if "codere" in u:
        return "codere"
    if "polymarket" in u:
        return "polymarket"
    return None


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


def select_markets(payload: list, pattern: str | None = None) -> list:
    """Filtra mercados crudos de la Gamma API por regex (case-insensitive) sobre
    `question`/`slug`/`title`. Filtro client-side, complementario al `search`
    server-side de `fetch_polymarket`.

    - `pattern` vacío/None => devuelve TODOS (sin filtrar).
    - Regex inválida => devuelve TODOS (no rompe la UI; el caller puede avisar).
    """
    if not pattern:
        return list(payload)
    try:
        rx = re.compile(pattern, re.I)
    except re.error:
        return list(payload)
    out = []
    for mkt in payload:
        text = " ".join(str(mkt.get(k, "")) for k in ("question", "slug", "title"))
        if rx.search(text):
            out.append(mkt)
    return out


DRAW_LABELS = {"draw", "tie", "empate", "x"}


def parse_polymarket(payload: list, fetched_at: str) -> list[OddsQuote]:
    """Soporta tres formas de mercado de Polymarket:
    (1) 2 outcomes = equipos (moneyline sin empate);
    (2) Yes/No 'Will X beat Y' que se emparejan por partido (frozenset{equipos});
    (3) 3 outcomes 'Equipo A / Empate / Equipo B' (incluye `draw_decimal`)."""
    out: list[OddsQuote] = []
    pending: dict[frozenset, tuple[str, float]] = {}  # par -> (equipo, P(Yes))
    for mkt in payload:
        try:
            outcomes = json.loads(mkt["outcomes"])
            prices = [float(p) for p in json.loads(mkt["outcomePrices"])]
        except (KeyError, ValueError, TypeError):
            continue
        labels = [str(o).strip().lower() for o in outcomes]

        # (3) Moneyline 1-X-2: 3 outcomes, uno de ellos es el empate.
        if len(outcomes) == 3 and len(prices) == 3:
            draw_idx = next((i for i, l in enumerate(labels) if l in DRAW_LABELS), None)
            if draw_idx is None:
                continue
            hi, ai = [i for i in range(3) if i != draw_idx]
            out.append(_quote("polymarket",
                              normalize_es(outcomes[hi]), normalize_es(outcomes[ai]),
                              price_to_decimal(prices[hi]), price_to_decimal(prices[ai]),
                              price_to_decimal(prices[draw_idx]), fetched_at))
            continue

        if len(outcomes) != 2 or len(prices) != 2:
            continue
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


def parse_polymarket_events(events: list, fetched_at: str) -> list[OddsQuote]:
    """Parsea eventos de partido de Polymarket a una cuota por partido.

    Cada evento tiene título "X vs. Y" y mercados Yes/No:
    "Will X win on FECHA?", "Will Y win on FECHA?", "Will X vs. Y end in a draw?".
    Se toma P(Yes) de cada uno: home/away = los win, draw = el de empate.
    Devuelve un OddsQuote por evento con título emparejable (y ambos ganadores)."""
    out: list[OddsQuote] = []
    for ev in events:
        vs = _parse_versus(ev.get("title", ""))
        if not vs:
            continue
        raw_home, raw_away = vs[0].lower(), vs[1].lower()
        p_home = p_away = p_draw = None
        for mkt in (ev.get("markets") or []):
            q = (mkt.get("question") or "").lower()
            try:
                labels = [str(o).strip().lower() for o in json.loads(mkt["outcomes"])]
                prices = [float(p) for p in json.loads(mkt["outcomePrices"])]
            except (KeyError, ValueError, TypeError):
                continue
            if set(labels) != {"yes", "no"}:
                continue
            p_yes = prices[labels.index("yes")]
            if "draw" in q:                       # "…end in a draw?"
                p_draw = p_yes
            elif raw_home in q:                   # "Will X win on…"
                p_home = p_yes
            elif raw_away in q:                   # "Will Y win on…"
                p_away = p_yes
        if not (p_home and p_away):               # necesita ambos ganadores
            continue
        out.append(_quote("polymarket", normalize_es(vs[0]), normalize_es(vs[1]),
                          price_to_decimal(p_home), price_to_decimal(p_away),
                          price_to_decimal(p_draw) if p_draw else None, fetched_at))
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
POLYMARKET_GAMMA = "https://gamma-api.polymarket.com"
WORLD_CUP_TAG_ID = 102232  # tag "FIFA World Cup 2026" en la Gamma API


def fetch_polymarket(tag_id: int = WORLD_CUP_TAG_ID, max_events: int = 500,
                     query: str | None = None) -> list:
    """Trae los eventos de un *tag* de Polymarket (default FIFA World Cup 2026 =
    102232) **paginando** `/events` (limit máx 100 por página, vía `offset`) y
    devuelve la lista de **eventos** (cada evento trae su título "X vs. Y" y un
    array `markets` con los mercados Yes/No "Will X win…", "…end in a draw?").

    La Gamma API **no tiene búsqueda de texto**: por eso filtramos por `tag_id`
    (lo correcto para el Mundial) y, si se pasa, `query` filtra eventos por
    substring en título/slug (client-side). El parseo a cuota por partido lo hace
    `parse_polymarket_events`; el filtro fino por equipo, `select_markets` (regex)."""
    import urllib.parse
    import urllib.request
    page_size = 100  # máximo que admite la Gamma API por request
    events: list = []
    offset = 0
    while len(events) < max_events:
        params = urllib.parse.urlencode({
            "tag_id": tag_id, "active": "true", "closed": "false",
            "limit": min(page_size, max_events - len(events)), "offset": offset})
        url = f"{POLYMARKET_GAMMA}/events?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                page = json.loads(r.read().decode("utf-8"))
            if isinstance(page, dict):
                page = page.get("data", [])
        except Exception as e:  # noqa: BLE001
            print(f"[warn] polymarket events fetch falló (offset {offset}): {e}")
            break
        if not page:
            break
        events.extend(page)
        if len(page) < page_size:   # última página
            break
        offset += len(page)

    if query:
        q = query.lower()
        events = [e for e in events
                  if q in f'{e.get("title", "")} {e.get("slug", "")}'.lower()]
    return events


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
