"""ETL: raw Open DATASUS (SRAG) CSV -> clean SQLite table.

Why this step exists:
    The DATASUS file has ~100 columns and ~165k rows, with many poorly filled
    fields and sensitive data (clinical/demographic). The agent must NOT read
    this raw CSV on every question. We ingest it ONCE:
      1. select only the columns needed for the 4 metrics;
      2. drop direct identifiers (sensitive data / LGPD);
      3. normalize dates and derive a single `data_caso`;
      4. write a lean, typed table (`srag`) into SQLite.

    The agent then queries this table with parameterized SQL — fast, safe and
    auditable.

Usage:
    python -m src.etl.build_db --csv data/INFLUD19-23-03-2026.csv
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Columns we care about (DATASUS name -> our name).
# Keep only what the metrics need + non-identifiable aggregations.
# ---------------------------------------------------------------------------
COLS = {
    "DT_SIN_PRI":  "dt_sintomas",     # first-symptoms date -> case counting
    "DT_NOTIFIC":  "dt_notificacao",  # date fallback
    "SG_UF_NOT":   "uf",              # state (aggregated, does not identify a person)
    "EVOLUCAO":    "evolucao",        # 1=cure 2=death 3=other-cause death 9=ignored
    "HOSPITAL":    "hospitalizado",   # 1=Yes 2=No 9=Ignored
    "UTI":         "uti",             # 1=Yes 2=No 9=Ignored
    "VACINA":      "vacina_gripe",    # 1=Yes 2=No 9=Ignored (FLU vaccine)
    "VACINA_COV":  "vacina_covid",    # 1=Yes 2=No 9=Ignored (COVID-19 vaccine)
    "CLASSI_FIN":  "classificacao",   # final case classification
}
# Alternative state columns in case the main one is absent from the file.
UF_FALLBACKS = ["SG_UF_NOT", "SG_UF", "CO_UF_NOT"]
DATE_COLS_RAW = ["DT_SIN_PRI", "DT_NOTIFIC"]


def _available_columns(csv_path: str) -> list[str]:
    """Read only the header to learn which columns actually exist."""
    head = pd.read_csv(csv_path, sep=";", nrows=0, encoding="latin-1")
    return list(head.columns)


def _pick_columns(available: list[str]) -> dict[str, str]:
    mapping = {src: dst for src, dst in COLS.items() if src in available}
    if "SG_UF_NOT" not in mapping:  # try an alternative state column
        for alt in UF_FALLBACKS:
            if alt in available:
                mapping[alt] = "uf"
                break
    return mapping


def _to_datetime(series: pd.Series) -> pd.Series:
    """Robustly parse DATASUS dates.

    The dictionary says DD/MM/YYYY, but the current portal export uses ISO
    (e.g. '2019-07-22T00:00:00.000Z'). We try ISO first and, for whatever is
    left, try the Brazilian format — without breaking on either.
    """
    iso = pd.to_datetime(series, errors="coerce", utc=True).dt.tz_localize(None)
    missing = iso.isna() & series.notna()
    if missing.any():
        br = pd.to_datetime(series[missing], format="%d/%m/%Y", errors="coerce")
        iso.loc[missing] = br
    return iso


def _parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    for raw in DATE_COLS_RAW:
        dst = COLS.get(raw)
        if dst and dst in df.columns:
            df[dst] = _to_datetime(df[dst])
    # data_caso = first symptoms, falling back to notification date
    dt_sin = df.get("dt_sintomas")
    dt_not = df.get("dt_notificacao")
    if dt_sin is not None:
        df["data_caso"] = dt_sin.fillna(dt_not) if dt_not is not None else dt_sin
    elif dt_not is not None:
        df["data_caso"] = dt_not
    return df


def _read_one(csv_path: str) -> pd.DataFrame:
    """Read one DATASUS CSV in chunks, keeping only the useful columns."""
    available = _available_columns(csv_path)
    mapping = _pick_columns(available)
    print(f"\n[{Path(csv_path).name}] {len(available)} columns | using {list(mapping.keys())}")
    frames = []
    chunks = pd.read_csv(
        csv_path, sep=";", encoding="latin-1",
        usecols=list(mapping.keys()), dtype=str, chunksize=50_000,
    )
    for i, chunk in enumerate(chunks, 1):
        frames.append(chunk.rename(columns=mapping))
        print(f"  chunk {i}: +{len(chunk)} rows")
    return pd.concat(frames, ignore_index=True)


def build(csv_paths: list[str], db_path: str = "data/srag.db") -> None:
    # Accept one or several CSVs (e.g. 2025 + 2026) and concatenate them.
    df = pd.concat([_read_one(p) for p in csv_paths], ignore_index=True)

    # Typing: categorical fields become numeric; dates become datetime.
    for col in ["evolucao", "hospitalizado", "uti", "vacina_gripe", "vacina_covid", "classificacao"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = _parse_dates(df)

    # Drop rows with no date (useless for any time-based metric).
    before = len(df)
    df = df.dropna(subset=["data_caso"])
    print(f"Rows with a valid date: {len(df)} (dropped {before - len(df)})")

    # Keep only the final columns and sort.
    final_cols = [c for c in ["data_caso", "uf", "evolucao", "hospitalizado",
                              "uti", "vacina_gripe", "vacina_covid", "classificacao"] if c in df.columns]
    df = df[final_cols].sort_values("data_caso").reset_index(drop=True)
    df["data_caso"] = df["data_caso"].dt.strftime("%Y-%m-%d")

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        df.to_sql("srag", conn, if_exists="replace", index=False)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_data ON srag(data_caso)")
    print(f"\nOK -> {len(df)} rows written to {db_path} (table 'srag').")
    print("Period covered:", df["data_caso"].min(), "->", df["data_caso"].max())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, nargs="+",
                    help="One or more DATASUS CSVs (e.g. --csv data/2025.csv data/2026.csv)")
    ap.add_argument("--db", default="data/srag.db")
    args = ap.parse_args()
    build(args.csv, args.db)
