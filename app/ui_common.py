"""
Controles de barra lateral compartidos por las páginas (Backtest, En vivo,
Simulador). Como st.session_state es compartido entre páginas, usar el mismo
`key` en cada widget mantiene los parámetros CONCORDANTES al navegar.
"""
from __future__ import annotations
import streamlit as st


def model_controls() -> tuple[float, float, bool]:
    """Sidebar 'Modelo': K, fuerza del prior Bayes, multiplicador por margen."""
    st.sidebar.header("Modelo")
    k = st.sidebar.slider("Factor K (Elo)", 10, 80, 40, 5, key="k_factor")
    prior = st.sidebar.slider("Fuerza del prior Bayes", 1.0, 12.0, 4.0, 1.0,
                              key="prior_strength")
    margin = st.sidebar.checkbox("Multiplicador por margen de gol", value=True,
                                 key="use_margin")
    return float(k), float(prior), bool(margin)


def fifa_ranking() -> dict[str, float]:
    """Sidebar 'Ranking FIFA': snapshot incluido o JSON subido {equipo: puntos}."""
    import json
    from src.fifa_seed import FIFA_SNAPSHOT_EXAMPLE
    st.sidebar.header("Ranking FIFA")
    fuente = st.sidebar.radio("Origen", ["Snapshot incluido", "Subir JSON"],
                              key="fifa_source")
    if fuente == "Subir JSON":
        up = st.sidebar.file_uploader("JSON {equipo: puntos}", type="json",
                                      key="fifa_json")
        if up is not None:
            try:
                return {k: float(v) for k, v in json.load(up).items()}
            except (ValueError, TypeError):
                st.sidebar.error("JSON inválido; usando el snapshot incluido.")
    return dict(FIFA_SNAPSHOT_EXAMPLE)


def betting_controls() -> dict:
    """Sidebar 'Apuestas': params compartidos (sin 'sizing' ni filtro Bayes).
    Devuelve un dict listo para BetParams(**common, sizing=..., use_bayes_filter=...)."""
    st.sidebar.header("Apuestas")
    bankroll0 = st.sidebar.number_input("Bankroll inicial", 100.0, 1_000_000.0,
                                        1000.0, 100.0, key="bankroll0")
    odds = st.sidebar.number_input("Cuota decimal fija", 1.01, 10.0, 2.0, 0.05,
                                   key="odds")
    start_match_no = st.sidebar.slider("Apostar desde la jornada", 1, 5, 2,
                                       key="start_match_no")
    base_fraction = st.sidebar.slider("Fracción base del bankroll", 0.01, 0.50,
                                      0.05, 0.01, key="base_fraction")
    kelly_fraction = st.sidebar.slider("Fracción de Kelly", 0.05, 1.0, 0.25, 0.05,
                                       key="kelly_fraction")
    side_criterion = st.sidebar.selectbox(
        "Criterio para elegir el lado", ["elo", "bayes", "blend"],
        format_func={"elo": "Elo (favorito)", "bayes": "Mayor media Bayes",
                     "blend": "Mezcla Elo/Bayes"}.get, key="side_criterion")
    blend_weight = st.sidebar.slider("Peso de Elo en la mezcla (blend)", 0.0, 1.0,
                                     0.5, 0.05, key="blend_weight")
    bayes_threshold = st.sidebar.slider("Umbral de Bayes (filtro)", 0.30, 0.80,
                                        0.50, 0.01, key="bayes_threshold")
    return dict(bankroll0=float(bankroll0), odds=float(odds),
                start_match_no=int(start_match_no),
                base_fraction=float(base_fraction),
                kelly_fraction=float(kelly_fraction),
                side_criterion=side_criterion, blend_weight=float(blend_weight),
                bayes_threshold=float(bayes_threshold))
