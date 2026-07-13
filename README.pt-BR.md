<!-- Seletor de idioma -->
**🌐 Leia em:** [English](README.md) · Português

# Agente de Relatório de SRAG — Relatórios Epidemiológicos Gerados por IA

Uma Prova de Conceito para a **Indicium HealthCare Inc.**: um agente de IA que
consulta uma base de dados real de saúde, busca notícias em tempo real, calcula
métricas epidemiológicas-chave e **gera um relatório automatizado** com gráficos
e explicações escritas por um LLM, fundamentadas nos dados.

A solução usa a base pública do **Open DATASUS** sobre internações por **SRAG**
(Síndrome Respiratória Aguda Grave).

> Construído com **LangGraph**, **LangChain**, **OpenAI**, **DuckDuckGo**, **pandas**,
> **SQLite** e **matplotlib**.

---

## Arquitetura

![Diagrama de arquitetura](docs/arquitetura.png)

Um **orquestrador LangGraph** executa um pipeline explícito e auditável. Cada
etapa é um nó; cada capacidade externa é uma **tool**:

| Nó | O que faz | Tool / recurso |
|------|--------------|-----------------|
| `plan` | Registra o plano de execução (auditabilidade) | — |
| `metrics` | Calcula as 4 métricas com SQL parametrizado | SQLite |
| `charts` | Gera os gráficos de 30 dias e 12 meses | matplotlib |
| `news` | Busca e **sanitiza** notícias de SRAG em tempo real | DuckDuckGo (primária) → Tavily (opcional) |
| `analyze` | **Etapa generativa**: o LLM escreve a interpretação | OpenAI |
| `validate` | Confere denominadores, faixas e arquivos gerados | — |
| `report` | Renderiza o relatório final em Markdown | — |

### Princípio central: o LLM nunca calcula números

Todos os valores vêm de **SQL/Python determinístico**. O LLM apenas *interpreta*
valores pré-calculados e **pré-formatados**. Esse é o principal guardrail contra
alucinação numérica e mantém todos os números do relatório reproduzíveis.

---

## As quatro métricas

| Métrica | Definição | Observação |
|--------|------------|------|
| **Taxa de aumento de casos** | Casos nos últimos 30 dias vs. os 30 dias anteriores | Ancorada na data mais recente do dataset |
| **Taxa de mortalidade** | Óbitos ÷ casos com *desfecho conhecido* | Exclui "Ignorado" para não subestimar |
| **Taxa de ocupação de UTI** | Casos em UTI ÷ hospitalizados com info de UTI conhecida | **Proxy** — o dataset não tem total de leitos |
| **Taxa de vacinação** | Casos vacinados ÷ casos com info de vacinação conhecida | Escolha da coluna guiada por dados (gripe vs. COVID por cobertura); refere-se aos casos de SRAG, não à população |

Mais dois gráficos: **casos diários (últimos 30 dias)** e **casos mensais
(últimos 12 meses)**.

> Escolha metodológica: as janelas temporais são ancoradas na **data mais recente
> do dataset**, não na data atual, porque dados epidemiológicos têm atraso de
> notificação.

---

## Estrutura do projeto

```
src/
  etl/build_db.py        # CSV (DATASUS) -> tabela SQLite limpa
  tools/metrics.py       # cálculo determinístico das métricas (SQL)
  tools/charts.py        # gráficos matplotlib (30d / 12m)
  tools/news.py          # notícias em tempo real + sanitização (anti prompt-injection)
  tools/audit.py         # log de auditoria append-only (JSONL)
  agent/analyst.py       # nó LLM: narrativa fundamentada (etapa generativa)
  agent/orchestrator.py  # pipeline LangGraph
  report/markdown.py     # gerador do relatório final
docs/
  architecture_diagram.py  # gera o PDF/PNG da arquitetura
  arquitetura.pdf          # diagrama conceitual exigido
  dicionario_srag.txt      # dicionário de dados do DATASUS (códigos das colunas)
tests/                   # testes unitários (métricas + guardrails)
```

---

## Setup

Requer Python 3.11+.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
cp .env.example .env               # depois preencha suas chaves
```

`.env`:

```ini
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
TAVILY_API_KEY=tvly-...            # secundária opcional; o DuckDuckGo é a fonte primária
```

### 1. Baixar os dados

No Open DATASUS (SRAG 2019–2026), baixe o CSV de 2019 (`INFLUD19-...csv`) e o
dicionário de dados para a pasta `data/`.

### 2. Construir o banco

```bash
python -m src.etl.build_db --csv data/INFLUD19-23-03-2026.csv
```

### 3. Gerar o relatório

```bash
python -m src.agent.orchestrator          # relatório completo (com notícias + LLM)
python -m src.agent.orchestrator --dry    # versão "seca" (sem notícias/LLM)
```

O relatório é escrito em `outputs/relatorio_srag_completo.md`, os gráficos em
`outputs/*.png` e um log estruturado de auditoria em `outputs/audit_*.jsonl`.

### Rodar os testes

```bash
pytest
```

---

## Como isso atende aos critérios de avaliação

- **Arquitetura** — pipeline LangGraph explícito e auditável; tools
  determinísticas claramente separadas da etapa generativa (LLM).
- **Governança e transparência** — cada execução grava um **log JSONL**
  append-only com decisões, tool calls e uso do LLM; cada métrica documenta seu
  numerador/denominador, janela e ressalvas metodológicas.
- **Guardrails** — o LLM nunca calcula números (os valores são pré-formatados e
  passados prontos); o conteúdo externo de notícias é **sanitizado** (HTML
  removido, caracteres de controle, padrões de prompt-injection neutralizados);
  há sempre um disclaimer médico; o pipeline **degrada graciosamente** (fallback
  de template se o LLM falhar; o DuckDuckGo é a fonte primária de notícias e a
  Tavily é uma secundária opcional, com um filtro de relevância garantindo que só
  entrem no relatório itens realmente sobre SRAG).
- **Uso de Tools** — métricas SQL, geração de gráficos, busca de notícias e
  auditoria são tools independentes e testáveis.
- **Dados sensíveis** — só as colunas mínimas são ingeridas (sem identificadores
  diretos; sexo/idade nunca carregados); o relatório só expõe **agregados**,
  nunca registros individuais; os dados de origem já são anonimizados conforme a
  LGPD.
- **Clean Code** — módulos pequenos e de responsabilidade única; docstrings;
  testes unitários; configuração via variáveis de ambiente.

---

## Limitações

- A taxa de UTI é um **proxy** do uso de UTI entre casos hospitalizados, não a
  ocupação real de leitos (a fonte não traz o total de leitos).
- A taxa de vacinação se refere aos **casos de SRAG**, não à população geral.
- O arquivo de 2019 é anterior à COVID-19, então a métrica de vacinação usa o
  campo da vacina de gripe (escolhido automaticamente pela cobertura de dados).
- As notícias fornecem **apenas contexto**; nunca alteram as métricas calculadas.
- Dados de SRAG estão sujeitos a atraso de notificação, incompletude e revisões.

---

*Este relatório é informativo e não constitui aconselhamento médico, diagnóstico
ou previsão epidemiológica oficial.*
