from __future__ import annotations

import html
import re
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


class WebResearchClient:
    USER_AGENT = "AgenticHub/1.0 (+https://github.com/)"

    @classmethod
    def fetch_page(cls, url: str, *, timeout_seconds: int = 15) -> dict:
        request = Request(url, headers={"User-Agent": cls.USER_AGENT})
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            body = response.read().decode("utf-8", errors="replace")
        cleaned = re.sub(r"<script.*?</script>", " ", body, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"<style.*?</style>", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = html.unescape(re.sub(r"\s+", " ", cleaned)).strip()
        return {"url": url, "content": cleaned[:8000]}

    @classmethod
    def search_web(cls, query: str, *, max_results: int = 5, timeout_seconds: int = 15) -> dict:
        search_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        request = Request(search_url, headers={"User-Agent": cls.USER_AGENT})
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            body = response.read().decode("utf-8", errors="replace")
        matches = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, flags=re.IGNORECASE | re.DOTALL)
        results = []
        for href, raw_title in matches[:max_results]:
            title = html.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
            results.append({"title": title, "url": href})
        return {"query": query, "results": results}
