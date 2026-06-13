# ⚽ World Cup 2026 — Betting Strategy Lab

> Monitor de fuerza de selecciones (**Elo + Bayes + TrueSkill**) y laboratorio de
> estrategias de apuesta para el Mundial 2026, con cuotas reales de Polymarket y
> Codere, todo en una app de Streamlit.

<p>
<img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
<img alt="Streamlit" src="https://img.shields.io/badge/UI-Streamlit-FF4B4B?logo=streamlit&logoColor=white">
<img alt="uv" src="https://img.shields.io/badge/env-uv-DE5FE9">
<img alt="tests" src="https://img.shields.io/badge/tests-72%20passing-2ea44f">
<img alt="status" src="https://img.shields.io/badge/uso-educativo-blue">
</p>

Tres modelos estiman la fuerza de cada selección partido a partido; el sistema
**calibra** sus probabilidades contra resultados reales y **simula estrategias de
apuesta** sobre Qatar 2022 para elegir la mejor y aplicarla en vivo al Mundial 2026.

> ⚠️ **Proyecto educativo de modelado, no es consejo de apuestas.** El scraping de
> cuotas es para análisis personal, no para redistribución.

---

## 🧭 El workflow en 4 pasos

No es "una app con páginas", es un **flujo Laboratorio → Producción**:

```
🏠 Inicio            Explica todo y muestra en qué paso vas (estrategia / calendario / cuotas)
        │
        ▼
🧪 Qatar 2022        LAB: configuras → ves los 3 modelos → backtest de apuestas → FIJAS la mejor estrategia
        │  (la estrategia activa se guarda en la DB = puente entre páginas)
        ▼
🔴 Mundial en vivo   PRODUCCIÓN: scrapea ESPN + cuotas reales → recomienda lado + stake con la estrategia fijada
        │
        ▼
🗄️ Datos             Inspecciona la base de datos (head, nº de filas, última actualización)
```

## 🚀 Arranque rápido

Requiere **Python 3.11+** y **[uv](https://docs.astral.sh/uv/)**. Todo desde `app/`:

```bash
cd app
uv sync                              # crea el entorno e instala dependencias
uv run streamlit run app.py          # abre la app en el navegador
uv run playwright install chromium   # solo para scrapear ESPN/Codere "en vivo"
uv run pytest -q                      # tests (sin red)
```

La base SQLite (`app/data/worldcup.db`) es la **fuente de verdad** y se crea sola
en el primer arranque.

## 🧠 Los modelos

| Modelo | Qué hace | Detalle |
|--------|----------|---------|
| **Elo** | Rating clásico ajustado por partido (empate = ½, multiplicador por margen de gol) | `R' = R + K·(S − E)` |
| **Bayes** | Fuerza latente `θ ~ Beta(a,b)` con prior anclado al Elo → media + intervalo de credibilidad | Beta-Bernoulli conjugado |
| **TrueSkill** | Habilidad bayesiana `N(μ,σ²)` ([trueskill.org](https://trueskill.org)); empate nativo, rating conservador μ−3σ | alternativa a Elo |

Las probabilidades del modelo se validan con **Brier**, **LogLoss** y curva de
fiabilidad (calibración). La página de Inicio incluye las fórmulas en LaTeX.

## 💰 Estrategia de apuesta

La meta-estrategia es **configurable**: el *criterio* elige el lado
(Elo / Bayes / mezcla / TrueSkill), un *filtro* Bayes opcional descarta apuestas
flojas, y el *sizing* dimensiona el stake (**Flat / Confianza / Kelly**). El
laboratorio **barre 24 combinaciones** sobre Qatar 2022, las rankea por *yield* y
deja fijar la ganadora; la página en vivo la usa con la **cuota real** elegida.

## 📈 Cuotas reales

- **Polymarket** — vía Gamma API por *tag* (`102232` = Mundial 2026), paginando los
  eventos "X vs. Y" y sus mercados Yes/No.
- **Codere** — scraping del cupón del Mundial 2026 con Playwright.
- **Comparación** — cobertura, divergencia, **margen (overround) por casa**, quién
  da la mejor cuota y un scatter de acuerdo. Los nombres de todas las fuentes se
  **homologan** al canónico del calendario.

## 🧪 Tests

```bash
cd app && uv run pytest -q       # 72 tests, sin red
```

La capa de modelos/apuestas/cuotas es **pura y testeada**; el scraping se inyecta
o se parsea desde payloads guardados.

## 📂 Estructura

Código y documentación viven en [`app/`](app/) — ver el
[README técnico](app/README.md) para el detalle de cada módulo. Diseños y planes en
[`docs/superpowers/`](docs/superpowers/).

---

*Hecho para aprender de modelado deportivo y calibración de probabilidades.* ⚽📊
