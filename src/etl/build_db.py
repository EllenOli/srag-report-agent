"""ETL: CSV bruto do Open DATASUS (SRAG) -> tabela limpa em SQLite.

Por que este passo existe:
    O arquivo do DATASUS tem ~100 colunas e ~165 mil linhas, com muitos campos
    mal preenchidos e dados sensíveis (clínicos/demográficos). O agente NÃO deve
    ler esse CSV cru a cada pergunta. Aqui fazemos a ingestão UMA vez:
      1. selecionamos apenas as colunas necessárias para as 4 métricas;
      2. descartamos identificadores diretos (dados sensíveis / LGPD);
      3. padronizamos datas e derivamos uma única `data_caso`;
      4. gravamos uma tabela enxuta e tipada (`srag`) no SQLite.

    O agente depois consulta essa tabela com SQL parametrizado — rápido, seguro
    e auditável.

Uso:
    python -m src.etl.build_db --csv data/INFLUD24.csv
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Colunas que nos interessam (nome no DATASUS -> uso).
# Mantemos só o necessário para as métricas + agregações não identificáveis.
# ---------------------------------------------------------------------------
COLS = {
    "DT_SIN_PRI":  "dt_sintomas",     # data 1os sintomas  -> contagem de casos
    "DT_NOTIFIC":  "dt_notificacao",  # fallback de data
    "SG_UF_NOT":   "uf",              # UF (agregada, não identifica pessoa)
    "EVOLUCAO":    "evolucao",        # 1=cura 2=óbito 3=óbito outras 9=ignorado
    "HOSPITAL":    "hospitalizado",   # 1=Sim 2=Não 9=Ignorado
    "UTI":         "uti",             # 1=Sim 2=Não 9=Ignorado
    "VACINA":      "vacina_gripe",    # 1=Sim 2=Não 9=Ignorado (vacina contra GRIPE)
    "VACINA_COV":  "vacina_covid",    # 1=Sim 2=Nao 9=Ignorado (vacina COVID-19)
    "CLASSI_FIN":  "classificacao",   # classificação final do caso
}
# UFs alternativas caso a principal não exista no arquivo.
UF_FALLBACKS = ["SG_UF_NOT", "SG_UF", "CO_UF_NOT"]
DATE_COLS_RAW = ["DT_SIN_PRI", "DT_NOTIFIC"]


def _available_columns(csv_path: str) -> list[str]:
    """Lê só o cabeçalho para saber quais colunas existem de fato."""
    head = pd.read_csv(csv_path, sep=";", nrows=0, encoding="latin-1")
    return list(head.columns)


def _pick_columns(available: list[str]) -> dict[str, str]:
    mapping = {src: dst for src, dst in COLS.items() if src in available}
    if "SG_UF_NOT" not in mapping:  # tenta uma UF alternativa
        for alt in UF_FALLBACKS:
            if alt in available:
                mapping[alt] = "uf"
                break
    return mapping


def _to_datetime(series: pd.Series) -> pd.Series:
    """Converte datas do DATASUS de forma robusta.

    O dicionário indica DD/MM/AAAA, mas a exportação atual do portal usa ISO
    (ex.: '2019-07-22T00:00:00.000Z'). Tentamos ISO primeiro e, para o que
    sobrar, tentamos o formato brasileiro — sem quebrar em nenhum dos dois.
    """
    iso = pd.to_datetime(series, errors="coerce", utc=True).dt.tz_localize(None)
    faltando = iso.isna() & series.notna()
    if faltando.any():
        br = pd.to_datetime(series[faltando], format="%d/%m/%Y", errors="coerce")
        iso.loc[faltando] = br
    return iso


def _parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    for raw in DATE_COLS_RAW:
        dst = COLS.get(raw)
        if dst and dst in df.columns:
            df[dst] = _to_datetime(df[dst])
    # data_caso = primeiro sintoma, com fallback para notificação
    dt_sin = df.get("dt_sintomas")
    dt_not = df.get("dt_notificacao")
    if dt_sin is not None:
        df["data_caso"] = dt_sin.fillna(dt_not) if dt_not is not None else dt_sin
    elif dt_not is not None:
        df["data_caso"] = dt_not
    return df


def _read_one(csv_path: str) -> pd.DataFrame:
    """Lê um CSV do DATASUS em chunks, selecionando só as colunas úteis."""
    available = _available_columns(csv_path)
    mapping = _pick_columns(available)
    print(f"\n[{Path(csv_path).name}] {len(available)} colunas | usando {list(mapping.keys())}")
    frames = []
    chunks = pd.read_csv(
        csv_path, sep=";", encoding="latin-1",
        usecols=list(mapping.keys()), dtype=str, chunksize=50_000,
    )
    for i, chunk in enumerate(chunks, 1):
        frames.append(chunk.rename(columns=mapping))
        print(f"  chunk {i}: +{len(chunk)} linhas")
    return pd.concat(frames, ignore_index=True)


def build(csv_paths: list[str], db_path: str = "data/srag.db") -> None:
    # Aceita um ou vários CSVs (ex.: 2025 + 2026) e concatena tudo.
    df = pd.concat([_read_one(p) for p in csv_paths], ignore_index=True)

    # Tipagem: campos categóricos viram numéricos; datas viram datetime.
    for col in ["evolucao", "hospitalizado", "uti", "vacina_gripe", "vacina_covid", "classificacao"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = _parse_dates(df)

    # Descarta linhas sem data (não servem para nenhuma métrica temporal).
    before = len(df)
    df = df.dropna(subset=["data_caso"])
    print(f"Linhas com data válida: {len(df)} (removidas {before - len(df)})")

    # Guarda só as colunas finais e ordena.
    final_cols = [c for c in ["data_caso", "uf", "evolucao", "hospitalizado",
                              "uti", "vacina_gripe", "vacina_covid", "classificacao"] if c in df.columns]
    df = df[final_cols].sort_values("data_caso").reset_index(drop=True)
    df["data_caso"] = df["data_caso"].dt.strftime("%Y-%m-%d")

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        df.to_sql("srag", conn, if_exists="replace", index=False)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_data ON srag(data_caso)")
    print(f"\nOK -> {len(df)} registros gravados em {db_path} (tabela 'srag').")
    print("Período coberto:", df["data_caso"].min(), "->", df["data_caso"].max())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, nargs="+",
                    help="Um ou mais CSVs do DATASUS (ex.: --csv data/2025.csv data/2026.csv)")
    ap.add_argument("--db", default="data/srag.db")
    args = ap.parse_args()
    build(args.csv, args.db)
