"""
🏠 Inicio — guía del workflow y tablero de estado.

Esta página NO entrena ni apuesta: explica el flujo de la app y muestra en qué
punto del workflow estás (¿hay calendario?, ¿estrategia fijada?, ¿cuotas
frescas?). El trabajo vive en las otras páginas (barra lateral):

    🧪 Qatar 2022      laboratorio: configurar → ver modelo → backtest → FIJAR
    🔴 Mundial en vivo producción: consume la estrategia fijada y recomienda
    🗄️ Datos           inspección read-only de la base de datos

Correr (desde app/):  uv run streamlit run app.py
"""
from __future__ import annotations
from datetime import datetime, timedelta

import streamlit as st
from sqlmodel import Session, select

from src.db import get_engine, init_db
from src.models import Match, Tournament
from src.strategies import load_active_strategy
from src.odds_store import latest_scrape_iso

st.set_page_config(page_title="Inicio — Mundial Elo+Bayes", layout="wide")

# ---- estilo PyPro-ish dark tech ----
st.markdown("""
<style>
  .stApp { background:#0F1117; }
  h1,h2,h3 { color:#22D3EE; }
</style>
""", unsafe_allow_html=True)

st.title("🏠 Mundial 2026 — Elo + Bayes + Apuestas")
st.caption("Monitor Elo/Bayes + motor de apuestas para el Mundial. Esta es la "
           "página de inicio: explica el flujo y te dice en qué paso vas.")


@st.cache_resource
def get_db():
    eng = get_engine()
    init_db(eng)
    return eng


db_engine = get_db()

# ----------------------------------------------------------------------
# El workflow en una frase + diagrama
# ----------------------------------------------------------------------
st.markdown("""
### El workflow, en 4 pasos

La idea no es "una app con páginas", sino **un flujo Laboratorio → Producción**:
entrenas y eliges una estrategia con datos pasados (Qatar 2022), la **fijas**, y
la página en vivo la usa para recomendar apuestas en el Mundial 2026.
""")

st.code("""🧪 Qatar 2022  →  configurar K/prior/apuesta · ver el modelo Elo/Bayes ·
   (laboratorio)    correr el backtest de apuestas · FIJAR la mejor estrategia
        │
        │  (la estrategia activa se guarda en la DB = puente entre páginas)
        ▼
🔴 Mundial en vivo →  scrapear ESPN (calendario) · traer cuotas reales ·
   (producción)       recomendar lado + stake con ELO·Bayes·Kelly y la cuota elegida
        │
        ▼
🗄️ Datos          →  revisar qué hay en la base (filas, head, última actualización)
""", language="text")

st.info("💾 **La base de datos SQLite es la fuente de verdad.** El scraper la "
        "llena (calendario + resultados), el pipeline Elo/Bayes lee de ella y la "
        "estrategia fijada vive ahí. Por eso las páginas concuerdan entre sí.")

# ----------------------------------------------------------------------
# Tablero de estado: ¿en qué paso del workflow estoy?
# ----------------------------------------------------------------------
st.subheader("📍 ¿Dónde voy en el workflow?")

with Session(db_engine) as s:
    wc = s.exec(select(Tournament).where(Tournament.name == "World Cup 2026")).first()
    n_cal = n_fin = 0
    if wc:
        ms = s.exec(select(Match).where(Match.tournament_id == wc.id)).all()
        n_cal = len(ms)
        n_fin = sum(1 for m in ms if m.finished)
    active = load_active_strategy(s)
    strat = ({f: getattr(active, f) for f in (
        "label", "sizing", "side_criterion", "blend_weight", "use_bayes_filter",
        "bayes_threshold", "start_match_no", "base_fraction", "kelly_fraction",
        "odds", "bankroll0", "backtest_yield")} if active is not None else None)
    poly_iso = latest_scrape_iso(s, wc, "polymarket") if wc else None
    cod_iso = latest_scrape_iso(s, wc, "codere") if wc else None

# ¿Cuotas frescas? (cualquier fuente con fetched_at < 24h)
fresh_iso = max([x for x in (poly_iso, cod_iso) if x], default=None)
cuotas_frescas = False
if fresh_iso:
    try:
        cuotas_frescas = datetime.fromisoformat(fresh_iso) > datetime.now() - timedelta(hours=24)
    except ValueError:
        cuotas_frescas = False


def estado(ok: bool) -> str:
    return "✅" if ok else "⬜"


