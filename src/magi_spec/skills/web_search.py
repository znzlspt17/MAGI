"""Small web research capability.

The implementation intentionally uses a conservative standard-library fetcher.
It is suitable for lightweight documentation discovery and produces evidence
artifacts even when no search is needed.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any


RESEARCH_TRIGGERS = {
    "latest",
    "current",
    "documentation",
    "docs",
    "sdk",
    "api",
    "security",
    "framework",
    "compatibility",
    "version",
}


class DuckDuckGoResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_link = False
        self._current_href = ""
        self._current_text: list[str] = []
        self.results: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = {key: value or "" for key, value in attrs}
        css_class = attr_map.get("class", "")
        if "result__a" in css_class:
            self._in_link = True
            self._current_href = attr_map.get("href", "")
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            title = " ".join(part.strip() for part in self._current_text if part.strip())
            href = self._decode_href(self._current_href)
            if title and href:
                self.results.append({"title": title, "url": href})
            self._in_link = False

    @staticmethod
    def _decode_href(href: str) -> str:
        parsed = urllib.parse.urlparse(href)
        query = urllib.parse.parse_qs(parsed.query)
        if "uddg" in query:
            return query["uddg"][0]
        return href


def should_research(user_request: str, mode: str) -> bool:
    if mode == "off":
        return False
    if mode == "on":
        return True
    lowered = user_request.lower()
    return any(trigger in lowered for trigger in RESEARCH_TRIGGERS)


def web_search(query: str, *, max_results: int = 5) -> list[dict[str, Any]]:
    encoded = urllib.parse.urlencode({"q": query})
    url = f"https://duckduckgo.com/html/?{encoded}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MAGI-Spec-Engine/0.1"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        html = response.read().decode("utf-8", errors="replace")
    parser = DuckDuckGoResultParser()
    parser.feed(html)
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "title": result["title"],
            "url": result["url"],
            "query": query,
            "retrieved_at": now,
        }
        for result in parser.results[:max_results]
    ]


def summarize_web_research(sources: list[dict[str, Any]], mode: str) -> str:
    lines = ["# 웹 리서치 요약", ""]
    if not sources:
        lines.append(f"- 웹 리서치 모드 `{mode}`에서 사용할 외부 출처가 기록되지 않았습니다.")
        lines.append("- 최종 명세는 사용자 요청과 프로젝트 증거를 우선합니다.")
        return "\n".join(lines) + "\n"
    for index, source in enumerate(sources, start=1):
        lines.append(f"{index}. {source.get('title', 'Untitled')}")
        lines.append(f"   - URL: {source.get('url', '')}")
        lines.append(f"   - Query: {source.get('query', '')}")
    lines.append("")
    lines.append("웹 출처는 현재성 확인을 위한 보조 증거이며, 사용자 요구사항으로 자동 승격되지 않습니다.")
    return "\n".join(lines) + "\n"


def sources_to_json(sources: list[dict[str, Any]]) -> str:
    return json.dumps({"sources": sources}, ensure_ascii=False, indent=2) + "\n"
