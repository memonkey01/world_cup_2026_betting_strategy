"""
Capa de base de datos: engine SQLite, creación de tablas y sesiones.

Para tests usar get_engine(":memory:") -> StaticPool mantiene una sola
conexión, así la DB en memoria sobrevive entre sesiones del mismo engine.
"""
from __future__ import annotations
from pathlib import Path
from contextlib import contextmanager

from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

from . import models  # noqa: F401  registra las tablas en SQLModel.metadata

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "worldcup.db"


def get_engine(path: str | Path = DEFAULT_DB_PATH, echo: bool = False):
    if str(path) == ":memory:":
        return create_engine(
            "sqlite://", echo=echo,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{path}", echo=echo,
        connect_args={"check_same_thread": False},
    )


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope(engine):
    with Session(engine) as session:
        yield session
