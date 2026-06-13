# Diseño — Página en vivo en tabs + hub de cuotas

**Fecha:** 2026-06-13
**Estado:** Aprobado

## Objetivo

Reestructurar la página "Mundial en vivo" en **3 tabs** (Calendario / Cuotas /
Recomendaciones), con una acción dedicada para **actualizar solo cuotas**, un
campo para **pegar una URL** que **detecta la fuente** (Codere/Polymarket) por
dominio, y mover el panel de cuotas del Simulador a la tab de Cuotas.

## Decisiones

| Tema | Decisión |
|------|----------|
| Tabs | **3**: 📅 Calendario (info), 💱 Cuotas (Codere+Polymarket), 🎯 Recomendaciones (lado+stake) |
| URL | `detect_source(url)` por dominio: `codere` / `polymarket` / `None`, con badge |
| Actualizar cuotas | Botón dedicado que **siempre busca al pulsar** (no TTL), independiente del scrape de calendario |
| Duplicación | **Mover** el panel de cuotas del Simulador a la tab Cuotas (Simulador queda backtest + laboratorio) |

## Capa pura — `src/odds.py`

```python
def detect_source(url: str) -> str | None:
    """'codere' si el dominio contiene codere; 'polymarket' si contiene
    polymarket; None en otro caso."""
```

## Página `pages/1_🔴_Mundial_en_vivo.py` (3 tabs)

El sidebar mantiene: `model_controls`, `betting_controls`, botones de sizing,
override, selector de fuente de cuotas, y el scrape de **calendario** ESPN
(`Actualizar (scrape ESPN)` → `ingest_calendar`, ya no toca cuotas).

Tras cargar `calendar`/`finished`/`odds_map`, entrenar `pipe` (finalizados 2026) y
resolver `params` (estrategia activa u override), renderizar:

### Tab 📅 Calendario
- KPIs: partidos en calendario / finalizados / programados.
- Partidos agrupados por fecha: `✅ home g-g away` (finalizado) o `🗓️ home vs away`
  (programado). Sin apuestas.

### Tab 💱 Cuotas (hub; movido del Simulador, con modelo 2026)
- Campo `st.text_input` para **pegar URL** + badge de `detect_source` (Codere /
  Polymarket / no reconocida).
- `st.text_input` query Polymarket (default "World Cup").
- Botón **"💱 Actualizar solo cuotas"** (siempre fetch): Polymarket por query +
  Codere si la URL pegada es de Codere → `ingest_odds`. Mensaje con conteos.
- Tabla por próximo partido: Codere (cuota+prob), Polymarket (cuota+prob),
  **modelo P(home)** (de `pipe` 2026) y **valor = modelo − prob. implícita**.

### Tab 🎯 Recomendaciones
- Por partido programado: `recommend_bet(prematch_rec, bankroll, params, match_odds)`
  con la fuente elegida → `🔵 Apostar: X · stake N @ cuota C` o `⚪ sin apuesta
  (warm-up / filtro)`, + tabla (lado, stake, cuota, p_elo, bayes).

## Simulador `pages/2_💰_Simulador_Apuestas.py`

- **Eliminar** la sección "💱 Cuotas reales" completa (incluido `pipe_live` y los
  imports de `odds`/`odds_store`/`datetime`/`load_calendar` que solo usaba ese panel).
- Conserva: backtest (dos estrategias), curvas, tablas y el laboratorio (barrido +
  fijar estrategia activa).

## Tests

- `tests/test_odds.py`: `detect_source` → codere.mx='codere',
  www.polymarket.com='polymarket', espn.com=None, cadena vacía=None.
- UI: `py_compile` de ambas páginas + smoke sin red del flujo de cuotas
  (detect_source + parse + ingest + tabla).

## Fuera de alcance (YAGNI)

- Persistir la URL de Codere pegada (se mantiene en `session_state`).
- Botones separados por fuente (un solo "Actualizar solo cuotas").
- Validar selectores Codere / endpoint Polymarket contra la red (best-effort).
