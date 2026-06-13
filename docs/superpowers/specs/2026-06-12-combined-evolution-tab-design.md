# Diseño — Tab "Evolución combinada" (Elo + Bayes, doble eje Y)

**Fecha:** 2026-06-12
**Estado:** Aprobado

## Objetivo

Añadir un tab al monitor Streamlit que grafique, para una o varias selecciones,
la evolución temporal de **Elo** (eje Y izquierdo, ~1500) y **probabilidad
bayesiana** (eje Y derecho, 0–1) sobre un eje X = número de partido jugado por
cada equipo.

## Decisiones

| Tema | Decisión |
|------|----------|
| Selección | `st.multiselect`, default top 3 por Elo |
| Eje X | Partido jugado por el equipo (índice 1,2,3… propio de cada equipo) |
| Doble eje | Altair `layer(...).resolve_scale(y='independent')` |
| Estilo | Elo línea sólida (izq); Bayes línea punteada (der); color por equipo |
| Dependencias | Ninguna nueva — Altair viene con Streamlit |

## Capa de datos (testeable)

Método puro nuevo en `src/pipeline.py`:

```python
def team_evolution(self) -> list[dict]:
    """Filas {team, match_no, elo, bayes} por partido jugado por cada equipo."""
```

Recorre `self.elo.history` y `self.snapshots` (parejos por índice: uno por
partido procesado). Para cada partido, por sus dos equipos, emite una fila con
`match_no` incremental propio del equipo, el Elo tras el partido
(`snapshots[i]["elo"][team]`) y la media bayesiana (`snapshots[i]["bayes"][team]`).

## UI (`app.py`)

- Nuevo tab `📉 Evolución combinada` (5º).
- `equipos = st.multiselect(...)` default top 3 del leaderboard.
- DataFrame desde `pipe.team_evolution()` filtrado por equipos.
- Altair:
  - `elo_line = mark_line(point=True)` → `y=Elo` (`scale zero=False`), color por equipo.
  - `bayes_line = mark_line(strokeDash=[4,4], point=True)` → `y=Bayes` (`domain=[0,1]`), color por equipo.
  - `alt.layer(elo_line, bayes_line).resolve_scale(y="independent")`.
- `st.caption`: línea sólida = Elo (izq), punteada = Bayes (der).

## Tests

`tests/test_pipeline.py`: `team_evolution()` produce, para Argentina sobre
`QATAR_2022_SAMPLE`, `match_no` consecutivo 1..N; todos los `elo` en rango
plausible y `bayes` en [0,1].

## Fuera de alcance

- No se toca Elo/Bayes ni la DB.
- No se persiste el gráfico; se recalcula desde el pipeline en memoria.
