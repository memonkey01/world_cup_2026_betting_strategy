# TrueSkill como modelo + criterio de apuesta — Plan

> Ejecutar inline. Verificación: `uv run pytest -q` + `py_compile` + validación
> live del pipeline sobre Qatar. Decisiones: seed μ desde FIFA; integración
> completa (3er modelo en el monitor + criterio de lado en el sweep).

**Goal:** Añadir TrueSkill (`trueskill==0.4.5`) como tercer modelo de rating
(junto a Elo/Bayes) y como `side_criterion` alternativo en la estrategia.

**API confirmada:** `TrueSkill(draw_probability)`, `env.rate_1vs1(a,b[,drawn=True])`,
`env.expose(r)=μ−3σ`, `env.cdf`. Prob: `Φ((μa−μb)/√(2β²+σa²+σb²))`.

---

### Task 1: `src/trueskill_model.py` + tests
- `TrueSkillSystem` (dataclass): `draw_probability=0.26`, `elo_per_mu=40.0`,
  `ratings: dict[str,Rating]`, env en `__post_init__`.
  - `seed_from_elo(initial_elo, mean_elo=1500)`: μ = 25 + (elo−1500)/elo_per_mu.
  - `get(team)` (default rating si falta), `expose(team)`,
    `win_probability(a,b)` (receta cdf), `update_match(a,b,hg,ag,...)` (empate
    nativo con `drawn=True`; si hg<ag invierte), `leaderboard()` (por expose).
- Test `tests/test_trueskill.py`: seed ordena μ por Elo; ganar sube μ del ganador
  y baja del perdedor; empate acerca; win_probability del más fuerte > 0.5 y
  simétrica (≈1−inversa); expose = μ−3σ.

### Task 2: Pipeline integra TrueSkill
- Campo `trueskill: TrueSkillSystem = field(default_factory=TrueSkillSystem)`.
- `seed()`: `self.trueskill.seed_from_elo(self.initial_elo)`.
- `process_match`: antes de actualizar, `ts_home = trueskill.win_probability(home,
  away)`, `ts_away = 1-ts_home` → al `match_log`. Después,
  `trueskill.update_match(...)`.
- `prematch_rec`: añade `ts_home`/`ts_away`.
- `combined_leaderboard`: añade `ts_mu`, `ts_sigma` (round 2).
- Test en `test_pipeline.py`: tras procesar, `match_log[i]` trae ts_home/ts_away
  en [0,1]; `prematch_rec` los expone; leaderboard trae ts_mu.

### Task 3: betting — criterio `trueskill`
- `pick_side`: `ts_home=rec.get("ts_home", elo_home)`, `ts_away=rec.get("ts_away",
  elo_away)`. Nuevo criterio `"trueskill"` → score por ts; `p_pick` = ts del lado
  elegido (Elo para los demás, sin cambios).
- `SWEEP_CRITERIA = ("elo","bayes","blend","trueskill")` → 24 combos.
- Tests: `test_pick_side_trueskill` (rec con ts elige por ts, p_pick=ts);
  actualizar `test_sweep_strategies_ranks_by_yield` a 24 y criterio en el set.

### Task 4: UI
- `ui_common.betting_controls`: criterio añade `"trueskill"` (label "TrueSkill (skill)").
- `pages/2_🧪_Qatar_2022.py`: selectbox criterio añade "trueskill"; LABELS añade
  "trueskill":"TrueSkill"; tabla combined añade columnas "TS μ","TS σ"; nuevo tab
  "🤝 TrueSkill" con leaderboard por μ−3σ.
- `app.py`: `crit` dict añade "trueskill"; nuevo expander LaTeX "④ TrueSkill".

### Task 5: docs + validación + commit
- README + CLAUDE: TrueSkill como 3er modelo + criterio.
- `uv run pytest -q` verde; pipeline live sobre Qatar imprime ts del leaderboard.
- Commit.
