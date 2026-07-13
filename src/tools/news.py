"""News search tool with external-content sanitization.

The agent treats search results as untrusted input. This module removes common
prompt-injection patterns, strips markup/control characters, limits text size,
and returns structured source metadata for auditability.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import unescape
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from dotenv import load_dotenv


DEFAULT_QUERY = (
    '"SRAG" OR "Sindrome Respiratoria Aguda Grave" Brasil noticias recentes '
    "boletim epidemiologico saude"
)
PROMPT_INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior|above) instructions",
    r"ignore as instru(c|ç)(o|õ)es (anteriores|acima)",
    r"ignore as instrucoes (anteriores|acima)",
    r"desconsidere as instru(c|ç)(o|õ)es (anteriores|acima)",
    r"desconsidere as instrucoes (anteriores|acima)",
    r"system prompt",
    r"developer message",
    r"reveal (the )?(prompt|instructions|secrets)",
    r"mostre (o )?(prompt|segredo|sistema)",
    r"execute (this|este)",
    r"tool call",
]


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published_date: str | None
    snippet: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def sanitize_external_text(value: Any, max_chars: int = 800) -> str:
    """Return plain, bounded text from an untrusted external source."""
    if value is None:
        return ""
    text = unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = text.replace("|", "/")
    for pattern in PROMPT_INJECTION_PATTERNS:
        text = re.sub(pattern, "[conteudo externo removido]", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _safe_url(url: Any) -> str:
    text = sanitize_external_text(url, max_chars=500)
    if text.startswith("//"):
        text = "https:" + text
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return text


def _source_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower().removeprefix("www.")


def _unwrap_duckduckgo_url(url: str) -> str:
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if "duckduckgo.com" not in parsed.netloc:
        return url
    uddg = parse_qs(parsed.query).get("uddg", [""])[0]
    return unquote(uddg) if uddg else url


def _normalize_tavily_result(raw: dict[str, Any]) -> NewsItem | None:
    url = _safe_url(raw.get("url"))
    if not url:
        return None
    title = sanitize_external_text(raw.get("title"), max_chars=180) or "Fonte sem titulo"
    snippet = sanitize_external_text(raw.get("content") or raw.get("snippet"), max_chars=700)
    published = sanitize_external_text(raw.get("published_date"), max_chars=40) or None
    return NewsItem(
        title=title,
        url=url,
        source=_source_from_url(url),
        published_date=published,
        snippet=snippet,
    )


def _search_duckduckgo(query: str, max_results: int) -> list[NewsItem]:
    import requests

    ddg_query = "SRAG Sindrome Respiratoria Aguda Grave Brasil boletim epidemiologico noticias"
    response = requests.get(
        "https://html.duckduckgo.com/html/",
        params={"q": ddg_query},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    html = response.text
    pattern = re.compile(
        r'<a rel="nofollow" class="result__a" href="(?P<url>.*?)">(?P<title>.*?)</a>'
        r'(?P<body>.*?)(?=<a rel="nofollow" class="result__a"|</body>)',
        flags=re.IGNORECASE | re.DOTALL,
    )
    items: list[NewsItem] = []
    for match in pattern.finditer(html):
        snippet_match = re.search(r'class="result__snippet".*?>(?P<snippet>.*?)</a>', match.group("body"), re.IGNORECASE | re.DOTALL)
        url = _safe_url(_unwrap_duckduckgo_url(unescape(match.group("url"))))
        if not url:
            continue
        item = NewsItem(
            title=sanitize_external_text(match.group("title"), max_chars=180) or "Fonte sem titulo",
            url=url,
            source=_source_from_url(url),
            published_date=None,
            snippet=sanitize_external_text(snippet_match.group("snippet") if snippet_match else "", max_chars=700),
        )
        if _is_relevant_srag(item):
            items.append(item)
        if len(items) >= max_results:
            break
    return items


def _is_relevant_srag(item: NewsItem) -> bool:
    haystack = f"{item.title} {item.snippet}".lower()
    blocked_sources = {"dadosabertos.saude.gov.br", "zenodo.org"}
    if item.source in blocked_sources:
        return False
    strict_terms = [
        "srag",
        "sindrome respiratoria aguda grave",
        "síndrome respiratória aguda grave",
        "sivep-gripe",
    ]
    news_terms = ["boletim", "infogripe", "casos", "alta", "queda", "alerta", "risco", "aument"]
    return any(term in haystack for term in strict_terms) and any(term in haystack for term in news_terms)


def buscar_noticias_srag(query: str = DEFAULT_QUERY, max_results: int = 5) -> dict[str, Any]:
    """Search recent SRAG news and return sanitized results plus status metadata."""
    load_dotenv()
    sanitized_query = sanitize_external_text(query, max_chars=220) or DEFAULT_QUERY
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    searched_at = datetime.now(timezone.utc).isoformat()

    if not api_key:
        return {
            "status": "fallback",
            "provider": "tavily",
            "query": sanitized_query,
            "searched_at_utc": searched_at,
            "items": [],
            "message": "TAVILY_API_KEY ausente; relatorio gerado sem noticias em tempo real.",
        }

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=sanitized_query,
            search_depth="basic",
            topic="news",
            max_results=max_results,
            include_answer=False,
            include_raw_content=False,
        )
        items = []
        rejected = 0
        for raw in response.get("results", []):
            item = _normalize_tavily_result(raw)
            if item and _is_relevant_srag(item):
                items.append(item.as_dict())
            elif item:
                rejected += 1
        if items:
            status = "ok"
            provider = "tavily"
            message = f"noticias sanitizadas com sucesso; {rejected} resultado(s) rejeitado(s) por baixa relevancia"
        else:
            try:
                ddg_items = _search_duckduckgo(sanitized_query, max_results=max_results)
                items = [item.as_dict() for item in ddg_items]
                status = "ok" if items else "fallback"
                provider = "duckduckgo" if items else "tavily+duckduckgo"
                message = (
                    "fallback DuckDuckGo acionado com resultados sanitizados"
                    if items
                    else f"busca sem resultados relevantes; {rejected} resultado(s) Tavily rejeitado(s)"
                )
            except Exception as ddg_exc:  # noqa: BLE001
                status = "fallback"
                provider = "tavily+duckduckgo"
                message = (
                    f"busca sem resultados relevantes no Tavily e falha no DuckDuckGo: "
                    f"{type(ddg_exc).__name__}"
                )
        return {
            "status": status,
            "provider": provider,
            "query": sanitized_query,
            "searched_at_utc": searched_at,
            "items": items,
            "message": message,
        }
    except Exception as exc:  # noqa: BLE001 - tool fallback must not break report generation
        return {
            "status": "fallback",
            "provider": "tavily",
            "query": sanitized_query,
            "searched_at_utc": searched_at,
            "items": [],
            "message": f"falha na busca de noticias; fallback acionado: {type(exc).__name__}",
        }


if __name__ == "__main__":
    import json

    print(json.dumps(buscar_noticias_srag(), ensure_ascii=False, indent=2))
