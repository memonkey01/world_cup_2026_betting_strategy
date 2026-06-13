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
sola. En la barra lateral hay tres páginas (ver «Páginas» abajo): **📊 Backtest**
(la principal, *no necesita red*), **🔴 Mundial en vivo** y **💰 Simulador de
apuestas**.

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
src/betting.py        # motor puro de apuestas (BetParams, simulate, recommend_bet)
ui_common.py          # controles de sidebar compartidos entre páginas (session_state)
app.py                # 📊 Backtest (Qatar) — monitor Elo/Bayes
pages/1_🔴_Mundial_en_vivo.py     # scrape ESPN → DB (calendario) + recomendaciones
pages/2_💰_Simulador_Apuestas.py  # backtest de apuestas (2 estrategias)
data/worldcup.db      # SQLite (runtime, gitignored) — finalizados + calendario
tests/                # test_pipeline.py, test_models.py, test_ingest.py, test_betting.py
```

## Páginas (multipage)

Al correr `uv run streamlit run app.py`, la barra lateral muestra tres páginas.
Los parámetros (K, prior, cuota, criterio, umbral…) se **comparten entre páginas**
vía `session_state` (helpers en `ui_common.py`), así backtest, vivo y simulador
concuerdan.

- **📊 Backtest (app.py):** monitor Elo/Bayes sobre Qatar 2022 — tabla, evolución
  de Elo, distribución bayesiana, calibración y evolución combinada.
- **🔴 Mundial en vivo:** scrapea ESPN, guarda **todo el calendario** (finalizados
  + programados) en la DB, lo muestra como vista tipo calendario y recomienda
  **lado + stake** por partido programado. El sizing se elige con botones
  (Flat / Confianza / Kelly). Necesita red; sin calendario en la DB muestra un aviso.
- **💰 Simulador de apuestas:** backtest al ganador sobre Qatar 2022 con bet sizing
  dinámico y meta-estrategia configurable (criterio de lado Elo / Bayes / mezcla).
  Compara *apostar a todos* vs *solo Bayes > umbral* con KPIs (ROI, yield, drawdown)
  y curvas de bankroll.

Backtest educativo con cuotas sintéticas fijas, no consejo de apuestas.
