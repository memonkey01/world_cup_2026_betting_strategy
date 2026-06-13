"""
Resultados reales de Qatar 2022 (subconjunto: fase de grupos completa de
varios grupos + algunos de eliminacion). Sirve para validar el pipeline
Elo/Bayes offline. Reemplazable por el scrape real de ESPN.
Marcadores en tiempo reglamentario (los penales no cuentan para Elo).
"""

QATAR_2022_SAMPLE = [
    # date, stage, home, away, hg, ag
    ("2022-11-20", "group", "Qatar", "Ecuador", 0, 2),
    ("2022-11-21", "group", "England", "Iran", 6, 2),
    ("2022-11-21", "group", "Senegal", "Netherlands", 0, 2),
    ("2022-11-21", "group", "USA", "Wales", 1, 1),
    ("2022-11-22", "group", "Argentina", "Saudi Arabia", 1, 2),
    ("2022-11-22", "group", "Denmark", "Tunisia", 0, 0),
    ("2022-11-22", "group", "Mexico", "Poland", 0, 0),
    ("2022-11-22", "group", "France", "Australia", 4, 1),
    ("2022-11-23", "group", "Morocco", "Croatia", 0, 0),
    ("2022-11-23", "group", "Germany", "Japan", 1, 2),
    ("2022-11-23", "group", "Spain", "Costa Rica", 7, 0),
    ("2022-11-23", "group", "Belgium", "Canada", 1, 0),
    ("2022-11-24", "group", "Switzerland", "Cameroon", 1, 0),
    ("2022-11-24", "group", "Uruguay", "Korea Republic", 0, 0),
    ("2022-11-24", "group", "Portugal", "Ghana", 3, 2),
    ("2022-11-24", "group", "Brazil", "Serbia", 2, 0),
    ("2022-11-25", "group", "Wales", "Iran", 0, 2),
    ("2022-11-25", "group", "Qatar", "Senegal", 1, 3),
    ("2022-11-25", "group", "Netherlands", "Ecuador", 1, 1),
    ("2022-11-25", "group", "England", "USA", 0, 0),
    ("2022-11-26", "group", "Tunisia", "Australia", 0, 1),
    ("2022-11-26", "group", "Poland", "Saudi Arabia", 2, 0),
    ("2022-11-26", "group", "France", "Denmark", 2, 1),
    ("2022-11-26", "group", "Argentina", "Mexico", 2, 0),
    ("2022-11-27", "group", "Japan", "Costa Rica", 0, 1),
    ("2022-11-27", "group", "Belgium", "Morocco", 0, 2),
    ("2022-11-27", "group", "Croatia", "Canada", 4, 1),
    ("2022-11-27", "group", "Spain", "Germany", 1, 1),
    ("2022-11-28", "group", "Cameroon", "Serbia", 3, 3),
    ("2022-11-28", "group", "Korea Republic", "Ghana", 2, 3),
    ("2022-11-28", "group", "Brazil", "Switzerland", 1, 0),
    ("2022-11-28", "group", "Portugal", "Uruguay", 2, 0),
    # eliminacion directa (tiempo reglamentario)
    ("2022-12-03", "R16", "Netherlands", "USA", 3, 1),
    ("2022-12-03", "R16", "Argentina", "Australia", 2, 1),
    ("2022-12-04", "R16", "France", "Poland", 3, 1),
    ("2022-12-04", "R16", "England", "Senegal", 3, 0),
    ("2022-12-05", "R16", "Japan", "Croatia", 1, 1),
    ("2022-12-05", "R16", "Brazil", "Korea Republic", 4, 1),
    ("2022-12-06", "R16", "Morocco", "Spain", 0, 0),
    ("2022-12-06", "R16", "Portugal", "Switzerland", 6, 1),
    ("2022-12-09", "QF", "Croatia", "Brazil", 1, 1),
    ("2022-12-09", "QF", "Netherlands", "Argentina", 2, 2),
    ("2022-12-10", "QF", "Morocco", "Portugal", 1, 0),
    ("2022-12-10", "QF", "England", "France", 1, 2),
    ("2022-12-13", "SF", "Argentina", "Croatia", 3, 0),
    ("2022-12-14", "SF", "France", "Morocco", 2, 0),
    ("2022-12-17", "3rd", "Croatia", "Morocco", 2, 1),
    ("2022-12-18", "final", "Argentina", "France", 3, 3),
]
