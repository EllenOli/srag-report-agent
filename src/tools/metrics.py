"""Tool de métricas — cálculos determinísticos sobre o banco SRAG.

Princípio de design (guardrail nº 1 contra alucinação):
    O LLM NÃO calcula números. Quem calcula é este módulo, com SQL parametrizado.
    O agente apenas chama estas funções e INTERPRETA os resultados. Assim as
    métricas do relatório são sempre reproduzíveis e auditáveis.

Convenção das taxas:
    Usamos como denominador apenas os registros com valor CONHECIDO (ignorando
    o código 9-Ignorado e nulos). Isso evita subestimar as taxas por causa do
    sub-preenchimento típico de dados reais de saúde.

Janelas temporais:
    "Últimos N dias/meses" são ancorados na DATA MAIS RECENTE do próprio dataset
    (não na data de hoje), porque dados epidemiológicos têm atraso de notificação.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, asdict
from datetime import timedelta

import pandas as pd

DB_PATH = "data/srag.db"


def _conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def _latest_date(conn: sqlite3.Connection) -> pd.Timestamp:
    v = conn.execute("SELECT MAX(data_caso) FROM srag").fetchone()[0]
    return pd.Timestamp(v)


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


@dataclass
class Metric:
    nome: str
    valor: float          # a taxa (0..1) ou o número
    unidade: str          # '%' ou 'casos'
    numerador: int
    denominador: int
    janela: str           # descrição da janela usada
    observacao: str = ""  # ressalva metodológica (transparência)

    def as_dict(self) -> dict:
        return asdict(self)


def taxa_aumento_casos(db_path: str = DB_PATH, dias: int = 30) -> Metric:
    """Compara casos dos últimos N dias com os N dias imediatamente anteriores."""
    with _conn(db_path) as c:
        fim = _latest_date(c)
        ini_atual = fim - timedelta(days=dias)
        ini_ant = fim - timedelta(days=2 * dias)

        def count(a, b):
            return c.execute(
                "SELECT COUNT(*) FROM srag WHERE data_caso > ? AND data_caso <= ?",
                (a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")),
            ).fetchone()[0]

        atual = count(ini_atual, fim)
        anterior = count(ini_ant, ini_atual)
        taxa = (atual - anterior) / anterior if anterior else 0.0
    return Metric(
        nome="Taxa de aumento de casos",
        valor=round(taxa, 4), unidade="%",
        numerador=atual, denominador=anterior,
        janela=f"ultimos {dias} dias vs. {dias} dias anteriores (ref. {fim.date()})",
        observacao="Variacao percentual entre os dois periodos.",
    )


def _taxa_binaria(db_path, coluna, positivo, nome, obs) -> Metric:
    """Taxa genérica: positivos / (valores conhecidos), ignorando 9 e nulos."""
    with _conn(db_path) as c:
        num = c.execute(
            f"SELECT COUNT(*) FROM srag WHERE {coluna} = ?", (positivo,)
        ).fetchone()[0]
        den = c.execute(
            f"SELECT COUNT(*) FROM srag WHERE {coluna} IN (1, 2)"
        ).fetchone()[0]
        taxa = num / den if den else 0.0
    return Metric(nome=nome, valor=round(taxa, 4), unidade="%",
                  numerador=num, denominador=den,
                  janela="todo o periodo do dataset", observacao=obs)


def taxa_mortalidade(db_path: str = DB_PATH) -> Metric:
    with _conn(db_path) as c:
        num = c.execute("SELECT COUNT(*) FROM srag WHERE evolucao = 2").fetchone()[0]
        den = c.execute("SELECT COUNT(*) FROM srag WHERE evolucao IN (1, 2)").fetchone()[0]
        taxa = num / den if den else 0.0
    return Metric(
        nome="Taxa de mortalidade", valor=round(taxa, 4), unidade="%",
        numerador=num, denominador=den, janela="todo o periodo do dataset",
        observacao="Obitos por SRAG / casos com desfecho conhecido (cura ou obito); exclui 'Ignorado'.",
    )


def taxa_ocupacao_uti(db_path: str = DB_PATH) -> Metric:
    with _conn(db_path) as c:
        num = c.execute(
            "SELECT COUNT(*) FROM srag WHERE hospitalizado = 1 AND uti = 1"
        ).fetchone()[0]
        den = c.execute(
            "SELECT COUNT(*) FROM srag WHERE hospitalizado = 1 AND uti IN (1, 2)"
        ).fetchone()[0]
        taxa = num / den if den else 0.0
    return Metric(
        nome="Taxa de ocupacao de UTI",
        valor=round(taxa, 4), unidade="%",
        numerador=num, denominador=den,
        janela="todo o periodo do dataset",
        observacao=(
            "PROXY: % de casos hospitalizados que usaram UTI entre os hospitalizados "
            "com informacao de UTI conhecida. O dataset nao traz leitos totais, "
            "entao nao e ocupacao real de leitos."
        ),
    )


def taxa_vacinacao(db_path: str = DB_PATH) -> Metric:
    """Escolhe a vacina com cobertura significativa no dataset (data-driven).

    O arquivo pode conter tanto VACINA (gripe) quanto VACINA_COV (COVID). Em vez
    de fixar uma, escolhemos a que tem MAIOR denominador conhecido — a que
    realmente tem sinal. No arquivo de 2019, isso seleciona a vacina de gripe
    (den ~31 mil), evitando a COVID, que aparece apenas como ruído esparso de
    preenchimento (den ~350) por ser anterior às campanhas de COVID-19.
    """
    candidatos = [
        ("vacina_covid", "COVID-19"),
        ("vacina_gripe", "gripe"),
    ]
    melhor = None  # (den, num, coluna, rotulo)
    with _conn(db_path) as c:
        for coluna, rotulo in candidatos:
            if not _has_column(c, "srag", coluna):
                continue
            num = c.execute(f"SELECT COUNT(*) FROM srag WHERE {coluna} = 1").fetchone()[0]
            den = c.execute(f"SELECT COUNT(*) FROM srag WHERE {coluna} IN (1, 2)").fetchone()[0]
            if melhor is None or den > melhor[0]:
                melhor = (den, num, coluna, rotulo)

    if not melhor or melhor[0] == 0:
        return Metric(
            nome="Taxa de vacinacao", valor=0.0, unidade="%",
            numerador=0, denominador=0, janela="todo o periodo do dataset",
            observacao="Sem informacao de vacinacao com denominador conhecido no dataset.",
        )

    den, num, coluna, rotulo = melhor
    return Metric(
        nome=f"Taxa de vacinacao {rotulo} entre casos",
        valor=round(num / den, 4), unidade="%",
        numerador=num, denominador=den, janela="todo o periodo do dataset",
        observacao=(
            f"% de casos de SRAG vacinados contra {rotulo} entre os casos com informacao "
            "conhecida (1=Sim, 2=Nao). Coluna escolhida por ter a maior cobertura de "
            "preenchimento no dataset. NAO representa cobertura vacinal da populacao."
        ),
    )


def todas_as_metricas(db_path: str = DB_PATH) -> list[dict]:
    return [
        taxa_aumento_casos(db_path).as_dict(),
        taxa_mortalidade(db_path).as_dict(),
        taxa_ocupacao_uti(db_path).as_dict(),
        taxa_vacinacao(db_path).as_dict(),
    ]


if __name__ == "__main__":
    import json
    print(json.dumps(todas_as_metricas(), indent=2, ensure_ascii=False))