col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(f"#### {estado(active is not None)} 1 · Estrategia")
    if active is not None:
        yld = (f"{active.backtest_yield*100:.1f}%"
               if active.backtest_yield is not None else "n/d")
        st.markdown(f"Fijada: **{active.label}**  \n"
                    f"sizing `{active.sizing}` · criterio `{active.side_criterion}` "
                    f"· yield Qatar {yld}")
    else:
        st.markdown("Sin estrategia fijada. Ve a **🧪 Qatar 2022**, corre el "
                    "backtest y pulsa *Guardar configuración actual*.")
with col2:
    st.markdown(f"#### {estado(n_cal > 0)} 2 · Calendario 2026")
    if n_cal:
        st.markdown(f"**{n_cal}** partidos en DB  \n"
                    f"({n_fin} finalizados · {n_cal - n_fin} programados)")
    else:
        st.markdown("Sin calendario. Ve a **🔴 Mundial en vivo** y pulsa "
                    "*Actualizar (scrape ESPN)*.")
with col3:
    st.markdown(f"#### {estado(cuotas_frescas)} 3 · Cuotas")
    if fresh_iso:
        edad = "frescas (<24h)" if cuotas_frescas else "viejas (>24h)"
        st.markdown(f"Última: `{fresh_iso}`  \n{edad}")
    else:
        st.markdown("Sin cuotas. En **🔴 Mundial en vivo → 💱 Cuotas** pulsa "
                    "*Actualizar solo cuotas*.")

# ----------------------------------------------------------------------
# Menú: enlaces directos a cada página
# ----------------------------------------------------------------------
st.subheader("🧭 Ir a")
st.page_link("pages/2_🧪_Qatar_2022.py",
             label="🧪 Qatar 2022 — laboratorio: modelo + backtest + fijar estrategia")
st.page_link("pages/1_🔴_Mundial_en_vivo.py",
             label="🔴 Mundial en vivo — calendario, cuotas y recomendaciones 2026")
st.page_link("pages/3_🗄️_Datos.py",
             label="🗄️ Datos — explorar las tablas de la base de datos")

# ----------------------------------------------------------------------
# Los modelos y la estrategia, en fórmulas (Markdown + LaTeX)
# ----------------------------------------------------------------------
st.subheader("📐 Los modelos y la estrategia, en fórmulas")

with st.expander("① Modelo Elo — rating por partido", expanded=False):
    st.markdown("**Semilla FIFA → Elo.** El ranking FIFA se re-centra a la escala "
                "Elo clásica (media ~1500):")
    st.latex(r"R_0 = 1500 + (\text{pts}_{\text{FIFA}} - \overline{\text{pts}}) \cdot 0.9")
    st.markdown("**Probabilidad esperada** (sigmoide logística) de que el equipo "
                "$A$ gane al $B$:")
    st.latex(r"E_A = \frac{1}{1 + 10^{\,(R_B - R_A)/400}}")
    st.markdown("**Actualización** tras el partido, con score "
                r"$S \in \{1,\ 0.5,\ 0\}$ (victoria / empate / derrota):")
    st.latex(r"R_A' = R_A + K_{\text{eff}}\,(S_A - E_A)")
    st.markdown("**Multiplicador por margen de gol** (amplifica $K$ en goleadas, "
                r"corrigiendo por diferencia de rating; $=1$ si hay empate):")
    st.latex(r"K_{\text{eff}} = K \cdot \ln\!\big(|\Delta g| + 1\big)\cdot "
             r"\frac{2.2}{\,0.001\,|R_A - R_B| + 2.2\,}")

