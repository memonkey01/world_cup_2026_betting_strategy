# Mundial Elo + Bayes Monitor

Sistema de puntuación Elo para el Mundial, con capa bayesiana sobre juego
binario (empate = medio punto, estilo ajedrez), scraping de ESPN vía
Playwright y monitor en Streamlit que se actualiza al cerrar cada jornada.

## Lógica

1. **Semilla FIFA → Elo.** El ranking FIFA (sistema tipo-Elo desde 2018) se
   re-centra a la escala Elo clásica (~1500 media). Ver `src/fifa_seed.py`.
2. **Elo por rondas.** `R' = R + K·(S − E)`, con `S ∈ {1, 0.5, 0}` y `E`
   sigmoide logística. Multiplicador opcional por margen de gol. `src/elo.py`.
3. **Bayes binario.** Cada equipo tiene `θ ~ Beta(a,b)` (prior anclado al Elo).
   Cada partido es un Bernoulli con empate = 0.5 éxito → posterior conjugado.
   Da media + intervalo de credibilidad. `src/bayes.py`.
4. **Validación de la distribución.** Las probabilidades del Elo (emitidas
   *antes* de cada partido) se contrastan contra resultados con Brier, LogLoss
   y curva de fiabilidad. `src/bayes.py` + `src/pipeline.py`.

## Requisitos

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** (gestor de entorno y dependencias). Instalar:
  - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

`uv` instala el resto (streamlit, pandas, playwright, sqlmodel) por ti. No hace
falta crear el venv a mano.

## Cómo correrlo

Todos los comandos se ejecutan **desde la carpeta `app/`**.

```bash
cd app
uv sync                          # 1. crea .venv/ e instala dependencias
uv run streamlit run app.py      # 2. abre el monitor en el navegador
```

