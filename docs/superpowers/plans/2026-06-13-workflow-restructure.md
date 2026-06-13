# Rediseño de la app como workflow — Plan

> Ejecutar inline (refactor de UI Streamlit). Verificación: `py_compile` por
> página + `uv run pytest -q` al final (la capa pura no cambia).

**Goal:** Reorganizar las 4 páginas como un workflow Lab→Prod coherente.

**Arquitectura:** `app.py` → Inicio (guía + estado); `pages/2` → Qatar 2022
(monitor + lab + fijar ligado); `pages/1` → selector de cuotas en tab Cuotas;
`pages/3` → expanders con head + última actualización.

---

### Task 1: 🏠 `app.py` → Inicio (menú + tablero de estado)

**Files:** Modify `app/app.py` (reescritura completa).

- [ ] Quitar el monitor Elo/Bayes (se va a Qatar 2022).
- [ ] Título "🏠 Mundial 2026 — Elo + Bayes + Apuestas". Explicación del
  workflow de 4 etapas y la DB como fuente de verdad.
- [ ] Tablero de estado: abrir sesión, calcular
  - `n_cal` = nº Match del torneo "World Cup 2026"
  - `active` = `load_active_strategy(s)`
  - `cuotas_iso` = `latest_scrape_iso(s, wc, "polymarket")` / `"codere"`
  mostrar `✅/⬜` + detalle por etapa.
- [ ] `st.page_link("pages/2_🧪_Qatar_2022.py", ...)`, idem en vivo y Datos.
- [ ] Verificar: `cd app && uv run python -m py_compile app.py` → sin error.
- [ ] Commit: `refactor(ui): app.py pasa a Inicio (guía + tablero de estado del workflow)`.

### Task 2: 🧪 Renombrar Simulador → Qatar 2022 (monitor + ligado)

**Files:** Crear `app/pages/2_🧪_Qatar_2022.py`, borrar
`app/pages/2_💰_Simulador_Apuestas.py`.

- [ ] Copiar la base del simulador. Sidebar: `model_controls()` +
  `betting_controls()` + `sizing` selectbox (key `sim_sizing`) + filtro Bayes
  checkbox (key `sim_filter`). `params = BetParams(sizing=sizing,
  use_bayes_filter=use_filter, **common)`.
- [ ] **Cuerpo 1 — Monitor:** portar de `app.py` los KPIs de calibración y los 5
  tabs (Tabla / Evolución Elo / Bayes / Calibración / Combinada) + persistir
  snapshots (`clear_snapshots`+`persist_snapshots`).
- [ ] **Cuerpo 2 — Backtest:** `res = simulate(pipe.match_log, params)` →
  KPIs + curva + tabla. Comparativa all vs filtrado opcional en un expander.
- [ ] **Cuerpo 3 — Fijar:** botón "📌 Guardar configuración actual como
  estrategia activa" → `save_active_strategy(s, params, label, yield_=res["yield"],
  roi=res["roi"])`. `label` describe sizing+criterio+filtro.
- [ ] **Expander sweep:** `sweep_strategies(pipe.match_log, BetParams(**common))`
  → tabla ranking. selectbox de combo + botón "Aplicar al panel" con
  `on_click=cb` que setea `st.session_state["sim_sizing"|"side_criterion"|"sim_filter"]`
  y `st.rerun()`.
- [ ] Verificar `py_compile` de la página nueva; `git rm` la vieja.
- [ ] Commit: `feat(ui): página Qatar 2022 (monitor + lab) con sidebar ligado a fijar`.

### Task 3: 🔴 Mundial en vivo — selector de fuente en tab Cuotas

**Files:** Modify `app/pages/1_🔴_Mundial_en_vivo.py`.

- [ ] Quitar el selectbox `live_odds_source` del sidebar.
- [ ] En la tab Cuotas, tras la tabla comparativa, añadir
  `st.selectbox("Fuente para recomendaciones", ["polymarket","codere","cuota fija"],
  key="live_odds_source")`. Default vía `session_state.setdefault`.
- [ ] La tab Recomendaciones lee `st.session_state.get("live_odds_source",
  "polymarket")` para construir `odds_map`/`mo` (mover la lectura de `odds_map`
  dentro del flujo, después de conocer la fuente).
- [ ] Verificar `py_compile`.
- [ ] Commit: `refactor(ui): selector de fuente de cuotas vive en la tab Cuotas`.

### Task 4: 🗄️ Datos — expanders + head + última actualización

**Files:** Modify `app/pages/3_🗄️_Datos.py`.

- [ ] Por tabla, envolver en `st.expander(f"{label} — {len(rows)} filas", ...)`.
- [ ] Mostrar `pd.DataFrame(rows).head(10)` en vez de toda la tabla; nota de
  "mostrando 10 de N".
- [ ] "Última actualización": helper inline que toma el max de `fetched_at`
  (Odds), `date` (Match), o `step` (RatingSnapshot) si la columna existe en rows.
- [ ] Mantener esquema y filtro por torneo.
- [ ] Verificar `py_compile`.
- [ ] Commit: `refactor(ui): Datos con expanders, head() y última actualización`.

### Task 5: Docs + tests

**Files:** Modify `README.md`, `CLAUDE.md`.

- [ ] Actualizar tabla de páginas y descripción del workflow en ambos.
- [ ] `cd app && uv run pytest -q` → 55 passed.
- [ ] Commit: `docs: workflow de 4 etapas (Inicio/Qatar/En vivo/Datos)`.