with st.expander("② Modelo Bayes — fuerza latente (Beta-Bernoulli)", expanded=False):
    st.markdown(r"Cada equipo tiene una fuerza latente $\theta \sim "
                r"\mathrm{Beta}(a,b)$. **Prior anclado al Elo** (fuerza del prior "
                r"$s$ = tamaño de muestra equivalente):")
    st.latex(r"p = \frac{1}{1 + 10^{\,(\overline{R} - R)/400}}, \qquad "
             r"a_0 = p\,s, \qquad b_0 = (1-p)\,s")
    st.markdown(r"Cada partido es un ensayo Bernoulli (**empate $= 0.5$ éxito**). "
                r"**Posterior conjugado** tras observar los resultados:")
    st.latex(r"\theta \mid \text{datos} \sim \mathrm{Beta}\!\left(a_0 + \sum_i S_i,\ "
             r"\; b_0 + \sum_i (1 - S_i)\right)")
    st.markdown("**Media** e **intervalo de credibilidad** (aproximación normal, "
                "sin scipy):")
    st.latex(r"\hat{\theta} = \frac{a}{a+b}, \qquad "
             r"\mathrm{Var} = \frac{a\,b}{(a+b)^2\,(a+b+1)}, \qquad "
             r"\hat{\theta} \pm z_{0.975}\,\sqrt{\mathrm{Var}}")
    st.markdown("**Calibración** de las probabilidades que emite el Elo "
                "($p_i$ predicha, $o_i$ resultado):")
    st.latex(r"\text{Brier} = \frac{1}{N}\sum_i (p_i - o_i)^2, \qquad "
             r"\text{LogLoss} = -\frac{1}{N}\sum_i \big[o_i \ln p_i + "
             r"(1-o_i)\ln(1-p_i)\big]")

with st.expander("③ Estrategia de apuesta (la activa)", expanded=True):
    st.markdown("Para cada partido programado: **elegir lado → filtrar → "
                "dimensionar el stake**. Con bankroll $B$ y cuota decimal $c$:")
    st.markdown("**1) Lado** según el criterio (Elo, Bayes o mezcla con peso $w$):")
    st.latex(r"\text{score}_{\text{equipo}} = w\,E + (1-w)\,\hat{\theta}\quad"
             r"\text{(Elo: } w{=}1;\ \text{Bayes: } w{=}0\text{)}")
    st.markdown(r"**2) Filtro Bayes** (opcional): apostar solo si "
                r"$\hat{\theta}_{\text{lado}} \ge \tau$. **Arranque:** saltar hasta "
                r"la jornada $m_0$.")
    st.markdown("**3) Tamaño de apuesta** (*sizing*), con $b = c - 1$ y "
                "$p$ = prob. del lado:")
    st.latex(r"\text{stake} = \begin{cases}"
             r"f \cdot B & \text{(flat)}\\[4pt]"
             r"f \cdot B \cdot \mathrm{clip}\big(2(p-0.5),\,0,\,1\big) & \text{(confianza)}\\[4pt]"
             r"\max\!\left(0,\ \dfrac{b\,p - (1-p)}{b}\right)\cdot \lambda \cdot B & \text{(Kelly)}"
             r"\end{cases}")
    st.markdown("**4) Liquidación:** si gana, "
                r"$B \mathrel{+}= \text{stake}\,(c-1)$; si no, "
                r"$B \mathrel{-}= \text{stake}$.")

    if strat is not None:
        yld = (f"{strat['backtest_yield']*100:.1f}\\%"
               if strat["backtest_yield"] is not None else r"\text{n/d}")
        w = strat["blend_weight"]
        crit = {"elo": "w = 1\\ (\\text{Elo})", "bayes": "w = 0\\ (\\text{Bayes})",
                "blend": f"w = {w:.2f}\\ (\\text{{mezcla}})"}[strat["side_criterion"]]
        sizing_tex = {
            "flat": rf"f = {strat['base_fraction']:.2f}",
            "confidence": rf"f = {strat['base_fraction']:.2f}",
            "kelly": rf"\lambda = {strat['kelly_fraction']:.2f}",
        }[strat["sizing"]]
        filtro = (rf"\tau = {strat['bayes_threshold']:.2f}"
                  if strat["use_bayes_filter"] else r"\text{sin filtro}")
        st.markdown(f"**Estrategia activa fijada: _{strat['label']}_** "
                    "(sus parámetros en las fórmulas de arriba):")
        st.latex(
            rf"\text{{sizing}}={strat['sizing']},\quad {sizing_tex},\quad {crit},"
            rf"\quad {filtro},\quad m_0={strat['start_match_no']},"
            rf"\quad B_0={strat['bankroll0']:.0f},\quad c={strat['odds']:.2f}")
        st.caption(f"Yield en el backtest de Qatar: {strat['backtest_yield']*100:.1f}%"
                   if strat["backtest_yield"] is not None else "Yield Qatar: n/d.")
    else:
        st.info("No hay estrategia activa fijada todavía. Ve a **🧪 Qatar 2022**, "
                "configura el panel, corre el backtest y pulsa *Guardar "
                "configuración actual* para fijarla.")

st.caption("Backtest educativo, **no** consejo de apuestas.")
