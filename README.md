<!-- Language selector -->
**🌐 Read this in:** English · [Português](README.pt-BR.md)

# SRAG Report Agent — AI-Generated Epidemiological Reports

A Proof of Concept for **Indicium HealthCare Inc.**: an AI agent that queries a
real health database, retrieves real-time news, computes key epidemiological
metrics and **generates an automated report** with charts and grounded,
LLM-written explanations.

The solution uses the public **Open DATASUS** dataset on **SRAG** (Severe Acute
Respiratory Syndrome / *Síndrome Respiratória Aguda Grave*) hospitalizations.

> Built with **LangGraph**, **LangChain**, **OpenAI**, **DuckDuckGo**, **pandas**,
> **SQLite** and **matplotlib**.

---

## Architecture

![Architecture diagram](docs/arquitetura.png)

A **LangGraph orchestrator** runs an explicit, auditable pipeline. Each step is a
node; each external capability is a **tool**:

| Node | What it does | Tool / resource |
|------|--------------|-----------------|
| `plan` | Registers the execution plan (auditability) | — |
| `metrics` | Computes the 4 metrics with parameterized SQL | SQLite |
| `charts` | Builds the 30-day and 12-month charts | matplotlib |
| `news` | Retrieves and **sanitizes** real-time SRAG news | DuckDuckGo (primary) → Tavily (optional) |
| `analyze` | **Generative step**: the LLM writes the interpretation | OpenAI |
| `validate` | Checks denominators, ranges and generated files | — |
| `report` | Renders the final Markdown report | — |

### Key design principle: the LLM never computes numbers

All figures come from **deterministic SQL/Python**. The LLM only *interprets*
pre-computed, **pre-formatted** values. This is the primary guardrail against
numeric hallucination and keeps every number in the report reproducible.

---

## The four metrics

| Metric | Definition | Note |
|--------|------------|------|
| **Case growth rate** | Cases in the last 30 days vs. the previous 30 days | Anchored to the dataset's latest date |
| **Mortality rate** | Deaths ÷ cases with a *known outcome* | Excludes "Ignored" to avoid underestimation |
| **ICU occupancy rate** | ICU cases ÷ hospitalized cases with known ICU info | **Proxy** — the dataset has no total-beds figure |
| **Vaccination rate** | Vaccinated cases ÷ cases with known vaccination info | Data-driven column choice (flu vs. COVID by coverage); refers to SRAG cases, not the general population |

Plus two charts: **daily cases (last 30 days)** and **monthly cases (last 12 months)**.

> Methodological choice: time windows are anchored to the **latest date in the
> dataset**, not the current date, because epidemiological data has reporting lag.

---

## Project structure

```
src/
  etl/build_db.py        # CSV (DATASUS) -> clean SQLite table
  tools/metrics.py       # deterministic metric calculations (SQL)
  tools/charts.py        # matplotlib charts (30d / 12m)
  tools/news.py          # real-time news + sanitization (anti prompt-injection)
  tools/audit.py         # append-only JSONL audit log
  agent/analyst.py       # LLM node: grounded narrative (generative step)
  agent/orchestrator.py  # LangGraph pipeline
  report/markdown.py     # final report writer
docs/
  architecture_diagram.py  # generates the architecture PDF/PNG
  arquitetura.pdf          # required conceptual diagram
  dicionario_srag.txt      # DATASUS data dictionary (column codes)
tests/                   # unit tests (metrics + guardrails)
```

---

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
cp .env.example .env               # then fill in your keys
```

`.env`:

```ini
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
TAVILY_API_KEY=tvly-...            # optional secondary; DuckDuckGo is the primary source
```

### 1. Download the data

From Open DATASUS (SRAG 2019–2026), download the 2019 CSV
(`INFLUD19-...csv`) and the data dictionary into `data/`.

### 2. Build the database

```bash
python -m src.etl.build_db --csv data/INFLUD19-23-03-2026.csv
```

### 3. Generate the report

```bash
python -m src.agent.orchestrator          # full report (with news + LLM)
python -m src.agent.orchestrator --dry    # "dry" version (no news/LLM)
```

The report is written to `outputs/relatorio_srag_completo.md`, charts to
`outputs/*.png`, and a structured audit log to `outputs/audit_*.jsonl`.

### Run the tests

```bash
pytest
```

---

## How this maps to the evaluation criteria

- **Architecture** — explicit, auditable LangGraph pipeline; deterministic tools
  cleanly separated from the generative (LLM) step.
- **Governance & transparency** — every run writes an append-only **JSONL audit
  log** of decisions, tool calls and LLM usage; each metric documents its
  numerator/denominator, window and methodological caveats.
- **Guardrails** — the LLM never computes numbers (values are pre-formatted and
  passed in); external news is **sanitized** (HTML stripped, control chars
  removed, prompt-injection patterns neutralized); a medical disclaimer is always
  present; the pipeline **degrades gracefully** (template fallback if the LLM
  fails; DuckDuckGo is the primary news source with Tavily as an optional
  secondary, and a relevance filter guarantees only on-topic items reach the report).
- **Tools** — SQL metrics, chart generation, news retrieval and audit logging are
  independent, testable tools.
- **Sensitive data** — only the minimal columns are ingested (no direct
  identifiers; sex/age never loaded); the report only ever exposes **aggregates**,
  never individual records; the source data is already anonymized per LGPD.
- **Clean code** — small, single-responsibility modules; docstrings; unit tests;
  configuration via environment variables.

---

## Limitations

- ICU rate is a **proxy** for ICU usage among hospitalized cases, not real bed
  occupancy (no total-beds data in the source).
- Vaccination rate refers to **SRAG cases**, not the general population.
- The 2019 file predates COVID-19, so the vaccination metric uses the influenza
  vaccine field (chosen automatically by data coverage).
- News provides **context only**; it never alters the computed metrics.
- SRAG data is subject to reporting lag, incompleteness and later revisions.

---

*This report is informational and does not constitute medical advice, diagnosis
or an official epidemiological forecast.*
