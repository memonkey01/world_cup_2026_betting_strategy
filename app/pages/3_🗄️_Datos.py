"""
Explorador de datos: navega las tablas de la DB para validar los modelos.

Read-only. Por tabla muestra el nº de filas, el esquema (columnas/tipos/nullable/PK)
y los datos, con filtro por torneo (aplica a Match y RatingSnapshot).
"""
from __future__ import annotations
import pandas as pd
import streamlit as st
from sqlmodel import Session

from src.db import get_engine, init_db
from src.models import Team, Tournament, Match, RatingSnapshot, Strategy, Odds
from src.dbview import table_schema, table_rows

st.set_page_config(page_title="Datos — Explorador", layout="wide")
st.title("🗄️ Datos — Explorador de modelos")
st.caption("Vista read-only de TODAS las tablas de la base de datos para validar "
           "los modelos: esquema (columnas/tipos/nullable/PK) y filas. El filtro "
           "por torneo aplica a las tablas que tienen `tournament_id` "
           "(Match, RatingSnapshot, Odds); Team, Tournament y Strategy son globales.")


@st.cache_resource
def get_db():
    eng = get_engine()
    init_db(eng)
    return eng


db_engine = get_db()

# Filtro por torneo (aplica a Match y RatingSnapshot).
with Session(db_engine) as s:
    tournaments = table_rows(s, Tournament)

opciones = {"Todos": None}
opciones.update({f'{t["name"]} ({t["year"]})': t["id"] for t in tournaments})
sel = st.selectbox("Filtrar por torneo (Match y RatingSnapshot)", list(opciones))
tournament_id = opciones[sel]

# Por tabla, la columna que mejor indica "última actualización" (mayor = más nuevo).
FRESHNESS_COL = {"odds": "fetched_at", "match": "date", "ratingsnapshot": "step"}
PREVIEW_N = 10


def last_update(model, rows: list[dict]) -> str | None:
    """Valor máximo de la columna de frescura del modelo, si existe."""
    col = FRESHNESS_COL.get(model.__tablename__)
    if not col or not rows:
        return None
    vals = [r.get(col) for r in rows if r.get(col) is not None]
    return str(max(vals)) if vals else None


TABLES = [("Teams", Team), ("Tournaments", Tournament),
          ("Matches", Match), ("RatingSnapshots", RatingSnapshot),
          ("Strategies", Strategy), ("Odds", Odds)]

st.caption(f"Cada tabla se abre en un expander con una vista previa "
           f"(`head({PREVIEW_N})`), el nº de filas, la última actualización "
           "y el esquema. Útil para confirmar de un vistazo si la DB ya se llenó.")

for label, model in TABLES:
    with Session(db_engine) as s:
        rows = table_rows(s, model, tournament_id=tournament_id)
    upd = last_update(model, rows)
    title = f"{label} — {len(rows)} filas"
    if upd:
        title += f" · últ. {upd}"
    with st.expander(title, expanded=(label == "Matches")):
        c1, c2 = st.columns(2)
        c1.metric(f"Filas en {model.__tablename__}", len(rows))
        c2.metric("Última actualización", upd or "—")

        if rows:
            df = pd.DataFrame(rows)
            st.markdown(f"**Vista previa** (head {PREVIEW_N} de {len(df)})")
            st.dataframe(df.head(PREVIEW_N), use_container_width=True)
        else:
            st.info("Sin filas para el filtro actual.")

        st.markdown("**Esquema del modelo**")
        st.dataframe(pd.DataFrame(table_schema(model)),
                     use_container_width=True, hide_index=True)
