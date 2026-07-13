"""Metrics tool — deterministic calculations over the SRAG database.

Design principle (guardrail #1 against hallucination):
    The LLM does NOT compute numbers. This module does, with parameterized SQL.
    The agent only calls these functions and INTERPRETS the results, so every
    figure in the report is reproducible and auditable.

Rate convention:
    The denominator counts only records with a KNOWN value (ignoring code
    9-"Ignorado" and nulls). This avoids underestimating rates because of the
    typical under-filling of real health data.

Time windows:
    "Last N days/months" are anchored to the dataset's MOST RECENT date (not
    today), because epidemiological data has reporting lag.

Note: metric display names and notes are kept in Portuguese on purpose — they
are report content aimed at Brazilian health professionals.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import timedelta

import pandas as pd

DB_PATH = "data/srag.db"


def _conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def _latest_date(conn: sqlite3.Connection) -> pd.Timestamp:
    value = conn.execute("SELECT MAX(data_caso) FROM srag").fetchone()[0]
    return pd.Timestamp(value)


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


@dataclass
class Metric:
    name: str
    value: float          # the rate (0..1) or the raw number
    unit: str             # '%' or 'casos'
    numerator: int
    denominator: int
    window: str           # description of the window used
    note: str = ""        # methodological caveat (transparency)

    def as_dict(self) -> dict:
        return asdict(self)


def case_growth_rate(db_path: str = DB_PATH, days: int = 30) -> Metric:
    """Compare cases in the last N days with the immediately preceding N days."""
    with _conn(db_path) as c:
        end = _latest_date(c)
        start_current = end - timedelta(days=days)
        start_previous = end - timedelta(days=2 * days)

        def count(a, b):
            return c.execute(
                "SELECT COUNT(*) FROM srag WHERE data_caso > ? AND data_caso <= ?",
                (a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")),
            ).fetchone()[0]

        current = count(start_current, end)
        previous = count(start_previous, start_current)
        rate = (current - previous) / previous if previous else 0.0
    return Metric(
        name="Taxa de aumento de casos",
        value=round(rate, 4), unit="%",
        numerator=current, denominator=previous,
        window=f"ultimos {days} dias vs. {days} dias anteriores (ref. {end.date()})",
        note="Variacao percentual entre os dois periodos.",
    )


def _binary_rate(db_path, column, positive, name, note) -> Metric:
    """Generic rate: positives / known values, ignoring code 9 and nulls."""
    with _conn(db_path) as c:
        num = c.execute(
            f"SELECT COUNT(*) FROM srag WHERE {column} = ?", (positive,)
        ).fetchone()[0]
        den = c.execute(
            f"SELECT COUNT(*) FROM srag WHERE {column} IN (1, 2)"
        ).fetchone()[0]
        rate = num / den if den else 0.0
    return Metric(name=name, value=round(rate, 4), unit="%",
                  numerator=num, denominator=den,
                  window="todo o periodo do dataset", note=note)


def mortality_rate(db_path: str = DB_PATH) -> Metric:
    with _conn(db_path) as c:
        num = c.execute("SELECT COUNT(*) FROM srag WHERE evolucao = 2").fetchone()[0]
        den = c.execute("SELECT COUNT(*) FROM srag WHERE evolucao IN (1, 2)").fetchone()[0]
        rate = num / den if den else 0.0
    return Metric(
        name="Taxa de mortalidade", value=round(rate, 4), unit="%",
        numerator=num, denominator=den, window="todo o periodo do dataset",
        note="Obitos por SRAG / casos com desfecho conhecido (cura ou obito); exclui 'Ignorado'.",
    )


def icu_occupancy_rate(db_path: str = DB_PATH) -> Metric:
    with _conn(db_path) as c:
        num = c.execute(
            "SELECT COUNT(*) FROM srag WHERE hospitalizado = 1 AND uti = 1"
        ).fetchone()[0]
        den = c.execute(
            "SELECT COUNT(*) FROM srag WHERE hospitalizado = 1 AND uti IN (1, 2)"
        ).fetchone()[0]
        rate = num / den if den else 0.0
    return Metric(
        name="Taxa de ocupacao de UTI",
        value=round(rate, 4), unit="%",
        numerator=num, denominator=den,
        window="todo o periodo do dataset",
        note=(
            "PROXY: % de casos hospitalizados que usaram UTI entre os hospitalizados "
            "com informacao de UTI conhecida. O dataset nao traz leitos totais, "
            "entao nao e ocupacao real de leitos."
        ),
    )


def vaccination_rate(db_path: str = DB_PATH) -> Metric:
    """Pick the vaccine field with meaningful coverage in the dataset (data-driven).

    The file may contain both VACINA (flu) and VACINA_COV (COVID). Instead of
    hard-coding one, we choose the field with the LARGEST known denominator — the
    one that actually carries signal. In the 2019 file this selects the flu
    vaccine (den ~31k), avoiding COVID, which appears only as sparse data-entry
    noise (den ~350) since it predates the COVID-19 vaccination campaigns.
    """
    candidates = [
        ("vacina_covid", "COVID-19"),
        ("vacina_gripe", "gripe"),
    ]
    best = None  # (den, num, column, label)
    with _conn(db_path) as c:
        for column, label in candidates:
            if not _has_column(c, "srag", column):
                continue
            num = c.execute(f"SELECT COUNT(*) FROM srag WHERE {column} = 1").fetchone()[0]
            den = c.execute(f"SELECT COUNT(*) FROM srag WHERE {column} IN (1, 2)").fetchone()[0]
            if best is None or den > best[0]:
                best = (den, num, column, label)

    if not best or best[0] == 0:
        return Metric(
            name="Taxa de vacinacao", value=0.0, unit="%",
            numerator=0, denominator=0, window="todo o periodo do dataset",
            note="Sem informacao de vacinacao com denominador conhecido no dataset.",
        )

    den, num, column, label = best
    return Metric(
        name=f"Taxa de vacinacao {label} entre casos",
        value=round(num / den, 4), unit="%",
        numerator=num, denominator=den, window="todo o periodo do dataset",
        note=(
            f"% de casos de SRAG vacinados contra {label} entre os casos com informacao "
            "conhecida (1=Sim, 2=Nao). Coluna escolhida por ter a maior cobertura de "
            "preenchimento no dataset. NAO representa cobertura vacinal da populacao."
        ),
    )


def get_all_metrics(db_path: str = DB_PATH) -> list[dict]:
    return [
        case_growth_rate(db_path).as_dict(),
        mortality_rate(db_path).as_dict(),
        icu_occupancy_rate(db_path).as_dict(),
        vaccination_rate(db_path).as_dict(),
    ]


if __name__ == "__main__":
    import json
    print(json.dumps(get_all_metrics(), indent=2, ensure_ascii=False))
