# CLAUDE.md

Monitor **Elo + Bayes** para el Mundial de fútbol, con scraping de resultados
desde ESPN y dashboard en Streamlit. Predice/valida la fuerza de las selecciones
y calibra las probabilidades del modelo contra resultados reales.

Todo el código vive en [app/](app/). Comentarios, docstrings y README están en español.

## Qué hace

1. **Semilla FIFA → Elo.** El ranking FIFA (tipo-Elo desde 2018) se re-centra a
   la escala Elo clásica (~1500 media). Ver [app/fifa_seed.py](app/fifa_seed.py).
2. **Elo por rondas.** `R' = R + K·(S − E)` con empates estilo ajedrez
   (`S ∈ {1, 0.5, 0}`) y multiplicador opcional por margen de gol.
   Ver [app/elo.py](app/elo.py).
3. **Bayes binario (Beta-Bernoulli).** Cada equipo tiene `θ ~ Beta(a,b)` con
   prior anclado al Elo; cada partido es un Bernoulli (empate = 0.5 éxito);
   posterior conjugado → media + intervalo de credibilidad.
   Ver [app/bayes.py](app/bayes.py).
4. **Calibración.** Las probabilidades que el Elo emite *antes* de cada partido
   se contrastan contra resultados con Brier, LogLoss y curva de fiabilidad
   (también en [app/bayes.py](app/bayes.py)).

## Arquitectura

| Archivo | Rol |
|---------|-----|
| [app/elo.py](app/elo.py) | `EloSystem` + `expected_score`, `match_scores`, `margin_multiplier` |
| [app/bayes.py](app/bayes.py) | `BetaBelief`, `BayesianLeague` + métricas `brier_score`, `log_loss`, `reliability_bins` |
| [app/fifa_seed.py](app/fifa_seed.py) | `fifa_to_elo`, `load_fifa_ranking`, `FIFA_SNAPSHOT_EXAMPLE` |
| [app/scraper.py](app/scraper.py) | ESPN scoreboard API vía Playwright; `fetch_via_requests` como fallback |
| [app/qatar_fixture.py](app/qatar_fixture.py) | `QATAR_2022_SAMPLE` — resultados reales para backtest offline |
| [app/pipeline.py](app/pipeline.py) | `Pipeline` — orquesta seed → Elo + Bayes por jornada, snapshots y calibración |
| [app/app.py](app/app.py) | Dashboard Streamlit (KPIs, tabla, evolución Elo, Bayes, calibración) |
| [app/test_pipeline.py](app/test_pipeline.py) | Tests del pipeline |

Flujo: `Pipeline.seed(fifa_points)` → `process_all(matches)` donde cada `match`
es la tupla `(date, stage, home, away, home_goals, away_goals)`. Elo y Bayes se
actualizan en paralelo; antes de cada partido se guarda `P(A gana)` para calibrar.

## Modos del dashboard

- **Backtest Qatar 2022:** offline, usa `QATAR_2022_SAMPLE` (sin red).
- **En vivo 2026:** scrapea `fifa.world` de ESPN por rango de fechas
  (`YYYYMMDD-YYYYMMDD`) y procesa solo partidos finalizados. Botón
  «Actualizar jornada» al cerrar cada fecha.

Endpoint ESPN (sin API key):
`https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=YYYYMMDD-YYYYMMDD`

## Comandos

```bash
cd app
uv venv && source .venv/bin/activate   # PowerShell: .venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
playwright install chromium            # solo para modo "En vivo 2026"
streamlit run app.py
python -m pytest -q                    # tests
```

## ⚠️ Gotcha: layout vs. imports

El código está escrito como **paquete `src`** pero en disco está **plano en `app/`**:

- `app.py` y `test_pipeline.py` hacen `from src.elo import …`
- `pipeline.py` hace imports relativos `from .elo import …`
- El README describe una carpeta `src/` y `tests/` que **no existen** en disco.

Por eso, tal cual, `streamlit run app.py` y `pytest` **fallan con `ModuleNotFoundError`**.
Para que corra hay dos opciones (elegir una y ser consistente):

1. **Reorganizar** moviendo `elo.py, bayes.py, fifa_seed.py, scraper.py,
   qatar_fixture.py, pipeline.py` a `app/src/` y `test_pipeline.py` a `app/tests/`
   (es lo que el README ya documenta), o
2. **Aplanar los imports** quitando el prefijo `src.` y volviendo absolutos los
   relativos de `pipeline.py` (`from .elo` → `from elo`).

La opción 1 alinea código, README y `app.py` sin tocar lógica — preferirla.

## Convenciones

- Python con `from __future__ import annotations` y `@dataclass` en todos los modelos.
- Sin scipy: el intervalo de credibilidad Beta usa aproximación normal con
  `statistics.NormalDist` ([app/bayes.py](app/bayes.py)).
- Marcadores Elo en **tiempo reglamentario** — los penales no cuentan.
- Empate = 0.5 tanto en Elo como en Bayes.

## Limitación conocida (siguiente iteración)

El Bayes binario trata partidos como ensayos independientes y **no usa la fuerza
del rival ni los goles**. Para mejorar predicción: Bradley-Terry (fuerza relativa)
o Poisson/Dixon-Coles (goles), reusando el mismo scraping y la misma capa de
calibración.
