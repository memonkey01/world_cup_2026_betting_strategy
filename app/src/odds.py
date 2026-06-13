"""
Capa de cuotas: dataclass normalizada, conversores y parsers puros para
Polymarket (API) y Codere (Playwright). Los fetchers tocan la red y son
best-effort (selectores/endpoint a validar en vivo); el parseo es puro y testeable.
"""
from __future__ import annotations
from dataclasses import dataclass
from statistics import mean
import json
import re

from .scraper import normalize_team

# Nombres en español (Codere) -> canónico del proyecto (= nombres del calendario
# ESPN). Cubre las selecciones del Mundial 2026 vistas en Codere.
ES_NAME_MAP = {
    "México": "Mexico", "Mexico": "Mexico",
    "Estados Unidos": "USA", "EE.UU.": "USA",
    "Canadá": "Canada", "Canada": "Canada",
    "Corea del Sur": "Korea Republic", "Corea": "Korea Republic",
    "Inglaterra": "England", "Brasil": "Brazil", "Países Bajos": "Netherlands",
    "Holanda": "Netherlands",
    "Croacia": "Croatia", "Bélgica": "Belgium", "Alemania": "Germany",
    "España": "Spain", "Francia": "France", "Marruecos": "Morocco",
    # --- ampliación Mundial 2026 ---
    "Catar": "Qatar", "Qatar": "Qatar",
    "Suiza": "Switzerland", "Haití": "Haiti", "Escocia": "Scotland",
    "Australia": "Australia", "Turquía": "Türkiye", "Turquia": "Türkiye",
    "Curazao": "Curaçao", "Japón": "Japan", "Japon": "Japan",
    "Costa de Marfil": "Ivory Coast", "Ecuador": "Ecuador",
    "Suecia": "Sweden", "Túnez": "Tunisia", "Tunez": "Tunisia",
    "Egipto": "Egypt", "Irán": "Iran", "Iran": "Iran",
    "Nueva Zelanda": "New Zealand", "Nueva Zelandia": "New Zealand",
    "Noruega": "Norway", "Irak": "Iraq", "Jordania": "Jordan",
    "Sudáfrica": "South Africa", "Sudafrica": "South Africa",
    "Chequia": "Czechia", "República Checa": "Czechia", "Republica Checa": "Czechia",
    "Bosnia y Herzegovina": "Bosnia-Herzegovina",
    "Bosnia-Herzegovina": "Bosnia-Herzegovina",
    "Cabo Verde": "Cape Verde",
    "Senegal": "Senegal", "Argelia": "Algeria", "Paraguay": "Paraguay",
    "Colombia": "Colombia", "Uzbekistán": "Uzbekistan", "Uzbekistan": "Uzbekistan",
    "Panamá": "Panama", "Uruguay": "Uruguay", "Portugal": "Portugal",
    "Arabia Saudí": "Saudi Arabia", "Arabia Saudita": "Saudi Arabia",
    "Ghana": "Ghana", "Túnez": "Tunisia",
    "RD Congo": "Congo DR", "Congo RD": "Congo DR",
    "República Democrática del Congo": "Congo DR", "R.D. Congo": "Congo DR",
    "Rep. Dem. del Congo": "Congo DR", "Rep. Dem. Congo": "Congo DR",
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
        # El título del partido es "X vs. Y"; los sub-eventos añaden sufijos como
        # " - Exact Score" / " - Halftime Result" / " - More Markets". Los cortamos
        # para no capturar el sufijo como nombre de equipo (esos sub-eventos no
        # traen mercados de ganador, así que igual se descartan abajo).
        title = ev.get("title", "").split(" - ")[0]
        vs = _parse_versus(title)
        if not vs:
            continue
        # Normalizamos AMBOS lados y comparamos por nombre canónico: el título usa
        # a veces otra grafía que el mercado ("Bosnia-Herzegovina" vs "Bosnia and
        # Herzegovina"), así que el match por substring crudo fallaba.
        home, away = normalize_es(vs[0]), normalize_es(vs[1])
        p_home = p_away = p_draw = None
        for mkt in (ev.get("markets") or []):
            question = mkt.get("question") or ""
            try:
                labels = [str(o).strip().lower() for o in json.loads(mkt["outcomes"])]
                prices = [float(p) for p in json.loads(mkt["outcomePrices"])]
            except (KeyError, ValueError, TypeError):
                continue
            if set(labels) != {"yes", "no"}:
                continue
            p_yes = prices[labels.index("yes")]
            if "draw" in question.lower():        # "…end in a draw?"
                p_draw = p_yes
                continue
            mm = re.match(r"\s*will\s+(.+?)\s+win\b", question, re.I)  # "Will X win on…"
            if not mm:
                continue
            team = normalize_es(mm.group(1))
            if team == home:
                p_home = p_yes
            elif team == away:
                p_away = p_yes
        if not (p_home and p_away):               # necesita ambos ganadores
            continue
        out.append(_quote("polymarket", home, away,
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
# Analítica de cuotas: comparación entre casas (pura, testeable).
# ----------------------------------------------------------------------
def book_overround(home_dec, draw_dec, away_dec) -> float:
    """Margen de la casa (*overround* / vig): suma de probabilidades implícitas
    (1/cuota) menos 1. Mayor = la casa se queda con más; un mercado eficiente
    tiende a 0. `draw_dec` puede ser None (mercado a 2 vías)."""
    s = 0.0
    for d in (home_dec, draw_dec, away_dec):
        if d and d > 0:
            s += 1.0 / d
    return s - 1.0


def compare_books(poly: list, codere: list) -> dict:
    """Compara dos listas de cuotas (dicts tipo `latest_odds`) emparejando por
    (home, away). Devuelve {stats, rows}:

    - stats: cobertura (n_poly/n_codere/n_common), divergencia media y máxima de
      P(local), margen medio por casa, y cuántas veces cada casa da la mejor cuota.
    - rows: por partido en común, ordenadas por |Δ P(local)| desc.
    """
    pm = {(o["home"], o["away"]): o for o in poly}
    cm = {(o["home"], o["away"]): o for o in codere}
    common = sorted(set(pm) & set(cm))
    rows, diffs, ov_p, ov_c = [], [], [], []
    best = {"home": {"poly": 0, "codere": 0, "igual": 0},
            "away": {"poly": 0, "codere": 0, "igual": 0}}

    def _best(side, pd_, cd_):
        if pd_ is None or cd_ is None:
            return None
        if abs(pd_ - cd_) < 1e-9:
            best[side]["igual"] += 1
            return "igual"
        if pd_ > cd_:
            best[side]["poly"] += 1
            return "Polymarket"
        best[side]["codere"] += 1
        return "Codere"

    for k in common:
        p, c = pm[k], cm[k]
        d = p["home_prob"] - c["home_prob"]
        diffs.append(abs(d))
        op = book_overround(p["home_decimal"], p.get("draw_decimal"), p["away_decimal"])
        oc = book_overround(c["home_decimal"], c.get("draw_decimal"), c["away_decimal"])
        ov_p.append(op)
        ov_c.append(oc)
        bh = _best("home", p["home_decimal"], c["home_decimal"])
        _best("away", p["away_decimal"], c["away_decimal"])
        rows.append({
            "partido": f"{k[0]} vs {k[1]}",
            "Poly P(local)": round(p["home_prob"], 3),
            "Codere P(local)": round(c["home_prob"], 3),
            "Δ P(local)": round(d, 3),
            "mejor cuota local": bh,
            "margen Poly %": round(op * 100, 1),
            "margen Codere %": round(oc * 100, 1),
        })
    rows.sort(key=lambda r: abs(r["Δ P(local)"]), reverse=True)
    stats = {
        "n_poly": len(pm), "n_codere": len(cm), "n_common": len(common),
        "div_media": mean(diffs) if diffs else 0.0,
        "div_max": max(diffs) if diffs else 0.0,
        "overround_poly": mean(ov_p) if ov_p else 0.0,
        "overround_codere": mean(ov_c) if ov_c else 0.0,
        "best_home": best["home"], "best_away": best["away"],
    }
    return {"stats": stats, "rows": rows}


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


CODERE_URL = "https://apuestas.codere.mx/es_MX/t/69679/Partidos-Mundial-2026"


def fetch_codere(url: str = CODERE_URL) -> dict:
    """Carga Codere (Playwright) y extrae las cuotas 1-X-2 del cupón del Mundial.

    Estructura real del DOM (validada): cada partido es un `tr.mkt` con tres
    `td.seln` (local / empate / visitante); el nombre del equipo está en
    `.seln-name` (el empate trae `.seln-draw-label`) y la cuota decimal en
    `.price.dec`. Devuelve el payload normalizado
    {events:[{home, away, odds:{home, draw, away}}]} con nombres en español
    (los homologa luego `parse_codere` vía `normalize_es`)."""
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
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_selector("tr.mkt .price.dec", state="attached",
                                   timeout=30000)
            page.wait_for_timeout(2000)  # deja que rendericen todas las cuotas
            events = page.evaluate(r"""() => {
                const num = el => {
                    if (!el) return null;
                    const v = parseFloat(el.textContent.trim().replace(',', '.'));
                    return Number.isFinite(v) ? v : null;
                };
                const out = [];
                for (const row of document.querySelectorAll('tr.mkt')) {
                    const selns = [...row.querySelectorAll('td.seln')];
                    const named = selns.filter(s => s.querySelector('.seln-name'));
                    if (named.length < 2) continue;
                    const home = named[0], away = named[named.length - 1];
                    const draw = selns.find(s => s.querySelector('.seln-draw-label'));
                    const dec = s => num(s ? s.querySelector('.price.dec') : null);
                    out.push({
                        home: home.querySelector('.seln-name').textContent.trim(),
                        away: away.querySelector('.seln-name').textContent.trim(),
                        odds: {home: dec(home), away: dec(away), draw: dec(draw)},
                    });
                }
                return out;
            }""")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] codere scrape falló: {e}")
        browser.close()
    return {"events": events}
