"""
Inspección read-only de la base de datos para validar los modelos.

Helpers puros (sin Streamlit): el esquema de cada modelo SQLModel y sus filas
como dicts, con filtro opcional por torneo.
"""
from __future__ import annotations

from sqlmodel import Session, select


def table_schema(model) -> list[dict]:
    """Esquema real de la tabla: columna, tipo, nullable, pk."""
    return [{
        "columna": c.name,
        "tipo": str(c.type),
        "nullable": bool(c.nullable),
        "pk": bool(c.primary_key),
    } for c in model.__table__.columns]


def table_rows(session: Session, model, tournament_id: int | None = None) -> list[dict]:
    """Filas de la tabla como dicts. Filtra por tournament_id solo si el modelo
    tiene esa columna y se pasa un valor."""
    stmt = select(model)
    if tournament_id is not None and hasattr(model, "tournament_id"):
        stmt = stmt.where(model.tournament_id == tournament_id)
    return [row.model_dump() for row in session.exec(stmt).all()]
