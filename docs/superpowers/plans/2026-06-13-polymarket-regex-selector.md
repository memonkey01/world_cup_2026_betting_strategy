# Optimización Polymarket: regex + selector manual — Plan

> Ejecutar inline. Verificación: `uv run pytest -q` (capa pura) + `py_compile`
> (UI). Decisiones: selector = preview + checkboxes (sin mapeo manual de
> nombres); regex es un filtro client-side **aparte** del query `search`.

**Goal:** Dar control sobre qué mercados de Polymarket se ingestan: filtro regex
sobre el payload crudo + tabla de preview donde el usuario marca cuáles guardar.

**Estado actual:** `fetch_polymarket` confía en `search` (server-side, caja
negra); `parse_polymarket` parsea todo y se ingesta de golpe sin visibilidad.

---

### Task 1: Capa pura — `select_markets` + tests

**Files:** Modify `app/src/odds.py`, `app/tests/test_odds.py`.

- [ ] En `odds.py`, añadir:
```python
def select_markets(payload: list, pattern: str | None = None) -> list:
    """Filtra mercados crudos de Gamma por regex (case-insensitive) sobre
    question/slug/title. pattern vacío => todos. Regex inválida => todos."""
    if not pattern:
        return list(payload)
    try:
        rx = re.compile(pattern, re.I)
    except re.error:
        return list(payload)
    out = []
    for mkt in payload:
        text = " ".join(str(mkt.get(k, "")) for k in ("question", "slug", "title"))
        if rx.search(text):
            out.append(mkt)
    return out
```
- [ ] Test en `test_odds.py`:
```python
def test_select_markets_regex():
    payload = [
        {"question": "Argentina vs France"},
        {"question": "Will Brazil win the World Cup?"},
        {"slug": "mexico-vs-canada-2026"},
    ]
    assert len(select_markets(payload, None)) == 3          # sin patrón -> todos
    assert len(select_markets(payload, "")) == 3
    out = select_markets(payload, r"argentina|mexico")
    assert len(out) == 2                                    # casa question y slug
    assert select_markets(payload, "[bad(") == payload      # regex inválida -> todos
```
- [ ] Import `select_markets` en el test (from src.odds).
- [ ] `cd app && uv run pytest -q` → 56 passed.
- [ ] Commit: `feat(odds): select_markets — filtro regex client-side de mercados Polymarket`.

### Task 2: UI tab Cuotas — regex + preview con checkboxes

**Files:** Modify `app/pages/1_🔴_Mundial_en_vivo.py`.

- [ ] Imports: añadir `select_markets, OddsQuote` a `from src.odds import (...)`.
- [ ] Reescribir el bloque Polymarket de la tab Cuotas:
  - Mantener `poly_query` (va al `search`). Añadir `poly_regex =
    st.text_input("Filtro regex (opcional)")`.
  - Botón **"🔎 Buscar mercados Polymarket"**:
    `raw = fetch_polymarket(poly_query)` → `sel = select_markets(raw, poly_regex)`
    → `quotes = parse_polymarket(sel, now_iso)`. Guardar en
    `st.session_state["poly_preview"]` (lista de dicts con los 9 campos de
    OddsQuote) y `st.session_state["poly_fetched_at"]`.
  - Si hay preview: construir DataFrame con `guardar` (default = casa con
    calendario), `partido`, `cuota home`, `cuota away`, `P(home)`,
    `✅ calendario`. `st.data_editor(..., column_order=[...], disabled=[todas
    menos "guardar"])`.
  - Botón **"💾 Guardar cuotas seleccionadas"**: `chosen = [preview[i] for i,v
    in enumerate(edited["guardar"]) if v]` → reconstruir `OddsQuote(**d)` →
    `ingest_odds(s, wc, quotes)`. Mostrar nº guardadas.
  - Codere: botón aparte "Actualizar Codere (de la URL)" visible si
    `src == "codere"`.
- [ ] El resto (tabla comparativa, selector de fuente) sin cambios.
- [ ] `py_compile` OK.
- [ ] Commit: `feat(ui): Polymarket con filtro regex y selector manual (preview + guardar)`.

### Task 3: Docs + tests

**Files:** Modify `CLAUDE.md`, `app/README.md`.

- [ ] Documentar `select_markets` y el flujo de 2 pasos (buscar → marcar →
  guardar) en la tab Cuotas.
- [ ] `uv run pytest -q` verde.
- [ ] Commit: `docs: Polymarket regex + selector manual en la tab Cuotas`.
