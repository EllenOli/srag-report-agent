"""LangGraph orchestrator for the complete SRAG report."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from src.agent.analyst import generate_narrative
from src.report.markdown import dataset_summary, write_dry_report, write_full_report
from src.tools.audit import AuditLogger
from src.tools.charts import generate_all_charts
from src.tools.metrics import get_all_metrics
from src.tools.news import fetch_srag_news


class ReportState(TypedDict, total=False):
    db_path: str
    output_path: str
    audit: AuditLogger
    plan: list[str]
    metrics: list[dict[str, Any]]
    charts: dict[str, str]
    news: dict[str, Any]
    narrative: dict[str, Any]
    validation: dict[str, Any]
    output_validation: dict[str, Any]
    report_path: str
    dry_run: bool


def plan_node(state: ReportState) -> ReportState:
    plan = [
        "consultar metricas deterministicas no SQLite",
        "gerar graficos de 30 dias e 12 meses",
        "buscar noticias recentes e sanitizar conteudo externo",
        "interpretar metricas e noticias com o LLM (analise generativa)",
        "validar denominadores e arquivos gerados",
        "escrever relatorio markdown completo",
    ]
    state["audit"].log("decision", "plan", {"plan": plan})
    return {"plan": plan}


def metrics_node(state: ReportState) -> ReportState:
    metrics = get_all_metrics(state["db_path"])
    state["audit"].log("tool_call", "metrics", {"tool": "get_all_metrics", "result": metrics})
    return {"metrics": metrics}


def charts_node(state: ReportState) -> ReportState:
    charts = generate_all_charts(state["db_path"])
    state["audit"].log("tool_call", "charts", {"tool": "generate_all_charts", "result": charts})
    return {"charts": charts}


def news_node(state: ReportState) -> ReportState:
    if state.get("dry_run"):
        news = {
            "status": "skipped",
            "provider": "none",
            "query": "",
            "searched_at_utc": "",
            "items": [],
            "message": "busca de noticias ignorada em dry_run",
        }
        state["audit"].log("skip", "news", news)
        return {"news": news}
    news = fetch_srag_news()
    state["audit"].log("tool_call", "news", {"tool": "fetch_srag_news", "result": news})
    return {"news": news}


def analyze_node(state: ReportState) -> ReportState:
    """Nó GENERATIVO: o LLM interpreta métricas e notícias (com guardrails)."""
    if state.get("dry_run"):
        state["audit"].log("skip", "analyze", {"reason": "dry_run"})
        return {"narrative": {}}
    summary = dataset_summary(state["db_path"])
    narrative = generate_narrative(state["metrics"], state["news"], summary)
    # Não logamos o texto todo, mas registramos o uso do LLM (governança).
    state["audit"].log("llm_call", "analyze", {
        "llm_used": narrative.get("llm_used"),
        "model": narrative.get("model"),
        "note": narrative.get("note", ""),
    })
    return {"narrative": narrative}


def validate_node(state: ReportState) -> ReportState:
    issues: list[str] = []
    for metric in state["metrics"]:
        if metric["denominator"] < 0 or metric["numerator"] < 0:
            issues.append(f"negative count in {metric['name']}")
        if metric["unit"] == "%" and metric["name"] != "Taxa de aumento de casos" and not 0 <= metric["value"] <= 1:
            issues.append(f"rate out of expected range in {metric['name']}")
        if metric["name"] == "Taxa de aumento de casos" and metric["value"] < -1:
            issues.append(f"case increase below -100% in {metric['name']}")
    for label, path in state["charts"].items():
        if not Path(path).exists():
            issues.append(f"missing chart {label}: {path}")
    news = state.get("news", {})
    if not state.get("dry_run") and news.get("status") == "ok" and not news.get("items"):
        issues.append("news status ok without items")
    if not state.get("dry_run"):
        for item in news.get("items", []):
            if not item.get("url", "").startswith(("http://", "https://")):
                issues.append(f"invalid news url: {item.get('url')}")
            if len(item.get("snippet", "")) > 700:
                issues.append(f"news snippet too long: {item.get('url')}")
    validation = {
        "status": "ok" if not issues else "warning",
        "message": "sem inconsistencias detectadas" if not issues else "; ".join(issues),
    }
    state["audit"].log("validation", "validate", validation)
    return {"validation": validation}


def report_node(state: ReportState) -> ReportState:
    if state.get("dry_run"):
        report_path = write_dry_report(
            metrics=state["metrics"],
            charts=state["charts"],
            validation=state["validation"],
            audit_path=str(state["audit"].path),
            db_path=state["db_path"],
            output_path=state["output_path"],
        )
    else:
        report_path = write_full_report(
            metrics=state["metrics"],
            charts=state["charts"],
            news=state["news"],
            validation=state["validation"],
            audit_path=str(state["audit"].path),
            db_path=state["db_path"],
            output_path=state["output_path"],
            narrative=state.get("narrative"),
        )
    output_validation = _validate_report_output(report_path, dry_run=bool(state.get("dry_run")))
    state["audit"].log("artifact", "report", {"report_path": report_path})
    state["audit"].log("output_validation", "report", output_validation)
    return {"report_path": report_path, "output_validation": output_validation}


def _validate_report_output(report_path: str, dry_run: bool = False) -> dict[str, Any]:
    text = Path(report_path).read_text(encoding="utf-8")
    required = [
        "## Metricas",
        "## Graficos",
        "Validacao automatica:",
        "Log estruturado da execucao:",
        "Taxa de aumento de casos",
        "Taxa de mortalidade",
        "Taxa de ocupacao de UTI",
        "Taxa de vacinacao",  # aceita variante gripe/COVID conforme o dataset
        "casos_diarios_30d.png",
        "casos_mensais_12m.png",
    ]
    if not dry_run:
        required.extend(
            [
                "nao constitui aconselhamento medico",
                "## Contexto de noticias",
                "## Governanca, guardrails e auditoria",
                "Conteudo externo e tratado como nao confiavel",
            ]
        )
    missing = [item for item in required if item not in text]
    return {
        "status": "ok" if not missing else "warning",
        "message": "relatorio contem secoes obrigatorias" if not missing else "faltando: " + ", ".join(missing),
    }


def build_graph():
    graph = StateGraph(ReportState)
    graph.add_node("plan", plan_node)
    graph.add_node("metrics", metrics_node)
    graph.add_node("charts", charts_node)
    graph.add_node("news", news_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("validate", validate_node)
    graph.add_node("report", report_node)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "metrics")
    graph.add_edge("metrics", "charts")
    graph.add_edge("charts", "news")
    graph.add_edge("news", "analyze")
    graph.add_edge("analyze", "validate")
    graph.add_edge("validate", "report")
    graph.add_edge("report", END)
    return graph.compile()


def run(
    db_path: str = "data/srag.db",
    output_path: str = "outputs/relatorio_srag_completo.md",
    dry_run: bool = False,
) -> ReportState:
    audit = AuditLogger()
    audit.log("start", "orchestrator", {"db_path": db_path, "output_path": output_path, "dry_run": dry_run})
    app = build_graph()
    final_state = app.invoke(
        {"db_path": db_path, "output_path": output_path, "audit": audit, "dry_run": dry_run}
    )
    audit.log("finish", "orchestrator", {"report_path": final_state.get("report_path")})
    return final_state


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/srag.db")
    parser.add_argument("--out", default="outputs/relatorio_srag_completo.md")
    parser.add_argument("--dry", action="store_true", help="Gera a versao seca, sem noticias.")
    args = parser.parse_args()
    state = run(db_path=args.db, output_path=args.out, dry_run=args.dry)
    print(state["report_path"])
