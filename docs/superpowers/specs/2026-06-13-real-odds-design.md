# Diseño — Cuotas reales (Codere + Polymarket)

**Fecha:** 2026-06-13
**Estado:** Aprobado

## Objetivo

Leer cuotas reales de **Codere.mx** (Playwright) y de la **API de Polymarket**,
guardarlas en la DB (histórico), mostrarlas/compararlas en el **Simulador**, y
usarlas en las **recomendaciones en vivo** (la cuota real por partido reemplaza la
cuota fija). Scraping bajo acción del usuario con caché diario (TTL 24h).

## Decisiones

| Tema | Decisión |
|------|----------|
| Uso | Las cuotas reales **alimentan `recommend_bet`** en la página en vivo; el Simulador las muestra/compara |
| Cadencia | Botón "Actualizar cuotas" + caché en DB con **TTL 24h** (no re-scrapea si <24h salvo "Forzar"). Sin scheduler externo |
| Persistencia | Tabla `Odds` **histórica** (una fila por scrape) |
| Fuentes | **Ambas**: Codere (Playwright) + Polymarket (API). Parseo puro testeable; fetchers best-effort |
| Default en vivo | Fuente **Polymarket** (API más estable); selector para cambiar a Codere |
| Mercado | **"gana el equipo"** (home/away decimal). `draw_decimal` se guarda pero no se usa para apostar |

## Capa pura — `src/odds.py`

```python
@dataclass
class OddsQuote:
    source: str            # 'codere' | 'polymarket'
    home: str              # nombre canónico (normalizado)
    away: str
    home_decimal: float
    away_decimal: float
    draw_decimal: float | None
    home_prob: float       # 1/home_decimal
    away_prob: float       # 1/away_decimal
    fetched_at: str        # ISO

def price_to_decimal(p: float) -> float      # 1/p (Polymarket da precio 0..1)
def american_to_decimal(a: int) -> float     # +150 -> 2.5 ; -120 -> 1.833
def implied_prob(decimal: float) -> float    # 1/decimal
def normalize_es(name: str) -> str           # "México"->"Mexico", "Estados Unidos"->"USA"... + normalize_team

def parse_polymarket(payload: dict, fetched_at: str) -> list[OddsQuote]
def parse_codere(payload: dict, fetched_at: str) -> list[OddsQuote]
```
- `parse_*` construyen `OddsQuote` con nombres normalizados y prob = `1/decimal`.
- Fetchers (red, best-effort, **sin unit-test**):
  - `fetch_polymarket(query)` — Gamma API vía `urllib`; devuelve el payload crudo.
  - `fetch_codere(url)` — Playwright carga codere.mx y extrae el JSON/DOM de cuotas.
- Selectores de Codere y slug/shape de Polymarket: **best-effort**, a validar en vivo.

## Persistencia — modelo `Odds` (`models.py`) + `src/odds_store.py`

### `Odds` (SQLModel)
`id, tournament_id (FK), home_team_id (FK), away_team_id (FK), date, source,
home_decimal, away_decimal, draw_decimal (nullable), home_prob, away_prob,
fetched_at`.

### `src/odds_store.py`
```python
def ingest_odds(session, tournament, quotes: list[OddsQuote]) -> int
    # resuelve equipos por nombre (get_or_create_team), inserta una fila por quote (histórico)
def latest_odds(session, tournament, source: str | None = None) -> list[dict]
    # la fila más reciente por (home,away,source); si source dado, filtra
def latest_scrape_iso(session, tournament, source: str) -> str | None
    # max(fetched_at) para esa fuente -> drive del TTL 24h
```

## Simulador — sección "Cuotas reales"

- Botón **"Actualizar cuotas (Codere + Polymarket)"**. Si `latest_scrape_iso` es
  <24h, muestra aviso "última actualización: …" y un checkbox **"Forzar"**; si no
  se fuerza, no re-scrapea.
- Al scrapear: `fetch_polymarket` + `fetch_codere` → `parse_*` → `ingest_odds`.
- Tabla comparativa por próximo partido (de `load_calendar`, no finalizados):
  columnas Codere (home/away + prob), Polymarket (home/away + prob), prob del
  modelo (`pipe.prematch_rec`) y **valor = prob_modelo − prob_implícita** del lado
  favorito.

## Mundial en vivo — usa cuotas reales

- Selector **"Fuente de cuotas"** (Polymarket por defecto / Codere).
- `recommend_bet(rec, bankroll, params, match_odds=None)`:
  - `match_odds` = `{"home": dec, "away": dec}` (de `latest_odds` para ese partido).
  - Tras `pick_side`, si hay cuota real para el lado elegido, usa esa cuota para el
    sizing/Kelly vía `replace(params, odds=...)` y la incluye en el dict devuelto
    (`"odds"`). Si no hay, cae a `params.odds`.
- El backtest (`simulate` sobre Qatar) **no cambia** (cuota fija).

## Tests

- `tests/test_odds.py`: `price_to_decimal`/`american_to_decimal`/`implied_prob`;
  `parse_polymarket` y `parse_codere` con fixtures → `OddsQuote` con nombres
  normalizados (incluye un caso ES "México") y prob = 1/decimal.
- `tests/test_odds_store.py`: `ingest_odds` inserta histórico; `latest_odds`
  devuelve la más reciente por (partido, fuente); `latest_scrape_iso` el máximo.
- `tests/test_betting.py`: `recommend_bet` con `match_odds` usa la cuota del lado
  elegido (Kelly cambia) y la reporta; sin `match_odds` usa `params.odds`.

## Fuera de alcance (YAGNI)

- Scheduler externo (cron) — solo botón + TTL 24h.
- Mercado 1X2 completo / apostar al empate — solo "gana el equipo".
- Arbitraje entre fuentes; movimiento de líneas (aunque el histórico lo permitiría después).
