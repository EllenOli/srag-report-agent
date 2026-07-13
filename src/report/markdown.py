"""Markdown report writer for the first SRAG PoC milestone."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


def dataset_summary(db_path: str) -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        count, start, end = conn.execute(
            "SELECT COUNT(*), MIN(data_caso), MAX(data_caso) FROM srag"
        ).fetchone()
    return {"registros": count, "inicio": start, "fim": end}


def _format_metric(metric: dict[str, Any]) -> str:
    value = metric["value"] * 100 if metric["unit"] == "%" else metric["value"]
    suffix = "%" if metric["unit"] == "%" else metric["unit"]
    return (
        f"| {metric['name']} | {value:.2f}{suffix} | "
        f"{metric['numerator']} / {metric['denominator']} | "
        f"{metric['window']} | {metric['note']} |"
    )


def _asset_link(output_path: str, asset_path: str) -> str:
    report_dir = Path(output_path).parent
    try:
        return Path(asset_path).relative_to(report_dir).as_posix()
    except ValueError:
        return Path(asset_path).as_posix()


def write_dry_report(
    metrics: list[dict[str, Any]],
    charts: dict[str, str],
    validation: dict[str, Any],
    audit_path: str,
    db_path: str,
    output_path: str = "outputs/relatorio_srag_seco.md",
) -> str:
    summary = dataset_summary(db_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    daily_chart = _asset_link(output_path, charts["daily"])
    monthly_chart = _asset_link(output_path, charts["monthly"])

    lines = [
        "# Relatorio automatizado de SRAG - versao seca",
        "",
        f"Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Escopo",
        "",
        (
            "Este relatorio cobre os marcos 1 e 2 da PoC: dados tratados em SQLite, "
            "metricas calculadas por SQL/Python, dois graficos e orquestracao em LangGraph. "
            "A busca de noticias em tempo real fica para a proxima etapa."
        ),
        "",
        "## Base de dados",
        "",
        f"- Banco: `{db_path}`",
        f"- Registros agregaveis: {summary['registros']}",
        f"- Periodo coberto: {summary['inicio']} a {summary['fim']}",
        "- Colunas mantidas: data do caso, UF, evolucao, hospitalizacao, UTI, vacinacao gripe/COVID e classificacao.",
        "- Governanca: o fluxo nao expoe linhas individuais nem identificadores diretos.",
        "",
        "## Metricas",
        "",
        "| Metrica | Valor | Numerador / denominador | Janela | Observacao |",
        "|---|---:|---:|---|---|",
    ]
    lines.extend(_format_metric(metric) for metric in metrics)
    lines.extend(
        [
            "",
            "## Graficos",
            "",
            f"![Casos diarios dos ultimos 30 dias]({daily_chart})",
            "",
            f"![Casos mensais dos ultimos 12 meses]({monthly_chart})",
            "",
            "## Leitura tecnica",
            "",
            _technical_reading(metrics),
            "",
            "## Guardrails e auditoria",
            "",
            "- O LLM nao calcula metricas; os numeros saem das tools deterministicas.",
            "- Consultas usam SQL parametrizado nas tools de dados.",
            "- O relatorio documenta denominadores e limitacoes metodologicas.",
            f"- Log estruturado da execucao: `{audit_path}`",
            f"- Validacao automatica: `{validation['status']}` - {validation['message']}",
            "",
            "## Limitacoes metodologicas",
            "",
            "- As janelas temporais sao ancoradas na data mais recente do dataset, nao na data atual.",
            "- UTI e proxy de uso de UTI entre casos hospitalizados, nao ocupacao real de leitos.",
            "- Vacinacao mede registro vacinal entre casos de SRAG com informacao conhecida, nao cobertura vacinal da populacao.",
            "- Esta versao ainda nao cruza noticias em tempo real.",
        ]
    )

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out)


def write_full_report(
    metrics: list[dict[str, Any]],
    charts: dict[str, str],
    news: dict[str, Any],
    validation: dict[str, Any],
    audit_path: str,
    db_path: str,
    output_path: str = "outputs/relatorio_srag_completo.md",
    narrative: dict[str, Any] | None = None,
) -> str:
    summary = dataset_summary(db_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    news_items = news.get("items", [])
    daily_chart = _asset_link(output_path, charts["daily"])
    monthly_chart = _asset_link(output_path, charts["monthly"])

    # Narrativa gerada pelo LLM (com fallback determinístico embutido no analyst).
    narrative = narrative or {}
    exec_text = narrative.get("executive_summary") or _executive_summary(metrics, news)
    interp_metrics = narrative.get("metric_comments") or _technical_reading(metrics)
    interp_news = narrative.get("news_context") or _news_interpretation(news)
    llm_used = narrative.get("llm_used", False)
    llm_model = narrative.get("model")

    lines = [
        "# Relatorio automatizado de SRAG",
        "",
        f"Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "> Aviso: este relatorio e informativo e nao constitui aconselhamento medico, diagnostico, "
        "previsao epidemiologica oficial ou recomendacao clinica. Decisoes de saude devem considerar "
        "fontes oficiais e profissionais qualificados.",
        "",
        "## Resumo executivo",
        "",
        exec_text,
        "",
        "## Base de dados",
        "",
        f"- Banco: `{db_path}`",
        f"- Registros agregaveis: {summary['registros']}",
        f"- Periodo coberto: {summary['inicio']} a {summary['fim']}",
        "- Granularidade publicada: agregada; o relatorio nao expoe registros individuais.",
        "- Observacao temporal: as metricas sao ancoradas na data maxima disponivel no dataset, nao na data atual.",
        "",
        "## Metricas",
        "",
        "| Metrica | Valor | Numerador / denominador | Janela | Observacao |",
        "|---|---:|---:|---|---|",
    ]
    lines.extend(_format_metric(metric) for metric in metrics)
    lines.extend(
        [
            "",
            "## Graficos",
            "",
            f"![Casos diarios dos ultimos 30 dias]({daily_chart})",
            "",
            f"![Casos mensais dos ultimos 12 meses]({monthly_chart})",
            "",
            "## Contexto de noticias",
            "",
            _news_context(news),
            "",
        ]
    )
    if news_items:
        lines.extend(
            [
                "| Fonte | Data | Titulo | Trecho sanitizado |",
                "|---|---|---|---|",
            ]
        )
        for item in news_items:
            lines.append(
                f"| [{item['source']}]({item['url']}) | "
                f"{item.get('published_date') or 'n/d'} | "
                f"{item['title']} | {item['snippet']} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Interpretacao",
            "",
            interp_metrics,
            "",
            interp_news,
            "",
            "## Governanca, guardrails e auditoria",
            "",
            "- LangGraph explicita o fluxo: plano, metricas, graficos, noticias, analise (LLM), validacao e escrita.",
            f"- Narrativa gerada por LLM: `{llm_used}`"
            + (f" (modelo `{llm_model}`)." if llm_used else " (fallback deterministico)."),
            "- O LLM nao calcula metricas; os numeros saem de SQL/Python deterministico. O LLM apenas interpreta.",
            "- Conteudo externo e tratado como nao confiavel: HTML, caracteres de controle e padroes de prompt-injection sao removidos.",
            "- Se a busca de noticias falhar, o relatorio e gerado com fallback e registra a falha.",
            "- A saida inclui disclaimer medico e limitacoes metodologicas.",
            f"- Log estruturado da execucao: `{audit_path}`",
            f"- Validacao automatica: `{validation['status']}` - {validation['message']}",
            "",
            "## Limitacoes metodologicas",
            "",
            "- Taxa de UTI e proxy de uso de UTI entre hospitalizados, nao ocupacao real de leitos.",
            "- Vacinacao mede registro vacinal entre casos de SRAG com informacao conhecida, nao cobertura vacinal da populacao.",
            "- Noticias ajudam a contextualizar, mas nao alteram os calculos epidemiologicos.",
            "- Dados de SRAG podem ter atraso de notificacao, incompletude e revisoes posteriores.",
        ]
    )

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out)


def _technical_reading(metrics: list[dict[str, Any]]) -> str:
    by_name = {m["name"]: m for m in metrics}
    increase = by_name["Taxa de aumento de casos"]
    mortality = by_name["Taxa de mortalidade"]
    direction = "alta" if increase["value"] > 0 else "queda"
    return (
        f"No recorte mais recente, a serie mostra {direction} de "
        f"{abs(increase['value'] * 100):.2f}% em relacao ao periodo anterior. "
        f"A mortalidade calculada sobre desfechos conhecidos e de "
        f"{mortality['value'] * 100:.2f}%, o que deve ser lido junto das ressalvas "
        "sobre atraso de notificacao e preenchimento incompleto dos campos."
    )


def _executive_summary(metrics: list[dict[str, Any]], news: dict[str, Any]) -> str:
    by_name = {m["name"]: m for m in metrics}
    increase = by_name["Taxa de aumento de casos"]
    mortality = by_name["Taxa de mortalidade"]
    news_count = len(news.get("items", []))
    return (
        f"A base tratada indica variacao de {increase['value'] * 100:.2f}% nos casos "
        f"no recorte comparativo mais recente e mortalidade de {mortality['value'] * 100:.2f}% "
        "entre casos com desfecho conhecido. "
        f"O contexto externo foi composto por {news_count} noticia(s) sanitizada(s); "
        "as noticias servem apenas como apoio interpretativo, sem modificar as metricas."
    )


def _news_context(news: dict[str, Any]) -> str:
    status = news.get("status", "fallback")
    provider = news.get("provider", "n/d")
    query = news.get("query", "n/d")
    searched_at = news.get("searched_at_utc", "n/d")
    message = news.get("message", "")
    if status != "ok":
        return (
            f"Busca de noticias em modo fallback. Provedor: `{provider}`. Query: `{query}`. "
            f"Horario UTC: `{searched_at}`. Motivo: {message}."
        )
    return (
        f"Noticias recentes consultadas via `{provider}` com query `{query}` em `{searched_at}` UTC. "
        "Os trechos abaixo foram sanitizados antes de entrar no relatorio."
    )


def _news_interpretation(news: dict[str, Any]) -> str:
    items = news.get("items", [])
    if not items:
        return (
            "Sem noticias utilizaveis nesta execucao. A interpretacao fica restrita aos dados do "
            "SQLite e as limitacoes metodologicas documentadas."
        )
    sources = ", ".join(sorted({item["source"] for item in items}))
    return (
        f"As fontes consultadas ({sources}) podem indicar preocupacoes ou comunicados recentes "
        "sobre SRAG e sindromes respiratorias. Como os dados locais usados nas metricas cobrem o "
        "periodo do arquivo DATASUS carregado, qualquer noticia atual deve ser lida como contexto, "
        "nao como evidencia direta dos indicadores calculados."
    )
