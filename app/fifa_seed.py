"""
Semilla del sistema: convierte puntos del ranking FIFA a ratings Elo iniciales.

El ranking FIFA usa un sistema tipo-Elo desde 2018 (SUM method), asi que los
puntos ya viven en una escala compatible. El truco es re-centrar para que
queden en el rango Elo familiar (~1500 promedio, top ~2100).

Mapeo lineal calibrado:
  elo = 1500 + (fifa_points - media_fifa) * escala

Con escala ~0.9 los top quedan ~2050-2100 y los debiles ~1300, que es
el rango realista observado en datasets de Elo de seleciones (eloratings.net).
"""

from __future__ import annotations
import json
from pathlib import Path


def fifa_to_elo(fifa_points: dict[str, float], anchor_mean: float = 1500.0,
                scale: float = 0.9) -> dict[str, float]:
    if not fifa_points:
        return {}
    mean_pts = sum(fifa_points.values()) / len(fifa_points)
    return {team: anchor_mean + (pts - mean_pts) * scale
            for team, pts in fifa_points.items()}


def load_fifa_ranking(path: str | Path) -> dict[str, float]:
    """Carga JSON {equipo: puntos_fifa}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: float(v) for k, v in data.items()}


# Snapshot de puntos FIFA (ejemplo representativo, ajustable).
# Reemplazar con el ranking oficial vigente al inicio del Mundial.
FIFA_SNAPSHOT_EXAMPLE = {
    "Argentina": 1886.0, "France": 1859.0, "Spain": 1854.0, "England": 1819.0,
    "Brazil": 1776.0, "Portugal": 1779.0, "Netherlands": 1754.0, "Belgium": 1765.0,
    "Italy": 1718.0, "Germany": 1717.0, "Croatia": 1716.0, "Morocco": 1694.0,
    "Colombia": 1696.0, "Mexico": 1653.0, "USA": 1648.0, "Uruguay": 1679.0,
    "Switzerland": 1648.0, "Japan": 1652.0, "Senegal": 1645.0, "Denmark": 1640.0,
    "Iran": 1637.0, "Korea Republic": 1575.0, "Australia": 1538.0, "Ecuador": 1567.0,
    "Austria": 1580.0, "Ukraine": 1573.0, "Sweden": 1556.0, "Poland": 1556.0,
    "Wales": 1545.0, "Serbia": 1538.0, "Egypt": 1518.0, "Nigeria": 1512.0,
    "Canada": 1508.0, "Norway": 1497.0, "Panama": 1393.0, "Saudi Arabia": 1419.0,
    "Qatar": 1400.0, "Costa Rica": 1500.0, "Ghana": 1463.0, "Cameroon": 1475.0,
}
