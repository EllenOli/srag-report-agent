"""Tests for the deterministic metric calculations."""
import sqlite3

import pytest

from src.tools import metrics


@pytest.fixture()
def sample_db(tmp_path):
    """Small SQLite fixture with known values."""
    db = tmp_path / "srag_test.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE srag (
            data_caso TEXT, uf TEXT, evolucao INT, hospitalizado INT,
            uti INT, vacina_gripe INT, vacina_covid INT, classificacao INT
        )"""
    )
    rows = [
        # date,       uf, evol, hosp, uti, vflu, vcov, classi
        ("2019-01-01", "SP", 1, 1, 1, 1, None, 5),
        ("2019-01-02", "SP", 2, 1, 2, 2, None, 5),  # death
        ("2019-01-03", "RJ", 1, 1, 1, 1, None, 4),
        ("2019-01-04", "RJ", 9, 1, 9, 9, None, 9),  # ignored
        ("2019-01-05", "MG", 2, 1, 1, 2, None, 5),  # death, icu
    ]
    conn.executemany("INSERT INTO srag VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return str(db)


def test_mortality_ignores_unknown_outcomes(sample_db):
    m = metrics.mortality_rate(sample_db)
    # 2 deaths among 4 known outcomes (excludes evolucao=9) -> 0.5
    assert m.numerator == 2
    assert m.denominator == 4
    assert m.value == 0.5


def test_icu_occupancy_is_proxy_among_known(sample_db):
    m = metrics.icu_occupancy_rate(sample_db)
    # uti=1 in 3 cases; known (1 or 2) = 4 -> 0.75
    assert m.numerator == 3
    assert m.denominator == 4
    assert m.value == 0.75


def test_vaccination_picks_column_with_most_coverage(sample_db):
    # vacina_covid is all NULL; vacina_gripe has coverage -> must pick flu
    m = metrics.vaccination_rate(sample_db)
    assert "gripe" in m.name.lower()
    assert m.denominator == 4  # 1,2,1,2 known (the 9 is ignored)


def test_rates_are_within_valid_range(sample_db):
    for m in (metrics.mortality_rate(sample_db),
              metrics.icu_occupancy_rate(sample_db),
              metrics.vaccination_rate(sample_db)):
        assert 0.0 <= m.value <= 1.0
        assert m.numerator <= m.denominator
