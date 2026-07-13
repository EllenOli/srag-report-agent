"""Tests for the deterministic metric calculations."""
import sqlite3

import pytest

from src.tools import metrics


@pytest.fixture()
def sample_db(tmp_path):
    """Small in-memory-like SQLite fixture with known values."""
    db = tmp_path / "srag_test.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE srag (
            data_caso TEXT, uf TEXT, evolucao INT, hospitalizado INT,
            uti INT, vacina_gripe INT, vacina_covid INT, classificacao INT
        )"""
    )
    rows = [
        # data,      uf, evol, hosp, uti, vgripe, vcov, classi
        ("2019-01-01", "SP", 1, 1, 1, 1, None, 5),
        ("2019-01-02", "SP", 2, 1, 2, 2, None, 5),  # obito
        ("2019-01-03", "RJ", 1, 1, 1, 1, None, 4),
        ("2019-01-04", "RJ", 9, 1, 9, 9, None, 9),  # ignorados
        ("2019-01-05", "MG", 2, 1, 1, 2, None, 5),  # obito, uti
    ]
    conn.executemany("INSERT INTO srag VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return str(db)


def test_mortalidade_ignora_desconhecidos(sample_db):
    m = metrics.taxa_mortalidade(sample_db)
    # 2 obitos entre 4 desfechos conhecidos (exclui o evolucao=9) -> 0.5
    assert m.numerador == 2
    assert m.denominador == 4
    assert m.valor == 0.5


def test_ocupacao_uti_e_proxy_entre_conhecidos(sample_db):
    m = metrics.taxa_ocupacao_uti(sample_db)
    # uti=1 em 3 casos; conhecidos (1 ou 2) = 4 -> 0.75
    assert m.numerador == 3
    assert m.denominador == 4
    assert m.valor == 0.75


def test_vacinacao_escolhe_coluna_com_mais_cobertura(sample_db):
    # vacina_covid e todo NULL; vacina_gripe tem cobertura -> deve escolher gripe
    m = metrics.taxa_vacinacao(sample_db)
    assert "gripe" in m.nome.lower()
    assert m.denominador == 4  # 1,2,1,2 conhecidos (o 9 e ignorado)


def test_taxas_estao_no_intervalo_valido(sample_db):
    for m in (metrics.taxa_mortalidade(sample_db),
              metrics.taxa_ocupacao_uti(sample_db),
              metrics.taxa_vacinacao(sample_db)):
        assert 0.0 <= m.valor <= 1.0
        assert m.numerador <= m.denominador
