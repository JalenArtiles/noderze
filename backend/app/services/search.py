"""Web search providers behind one interface. Results are leads, never facts by themselves."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from ..config import settings
from .llm import llm

log = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    published: str | None = None


def provider_name() -> str:
    p = settings.search_provider
    if p != "auto":
        return p
    if settings.tavily_api_key:
        return "tavily"
    if settings.brave_api_key:
        return "brave"
    if settings.serper_api_key:
        return "serper"
    if llm.available:
        return "anthropic"
    return "none"


def search(query: str, n: int = 8) -> list[SearchResult]:
    p = provider_name()
    try:
        if p == "tavily":
            r = httpx.post("https://api.tavily.com/search", timeout=30,
                           headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
                           json={"api_key": settings.tavily_api_key, "query": query, "max_results": n,
                                 "search_depth": "basic"})
            r.raise_for_status()
            return [SearchResult(x.get("title", ""), x["url"], x.get("content", "")[:500], x.get("published_date"))
                    for x in r.json().get("results", [])]
        if p == "brave":
            r = httpx.get("https://api.search.brave.com/res/v1/web/search", timeout=30, params={"q": query, "count": n},
                          headers={"X-Subscription-Token": settings.brave_api_key, "Accept": "application/json"})
            r.raise_for_status()
            return [SearchResult(x.get("title", ""), x["url"], x.get("description", "")[:500], x.get("age"))
                    for x in r.json().get("web", {}).get("results", [])]
        if p == "serper":
            r = httpx.post("https://google.serper.dev/search", timeout=30, json={"q": query, "num": n},
                           headers={"X-API-KEY": settings.serper_api_key})
            r.raise_for_status()
            return [SearchResult(x.get("title", ""), x["link"], x.get("snippet", "")[:500], x.get("date"))
                    for x in r.json().get("organic", [])]
        if p == "anthropic":
            return [SearchResult(**x) for x in llm.web_search(query)][:n]
    except httpx.HTTPError as e:
        log.warning("search provider %s failed: %s", p, e)
    return []
