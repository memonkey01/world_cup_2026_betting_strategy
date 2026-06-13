# Rediseño de la app como workflow — Design

**Fecha:** 2026-06-13
**Goal:** Convertir la app multipágina en un **workflow de 4 etapas** con un hilo
narrativo claro (Laboratorio → Producción) en lugar de páginas sueltas.

## Decisiones (confirmadas con el usuario)

1. El monitor Elo/Bayes (hoy en `app.py`) se **fusiona** en la página Qatar 2022.
2. El fetch de cuotas en Mundial en vivo es **solo por botón manual** (sin auto-fetch).

## Etapas del workflow

```
🏠 Inicio          guía + tablero de estado (¿calendario? ¿estrategia? ¿cuotas?)
   ↓
🧪 Qatar 2022      LAB: configurar → monitor modelo → backtest apuestas → FIJAR
   ↓ (estrategia activa en DB = puente)
🔴 Mundial en vivo PROD: consume estrategia + cuota elegida → recomienda
   ↓
🗄️ Datos           inspección: pd.head() + nº filas + última actualización
```

## Página por página

### 🏠 Inicio (`app.py`)
- Deja de entrenar/monitorear. Pasa a **guía + tablero**.
- Explica el workflow, la DB como fuente de verdad, qué hace cada página.
- **Tablero de estado** con `✅/⬜` por etapa:
  - ¿Hay calendario 2026 en DB? (count Match de World Cup 2026)
  - ¿Hay estrategia activa fijada? (`load_active_strategy`)
  - ¿Cuotas frescas <24h? (`latest_scrape_iso` por fuente)
- `st.page_link` a cada página. Sin controles de modelo en el sidebar.

### 🧪 Qatar 2022 (`pages/2_🧪_Qatar_2022.py`, renombrada desde Simulador)
- **Sidebar (paso a paso, ligado):** `model_controls` (K, prior, margen) +
  `betting_controls` (bankroll, cuota, criterio, peso, umbral, jornada,
  fracciones) + selectbox `sizing` (key `sim_sizing`) + checkbox filtro Bayes
  (key `sim_filter`). De aquí sale **un** `BetParams` (`params`).
- **Cuerpo 1 — Monitor del modelo** (lo que hoy vive en `app.py`): KPIs de
  calibración + tabs Tabla / Evolución Elo / Bayes / Calibración / Combinada.
  Persiste `RatingSnapshot` (clear+rewrite) tras la corrida.
- **Cuerpo 2 — Backtest de apuestas:** `simulate(match_log, params)` →
  KPIs + curva de bankroll + tabla de apuestas. (Comparativa opcional
  "apostar a todos vs filtrado".)
- **Cuerpo 3 — Fijar estrategia:** botón "📌 Guardar configuración actual" que
  hace `save_active_strategy(s, params, label, yield_, roi)` con **los params
  del sidebar** y las métricas de su propio backtest. **Este es el fix clave del
  "ligado".**
- **Expander opcional "🔬 Explorar combinaciones":** `sweep_strategies` (18
  combos, ranking por yield). Un selectbox elige una combo y un botón
  "Aplicar al panel" usa `on_click` para escribir `sim_sizing`,
  `side_criterion`, `sim_filter` en `session_state` y `st.rerun()` → el sidebar
  refleja la combo → el usuario revisa y la fija. Sigue ligado.

### 🔴 Mundial en vivo (`pages/1_…`)
- Sigue en 3 tabs. Cambio: el **selector de fuente de cuotas se mueve del sidebar
  a la tab Cuotas** (key `live_odds_source` en `session_state`), justo donde se
  ven y comparan, y la tab Recomendaciones lo lee para elegir la cuota real.
- Recomendaciones = ELO (lado) · Bayes (filtro) · Kelly (stake) con la
  estrategia activa (o override manual del sidebar).

### 🗄️ Datos (`pages/3_…`)
- Por tabla: **expander** con nº de filas, **`df.head()`**, esquema y
  **"última actualización"** (max de `fetched_at` para Odds, max de `date` para
  Match, `step` máx para RatingSnapshot) para ver si la DB ya se llenó.
- Mantiene el filtro por torneo.

## No cambia
- Capa pura (`elo`, `bayes`, `betting`, `strategies`, `odds`, `odds_store`,
  `dbview`, `pipeline`, `ingest`): sin cambios → los 55 tests siguen verdes.
- Esto es un refactor de UI Streamlit; verificación con `py_compile` + `pytest`.
