"""
Scraper de resultados del Mundial desde ESPN usando Playwright (headless).

ESPN expone un endpoint JSON interno (site.api.espn.com) que es MUCHO mas
estable que parsear HTML. Playwright se usa para:
  (a) navegar la pagina del fixture y dejar que cargue,
  (b) interceptar / disparar la llamada al scoreboard API,
  (c) caer a parseo de DOM solo si el API falla.

Estrategia recomendada: pegarle directo al scoreboard API (mas robusto),
y usar Playwright como fallback para fechas donde el API cambie de formato.

Endpoint (men's World Cup, liga id FIFA.WORLD):
  https://site.api.espn.com/apis/site/v2/sports/soccer/FIFA.WORLD/scoreboard?dates=YYYYMMDD

Para Qatar 2022 backtest, las fechas van del 20221120 al 20221218.
Para 2026, ajustar el rango de fechas del torneo.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
import json


ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/"
    "{league}/scoreboard?dates={date}"
)


# Mapa ESPN displayName -> nombre canónico interno (coincide con FIFA snapshot).
ESPN_NAME_MAP = {
    "United States": "USA",
    "IR Iran": "Iran",
    "Iran": "Iran",
    "South Korea": "Korea Republic",
    "Korea Republic": "Korea Republic",
    "Republic of Korea": "Korea Republic",
    "Saudi Arabia": "Saudi Arabia",
}

# Variantes de nombre entre fuentes (Polymarket / intl) -> canónico del proyecto.
# Homologa el calendario (ESPN) con las cuotas: Polymarket usa otras grafías para
# algunas selecciones. Se aplica en normalize_team, así TODAS las fuentes convergen.
ALT_NAME_MAP = {
    "Cabo Verde": "Cape Verde",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "DR Congo": "Congo DR",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
}


def normalize_team(name: str) -> str:
    """Normaliza el nombre (ESPN/Polymarket/Codere) al canónico del proyecto."""
    n = (name or "").strip()
    n = ESPN_NAME_MAP.get(n, n)
    return ALT_NAME_MAP.get(n, n)


def normalize_stage(raw: str | None) -> str:
    """Mapea etiquetas de fase de ESPN a STAGE_ORDER (default 'group')."""
    if not raw:
        return "group"
    s = raw.lower()
    if "round of 16" in s or s.strip() == "r16":
        return "R16"
    if "quarter" in s:
        return "QF"
    if "semi" in s:
        return "SF"
    if "3rd" in s or "third" in s:
        return "3rd"
    if "final" in s:
        return "final"
    return "group"


@dataclass
class MatchResult:
    date: str
    stage: str
    home: str
    away: str
    home_goals: int
    away_goals: int
    status: str  # "STATUS_FULL_TIME", "STATUS_SCHEDULED", etc.
    event_id: str | None = None

    @property
    def finished(self) -> bool:
        return self.status in ("STATUS_FULL_TIME", "STATUS_FINAL", "STATUS_FT")


def parse_scoreboard_json(payload: dict) -> list[MatchResult]:
    """Parsea la respuesta del scoreboard API de ESPN."""
    results: list[MatchResult] = []
    for event in payload.get("events", []):
        comp = event.get("competitions", [{}])[0]
        status = comp.get("status", {}).get("type", {}).get("name", "UNKNOWN")
        competitors = comp.get("competitors", [])
        if len(competitors) != 2:
            continue
        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
        try:
            hg = int(home.get("score", 0))
            ag = int(away.get("score", 0))
        except (ValueError, TypeError):
            hg, ag = 0, 0
        headline = (comp.get("notes", [{}])[0].get("headline")
                    if comp.get("notes") else None)
        results.append(MatchResult(
            date=event.get("date", "")[:10],
            stage=normalize_stage(headline),
            home=normalize_team(home.get("team", {}).get("displayName", "?")),
            away=normalize_team(away.get("team", {}).get("displayName", "?")),
            home_goals=hg, away_goals=ag, status=status,
            event_id=str(event.get("id")) if event.get("id") is not None else None,
        ))
    return results


def fetch_via_playwright(date_range: str, league: str = "fifa.world") -> list[MatchResult]:
    """
    Usa Playwright para pedir el JSON del scoreboard. Playwright maneja
    headers/cookies/anti-bot mejor que requests pelado.

    date_range: "YYYYMMDD" o rango "YYYYMMDD-YYYYMMDD" (una sola llamada).
    """
    from playwright.sync_api import sync_playwright

    all_results: list[MatchResult] = []
    url = ESPN_SCOREBOARD.format(league=league, date=date_range)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36")
        )
        page = ctx.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=25000)
            if resp and resp.ok:
                body = page.evaluate("() => document.body.innerText")
                payload = json.loads(body)
                all_results.extend(parse_scoreboard_json(payload))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] rango {date_range} fallo: {e}")
        browser.close()
    return all_results


def fetch_via_requests(date_range: str, league: str = "fifa.world") -> list[MatchResult]:
    """Fallback ligero sin navegador (mas rapido, mas fragil)."""
    import urllib.request
    url = ESPN_SCOREBOARD.format(league=league, date=date_range)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            payload = json.loads(r.read().decode("utf-8"))
            return parse_scoreboard_json(payload)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] rango {date_range} fallo: {e}")
        return []


def qatar_2022_range() -> str:
    """Rango Qatar 2022 para una sola llamada."""
    return "20221120-20221218"


def save_results(results: list[MatchResult], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=2)
