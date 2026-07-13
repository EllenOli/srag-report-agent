"""Tool de gráficos — gera os dois gráficos exigidos pelo desafio.

    1. Casos diários dos últimos 30 dias.
    2. Casos mensais dos últimos 12 meses.

Como nas métricas, as janelas são ancoradas na data mais recente do dataset.
Os gráficos são salvos como PNG em outputs/ e o caminho é devolvido para o
agente incluir no relatório.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

Path("outputs", ".matplotlib-cache").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs") / ".matplotlib-cache"))

import matplotlib
matplotlib.use("Agg")  # backend sem interface (roda em servidor/headless)
import matplotlib.pyplot as plt
import pandas as pd

DB_PATH = "data/srag.db"
OUT_DIR = Path("outputs")
AZUL = "#2F6DB0"


def _read(db_path: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as c:
        df = pd.read_sql("SELECT data_caso FROM srag", c, parse_dates=["data_caso"])
    return df


def grafico_casos_diarios(db_path: str = DB_PATH, dias: int = 30) -> str:
    df = _read(db_path)
    fim = df["data_caso"].max()
    ini = fim - pd.Timedelta(days=dias)
    janela = df[(df["data_caso"] > ini) & (df["data_caso"] <= fim)]
    serie = (janela.groupby(janela["data_caso"].dt.date).size()
             .reindex(pd.date_range(ini + pd.Timedelta(days=1), fim).date, fill_value=0))

    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / "casos_diarios_30d.png"
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(serie.index, serie.values, color=AZUL)
    ax.set_title(f"Casos diarios de SRAG - ultimos {dias} dias (ref. {fim.date()})")
    ax.set_ylabel("Casos")
    ax.grid(axis="y", alpha=.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path.as_posix()


def grafico_casos_mensais(db_path: str = DB_PATH, meses: int = 12) -> str:
    df = _read(db_path)
    fim = df["data_caso"].max()
    ini = (fim - pd.DateOffset(months=meses)).replace(day=1)
    janela = df[df["data_caso"] >= ini]
    serie = (janela.groupby(janela["data_caso"].dt.to_period("M")).size())
    serie.index = serie.index.astype(str)

    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / "casos_mensais_12m.png"
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(serie.index, serie.values, marker="o", color=AZUL, linewidth=2)
    ax.set_title(f"Casos mensais de SRAG - ultimos {meses} meses (ref. {fim.date()})")
    ax.set_ylabel("Casos")
    ax.grid(alpha=.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path.as_posix()


def gerar_todos(db_path: str = DB_PATH) -> dict:
    return {
        "casos_diarios": grafico_casos_diarios(db_path),
        "casos_mensais": grafico_casos_mensais(db_path),
    }


if __name__ == "__main__":
    print(gerar_todos())
