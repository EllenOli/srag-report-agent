"""Gera o diagrama conceitual da arquitetura da solucao (PDF + PNG).

    python docs/architecture_diagram.py

Mostra o Agente Principal (Orquestrador LangGraph), as Tools, o LLM, o banco
de dados e as fontes de noticias, conforme exigido na entrega.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

NAVY = "#1F3A5F"
BLUE = "#2F6DB0"
LIGHT = "#E9F0F8"
GREEN = "#177A5E"
AMBER = "#9A5B00"
GREY = "#555555"

OUT = Path("docs")


def box(ax, x, y, w, h, text, fc=LIGHT, ec=BLUE, tc=NAVY, fs=9, bold=False):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06",
        linewidth=1.5, edgecolor=ec, facecolor=fc, zorder=2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, color=tc, weight="bold" if bold else "normal", zorder=3)


def arrow(ax, xy1, xy2, color=GREY, style="-|>"):
    ax.add_patch(FancyArrowPatch(
        xy1, xy2, arrowstyle=style, mutation_scale=13,
        color=color, linewidth=1.3, zorder=1,
        connectionstyle="arc3,rad=0"))


def build():
    fig, ax = plt.subplots(figsize=(12, 7.6))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 9)
    ax.axis("off")

    ax.text(6, 8.7, "SRAG Report Generation Agent — Architecture",
            ha="center", fontsize=14, weight="bold", color=NAVY)
    ax.text(6, 8.3, "Indicium HealthCare — PoC", ha="center", fontsize=9, color=GREY)

    # Entry point
    box(ax, 0.4, 7.2, 2.3, 0.8, 'Request\n"Generate report"', fc="#fff", ec=GREY, tc=GREY)

    # Orchestrator (container)
    ax.add_patch(FancyBboxPatch(
        (0.4, 3.5), 11.2, 3.2, boxstyle="round,pad=0.02,rounding_size=0.08",
        linewidth=2, edgecolor=NAVY, facecolor="#F4F7FB", zorder=0))
    ax.text(6, 6.45, "MAIN AGENT — Orchestrator (LangGraph)",
            ha="center", fontsize=10.5, weight="bold", color=NAVY)

    nodes = ["plan", "metrics", "charts", "news", "analyze\n(LLM)", "validate", "report"]
    nx = 0.8
    nw, gap = 1.35, 0.18
    centers = []
    for i, n in enumerate(nodes):
        fc = "#DDEBFF" if n.startswith("analyze") else LIGHT
        ec = BLUE if not n.startswith("analyze") else NAVY
        box(ax, nx, 4.6, nw, 1.1, n, fc=fc, ec=ec, fs=9, bold=n.startswith("analyze"))
        centers.append((nx + nw / 2, 4.6))
        if i > 0:
            arrow(ax, (prev, 5.15), (nx, 5.15), color=NAVY)
        prev = nx + nw
        nx += nw + gap

    arrow(ax, (1.5, 7.2), (1.475, 5.7), color=GREY)  # entrada -> plan

    # External resources (bottom)
    box(ax, 1.6, 1.9, 2.0, 0.9, "SQLite database\n(cleaned DATASUS\ndata)", fc="#EAF6F0", ec=GREEN, tc=GREEN)
    box(ax, 4.1, 1.9, 2.0, 0.9, "Matplotlib\n(PNG charts)", fc="#EAF6F0", ec=GREEN, tc=GREEN)
    box(ax, 6.6, 1.9, 2.3, 0.9, "Real-time news\nDuckDuckGo (primary)\n→ Tavily (optional)", fc="#FDF3E6", ec=AMBER, tc=AMBER)
    box(ax, 9.2, 1.9, 2.0, 0.9, "OpenAI LLM\n(gpt-4o-mini)", fc="#DDEBFF", ec=NAVY, tc=NAVY)

    # ligacoes nodes -> recursos
    arrow(ax, (centers[1][0], 4.6), (2.6, 2.8), color=GREEN)   # metrics -> sqlite
    arrow(ax, (centers[2][0], 4.6), (5.1, 2.8), color=GREEN)   # charts -> matplotlib
    arrow(ax, (centers[3][0], 4.6), (7.7, 2.8), color=AMBER)   # news -> tavily
    arrow(ax, (centers[4][0], 4.6), (10.2, 2.8), color=NAVY)   # analyze -> llm

    # Outputs (bottom)
    box(ax, 0.4, 0.3, 3.5, 0.9, "Final report (Markdown/PDF)\nmetrics + charts + context", fc="#fff", ec=BLUE)
    box(ax, 4.2, 0.3, 3.3, 0.9, "Guardrails\nLLM doesn't compute · sanitization\n· medical disclaimer", fc="#fff", ec=AMBER, tc=AMBER)
    box(ax, 7.8, 0.3, 3.4, 0.9, "Audit log (JSONL)\ndecisions, tool calls, LLM", fc="#fff", ec=GREY, tc=GREY)

    arrow(ax, (centers[6][0], 4.6), (2.1, 1.2), color=BLUE)    # report -> relatorio
    arrow(ax, (6.0, 3.5), (6.0, 1.25), color=AMBER, style="-")  # guardrails aplicados no fluxo
    arrow(ax, (10.5, 3.5), (9.5, 1.2), color=GREY, style="-")   # auditoria registra fluxo

    OUT.mkdir(exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT / "arquitetura.pdf", bbox_inches="tight")
    fig.savefig(OUT / "arquitetura.png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    print("Gerado: docs/arquitetura.pdf e docs/arquitetura.png")


if __name__ == "__main__":
    build()
