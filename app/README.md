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

## Uso

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
playwright install chromium     # solo para modo "En vivo 2026"
streamlit run app.py
```

- **Backtest Qatar 2022:** offline, usa `src/qatar_fixture.py` (resultados reales).
- **En vivo 2026:** scrapea `fifa.world` de ESPN por rango de fechas y procesa
  solo partidos finalizados. Pulsa «Actualizar jornada» al cerrar cada fecha.

Endpoint ESPN (sin API key):
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
src/scraper.py        # ESPN vía Playwright / requests
src/qatar_fixture.py  # resultados reales Qatar 2022 (offline)
src/pipeline.py       # orquestador + snapshots por jornada
app.py                # monitor Streamlit
tests/test_pipeline.py
```
