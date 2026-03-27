from __future__ import annotations

import html
import re
from urllib.parse import quote, unquote

import requests


class WebResearchClient:
    def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        response = requests.get(
            f"https://duckduckgo.com/html/?q={quote(query)}",
            headers={"User-Agent": "AgenticHub/0.1"},
            timeout=30,
        )
        response.raise_for_status()
        body = response.text
        pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
            re.DOTALL,
        )
        results: list[dict[str, str]] = []
        for match in pattern.finditer(body):
            href = self._clean_link(match.group("href"))
            title = self._clean_html(match.group("title"))
            snippet = self._clean_html(match.group("snippet"))
            if not href:
                continue
            results.append({"title": title, "url": href, "snippet": snippet})
            if len(results) >= max_results:
                break
        return results

    def fetch_page(self, url: str, *, max_chars: int = 8000) -> str:
        response = requests.get(url, headers={"User-Agent": "AgenticHub/0.1"}, timeout=30)
        response.raise_for_status()
        text = response.text
        text = re.sub(r"<script.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]

    def _clean_html(self, value: str) -> str:
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()

    def _clean_link(self, href: str) -> str:
        if href.startswith("//"):
            return f"https:{href}"
        if "uddg=" in href:
            encoded = href.split("uddg=", maxsplit=1)[1]
            encoded = encoded.split("&", maxsplit=1)[0]
            return unquote(encoded)
        return href