Streamlit imprime una URL local (por defecto http://localhost:8501) y la abre
sola. La app es un **workflow de 4 etapas** (ver «Páginas» abajo): **🏠 Inicio**
(guía + estado), **🧪 Qatar 2022** (laboratorio, *no necesita red*), **🔴 Mundial
en vivo** (producción) y **🗄️ Datos**.

Para el modo en vivo (scrape de ESPN) instala una sola vez el navegador:

```bash
uv run playwright install chromium    # solo para "Mundial en vivo"
```

En esa página pones el rango de fechas, pulsas «Actualizar (scrape ESPN)» y se
guarda **todo el calendario** (finalizados + programados) en la DB.

### Tests

```bash
uv run pytest -q                 # tests sin red
```

### Base de datos

La base de datos SQLite (`app/data/worldcup.db`) es la **fuente de verdad**: el
scraper la llena con partidos y el pipeline Elo/Bayes lee de ella. Se crea sola
en el primer arranque y está en `.gitignore`. Para empezar de cero, basta con
borrarla:

```bash
rm app/data/worldcup.db          # Windows PowerShell: Remove-Item app/data/worldcup.db
```

Endpoint ESPN que usa el scraper (sin API key):
`https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=YYYYMMDD-YYYYMMDD`

## Resultado del backtest (Qatar 2022, K=40)

- Brier ≈ **0.124** (azar = 0.25) → Elo bien calibrado partiendo de FIFA.
- Argentina (campeón) penalizada por la derrota vs Arabia Saudita; Francia
  lidera Elo por márgenes de gol amplios. Coherente con la realidad.

## Limitación conocida (parte 2)

El modelo Bayes binario trata partidos como ensayos independientes y **no usa
la fuerza del rival** ni los goles. Es interpretable y es lo pedido, pero para
fútbol un **Bradley-Terry** (fuerza relativa) o **Poisson/Dixon-Coles** (goles)
predice mejor. Recomendado para la siguiente iteración, reusando el mismo
pipeline de scraping y la misma capa de calibración.

## Estructura

```
src/elo.py            # Elo + empates + margen de gol
src/bayes.py          # Beta-Bernoulli + métricas de calibración
src/fifa_seed.py      # FIFA → Elo inicial
src/scraper.py        # ESPN vía Playwright / requests + normalización de nombres/fases
src/qatar_fixture.py  # resultados reales Qatar 2022 (offline / fallback)
src/pipeline.py       # orquestador Elo+Bayes + snapshots + match_log pre-partido
src/models.py         # modelos SQLModel: Team, Tournament, Match, RatingSnapshot
src/db.py             # engine SQLite, init_db, sesiones
src/ingest.py         # pegamento scraper ↔ DB ↔ pipeline (DB = fuente de verdad)
src/betting.py        # motor puro de apuestas (BetParams, simulate, recommend_bet, sweep_strategies)
src/strategies.py     # estrategia activa en la DB (save/load, Strategy<->BetParams)
src/odds.py           # capa de cuotas (OddsQuote, parsers Polymarket/Codere, fetchers)
src/odds_store.py     # persistencia de cuotas en la DB (Odds: histórico, última)
src/dbview.py         # inspección read-only de la DB (table_schema, table_rows)
ui_common.py          # controles de sidebar compartidos entre páginas (session_state)
app.py                # 🏠 Inicio — guía del workflow + tablero de estado
pages/1_🔴_Mundial_en_vivo.py     # scrape ESPN → DB (calendario) + recomendaciones
pages/2_🧪_Qatar_2022.py          # laboratorio: monitor Elo/Bayes + backtest + fijar
pages/3_🗄️_Datos.py               # explorador de datos (head + esquema por tabla)
data/worldcup.db      # SQLite (runtime, gitignored) — finalizados + calendario
tests/                # test_pipeline, test_models, test_ingest, test_betting, test_dbview
```

## Páginas — el workflow en 4 etapas

Al correr `uv run streamlit run app.py`, la barra lateral muestra las páginas. No
es "una app con páginas", sino un **flujo Laboratorio → Producción**: entrenas y
fijas una estrategia con Qatar 2022 y la página en vivo la usa para 2026. Los
parámetros (K, prior, cuota, criterio, umbral…) se **comparten entre páginas** vía
`session_state` (helpers en `ui_common.py`).

- **🏠 Inicio (app.py):** guía del workflow + **tablero de estado** (¿hay calendario
  2026?, ¿estrategia fijada?, ¿cuotas <24h?) con enlaces a cada página. No entrena
  ni apuesta; sin red.
- **🧪 Qatar 2022 (laboratorio):** una sola página, paso a paso:
  1. configuras el sidebar (modelo: K/prior/margen · apuesta: bankroll/cuota/criterio/
     umbral/jornada/sizing/filtro),
  2. **monitor del modelo** Elo/Bayes (tabla, evolución Elo, Bayes, calibración,
     evolución combinada) — persiste `RatingSnapshot` y permite subir ranking FIFA,
  3. **backtest de apuestas** con esos params (ROI, yield, acierto, drawdown, curva),
  4. **«Guardar configuración actual»** fija exactamente esos params como estrategia
     activa (sidebar y fijar **ligados**). El expander **🔬 Explorar combinaciones**
     barre las 18 variantes y «Aplicar al panel» copia la elegida al sidebar.
- **🔴 Mundial en vivo (producción):** scrapea ESPN y guarda **todo el calendario**
  (finalizados + programados). En **3 tabs**:
  - **📅 Calendario** — partidos por fecha con su estado.
  - **💱 Cuotas** — hub: pega una **URL** (detecta Codere/Polymarket), **"Actualizar
    solo cuotas"** busca al instante; tabla comparativa Codere/Polymarket vs modelo
    2026; **aquí eliges la fuente** que alimenta las recomendaciones.
  - **🎯 Recomendaciones** — lado + stake por partido con la **estrategia activa**
    (toggle "Ignorar estrategia activa") y la **cuota real** de la fuente elegida.
  Necesita red; sin calendario en la DB muestra un aviso.
- **🗄️ Datos:** explorador read-only — por tabla (Teams / Tournaments / Matches /
  RatingSnapshots / Strategies / Odds), un expander con `head()`, nº de filas,
  **última actualización** y esquema, con filtro por torneo.

> ⚠️ Los selectores de Codere y la forma de los mercados de Polymarket son
> *best-effort* — pueden requerir ajuste contra la red real en el primer scrape.
> `parse_polymarket` soporta mercados de 2 outcomes y Yes/No "Will X beat Y"
> emparejados por partido. El scraping de cuotas es para análisis personal, no
> redistribución.

Backtest educativo con cuotas sintéticas fijas, no consejo de apuestas.
