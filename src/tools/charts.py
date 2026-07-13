"""Charts tool — builds the two charts required by the challenge.

    1. Daily cases over the last 30 days.
    2. Monthly cases over the last 12 months.

As with the metrics, the windows are anchored to the dataset's most recent date.
Charts are saved as PNG in outputs/ and the path is returned for the agent to
embed in the report. Titles are kept in Portuguese (report content).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

Path("outputs", ".matplotlib-cache").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs") / ".matplotlib-cache"))

import matplotlib
matplotlib.use("Agg")  # headless backend (runs on a server without a display)
import matplotlib.pyplot as plt
import pandas as pd

DB_PATH = "data/srag.db"
OUT_DIR = Path("outputs")
BLUE = "#2F6DB0"


def _read(db_path: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as c:
        return pd.read_sql("SELECT data_caso FROM srag", c, parse_dates=["data_caso"])


def daily_cases_chart(db_path: str = DB_PATH, days: int = 30) -> str:
    df = _read(db_path)
    end = df["data_caso"].max()
    start = end - pd.Timedelta(days=days)
    window = df[(df["data_caso"] > start) & (df["data_caso"] <= end)]
    series = (window.groupby(window["data_caso"].dt.date).size()
              .reindex(pd.date_range(start + pd.Timedelta(days=1), end).date, fill_value=0))

    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / "casos_diarios_30d.png"
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(series.index, series.values, color=BLUE)
    ax.set_title(f"Casos diarios de SRAG - ultimos {days} dias (ref. {end.date()})")
    ax.set_ylabel("Casos")
    ax.grid(axis="y", alpha=.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path.as_posix()


def monthly_cases_chart(db_path: str = DB_PATH, months: int = 12) -> str:
    df = _read(db_path)
    end = df["data_caso"].max()
    start = (end - pd.DateOffset(months=months)).replace(day=1)
    window = df[df["data_caso"] >= start]
    series = window.groupby(window["data_caso"].dt.to_period("M")).size()
    series.index = series.index.astype(str)

    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / "casos_mensais_12m.png"
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(series.index, series.values, marker="o", color=BLUE, linewidth=2)
    ax.set_title(f"Casos mensais de SRAG - ultimos {months} meses (ref. {end.date()})")
    ax.set_ylabel("Casos")
    ax.grid(alpha=.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path.as_posix()


def generate_all_charts(db_path: str = DB_PATH) -> dict:
    return {
        "daily": daily_cases_chart(db_path),
        "monthly": monthly_cases_chart(db_path),
    }


if __name__ == "__main__":
    print(generate_all_charts())
