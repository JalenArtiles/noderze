"""Thin wrapper over the Anthropic Messages API.

- structured(): forces a tool call whose input_schema is the desired JSON shape, so output is parsed
  JSON rather than free text.
- web_search(): uses the server-side web search tool and returns result URLs and titles.
Everything returns None / [] when no API key is configured; callers fall back to deterministic logic.
"""
from __future__ import annotations

import logging

from ..config import settings

log = logging.getLogger(__name__)

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None


class LLM:
    def __init__(self) -> None:
        self.client = None
        if settings.anthropic_api_key and anthropic is not None:
            self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    @property
    def available(self) -> bool:
        return self.client is not None

    def structured(self, system: str, prompt: str, schema: dict, *, fast: bool = False,
                   max_tokens: int = 3000) -> dict | None:
        if not self.client:
            return None
        try:
            resp = self.client.messages.create(
                model=settings.llm_fast_model if fast else settings.llm_model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": prompt}],
                tools=[{"name": "record", "description": "Record the structured result.", "input_schema": schema}],
                tool_choice={"type": "tool", "name": "record"})
        except Exception as e:  # network, auth, rate limit
            log.warning("LLM structured call failed: %s", e)
            return None
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                return dict(block.input)
        return None

    def text(self, system: str, prompt: str, *, fast: bool = False, max_tokens: int = 1500) -> str | None:
        if not self.client:
            return None
        try:
            resp = self.client.messages.create(
                model=settings.llm_fast_model if fast else settings.llm_model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": prompt}])
        except Exception as e:
            log.warning("LLM text call failed: %s", e)
            return None
        return "".join(getattr(b, "text", "") for b in resp.content).strip() or None

    def web_search(self, query: str, max_uses: int = 2) -> list[dict]:
        if not self.client:
            return []
        try:
            resp = self.client.messages.create(
                model=settings.llm_model, max_tokens=1200,
                tools=[{"type": settings.anthropic_web_search_tool, "name": "web_search", "max_uses": max_uses}],
                messages=[{"role": "user", "content": f"Search the web for: {query}\nThen briefly list what you found."}])
        except Exception as e:
            log.warning("Anthropic web search failed: %s", e)
            return []
        results: dict[str, dict] = {}
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "web_search_tool_result" and isinstance(getattr(block, "content", None), list):
                for r in block.content:
                    url = getattr(r, "url", None)
                    if url and url not in results:
                        results[url] = {"title": getattr(r, "title", "") or "", "url": url, "snippet": "",
                                        "published": getattr(r, "page_age", None)}
            if btype == "text":
                for c in getattr(block, "citations", None) or []:
                    url = getattr(c, "url", None)
                    if url in results and not results[url]["snippet"]:
                        results[url]["snippet"] = (getattr(c, "cited_text", "") or "")[:500]
        return list(results.values())


llm = LLM()
