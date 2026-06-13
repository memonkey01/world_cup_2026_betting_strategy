# Diseño — Explorador de datos (validar modelos)

**Fecha:** 2026-06-13
**Estado:** Aprobado

## Objetivo

Página nueva read-only para navegar las tablas de la DB y validar los modelos:
por tabla muestra nº de filas, esquema (columnas/tipos/nullable/PK) y los datos,
con filtro por torneo.

## Decisiones

| Tema | Decisión |
|------|----------|
| Ubicación | Página nueva `pages/3_🗄️_Datos.py` con una pestaña por tabla |
| Contenido | Por tabla: nº de filas + esquema + datos (dataframe); read-only |
| Filtro | Por torneo (aplica a Match y RatingSnapshot; Team/Tournament son globales) |

## Helpers puros (testeables) — `src/dbview.py`

```python
def table_schema(model) -> list[dict]:
    """Introspección de model.__table__.columns -> {columna, tipo, nullable, pk}."""

def table_rows(session, model, tournament_id=None) -> list[dict]:
    """Filas como dicts (model_dump()). Filtra por tournament_id solo si el
    modelo tiene esa columna y se pasa un valor."""
```

## Página `pages/3_🗄️_Datos.py`

- Selector de torneo (de la tabla Tournament) con opción "Todos".
- 4 pestañas: Teams · Tournaments · Matches · RatingSnapshots.
- Cada pestaña: `st.metric` con nº de filas, dataframe del esquema, dataframe de
  los datos. El filtro de torneo aplica a Matches y RatingSnapshots.

## Tests — `tests/test_dbview.py`

- `table_schema(Match)`: incluye `id` (pk), `home_goals` (nullable), `espn_event_id`.
- `table_rows`: cuenta Teams; filtra Match por `tournament_id` (Team no se filtra).

## Fuera de alcance

- Edición de datos (read-only) y caja de SQL libre (descartada).
