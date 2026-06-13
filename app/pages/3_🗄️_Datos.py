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

TABLES = [("Teams", Team), ("Tournaments", Tournament),
          ("Matches", Match), ("RatingSnapshots", RatingSnapshot),
          ("Strategies", Strategy), ("Odds", Odds)]

for tab, (label, model) in zip(st.tabs([t[0] for t in TABLES]), TABLES):
    with tab:
        with Session(db_engine) as s:
            rows = table_rows(s, model, tournament_id=tournament_id)
        st.metric(f"Filas en {model.__tablename__}", len(rows))

        st.markdown("**Esquema del modelo**")
        st.dataframe(pd.DataFrame(table_schema(model)),
                     use_container_width=True, hide_index=True)

        st.markdown("**Datos**")
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, height=460)
        else:
            st.info("Sin filas para el filtro actual.")
