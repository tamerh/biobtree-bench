"""Minimal web search/fetch tools for the `web` baseline condition.

Standard library only. Search uses DuckDuckGo's HTML endpoint (no API key);
fetch strips HTML to plain text. Both are bounded so a misbehaving page cannot
blow the model context.

This is a *baseline*: a general-purpose web agent, not a curated database. It
exists to answer "isn't web search enough?" on the same questions as the MCP
condition.
"""

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) biobtree-benchmark/1.0"
SEARCH_URL = "https://lite.duckduckgo.com/lite/"
BING_URL = "https://www.bing.com/search"
MAX_FETCH_BYTES = 2_000_000
DEFAULT_FETCH_CHARS = 20_000

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the public web. Returns up to 10 results as title, URL "
                "and snippet. Use web_fetch to read a result in full."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results (default 10, max 10)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetch a URL and return its main text content (HTML stripped, "
                "truncated). Use after web_search, or on a known database page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Absolute http(s) URL"},
                    "max_chars": {
                        "type": "integer",
                        "description": "Max characters to return (default 20000)",
                    },
                },
                "required": ["url"],
            },
        },
    },
]

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")
_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")


def _strip_html(text):
    text = _SCRIPT.sub(" ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _NL.sub("\n\n", text).strip()


def _unwrap_ddg(href):
    """DuckDuckGo wraps results as //duckduckgo.com/l/?uddg=<encoded>."""
    if "uddg=" in href:
        q = urllib.parse.urlparse(href if href.startswith("http") else "https:" + href)
        target = urllib.parse.parse_qs(q.query).get("uddg")
        if target:
            return target[0]
    if href.startswith("//"):
        return "https:" + href
    return href


class WebError(RuntimeError):
    pass


class WebClient:
    def __init__(self, timeout=30, fetch_chars=DEFAULT_FETCH_CHARS):
        self.timeout = timeout
        self.fetch_chars = fetch_chars

    # -- tool schema -------------------------------------------------------
    def openai_tools(self, names=None):
        if names is None:
            return list(_TOOLS)
        wanted = set(names)
        return [t for t in _TOOLS if t["function"]["name"] in wanted]

    # -- dispatch ----------------------------------------------------------
    def call_tool(self, name, arguments):
        try:
            if name == "web_search":
                return self.search(
                    arguments.get("query", ""),
                    int(arguments.get("max_results") or 10),
                )
            if name == "web_fetch":
                return self.fetch(
                    arguments.get("url", ""),
                    int(arguments.get("max_chars") or self.fetch_chars),
                )
            return f"ERROR: unknown tool {name}"
        except WebError as e:
            return f"ERROR: {e}"

    # -- implementations ---------------------------------------------------
    def _get(self, url, data=None):
        payload = urllib.parse.urlencode(data).encode() if data else None
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
            method="POST" if payload else "GET",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.read(MAX_FETCH_BYTES).decode("utf-8", "replace")

    @staticmethod
    def _parse_ddg_lite(body, max_results):
        results = []
        for m in re.finditer(
            r"(?is)<a[^>]+href=\"([^\"]+)\"[^>]*class='result-link'[^>]*>(.*?)</a>"
            r"(.*?)(?=<a[^>]+class='result-link'|\Z)",
            body,
        ):
            href, title, tail = m.group(1), m.group(2), m.group(3)
            snip = re.search(r"(?is)class='result-snippet'[^>]*>(.*?)</td>", tail)
            results.append(
                {
                    "title": html.unescape(_TAG.sub("", title)).strip(),
                    "url": _unwrap_ddg(html.unescape(href)),
                    "snippet": _strip_html(snip.group(1)) if snip else "",
                }
            )
            if len(results) >= max_results:
                break
        return results

    @staticmethod
    def _parse_bing(body, max_results):
        results = []
        for m in re.finditer(
            r'(?is)<li class="b_algo".*?<h2><a[^>]+href="([^"]+)"[^>]*>(.*?)</a></h2>'
            r"(.*?)(?=<li class=\"b_algo\"|\Z)",
            body,
        ):
            href, title, tail = m.group(1), m.group(2), m.group(3)
            snip = re.search(r"(?is)<p[^>]*>(.*?)</p>", tail)
            results.append(
                {
                    "title": html.unescape(_TAG.sub("", title)).strip(),
                    "url": html.unescape(href),
                    "snippet": _strip_html(snip.group(1)) if snip else "",
                }
            )
            if len(results) >= max_results:
                break
        return results

    def search(self, query, max_results=10):
        query = (query or "").strip()
        if not query:
            return json.dumps({"error": "empty query"})
        max_results = max(1, min(int(max_results or 10), 10))
        errors = []
        for name, url, data, parser in (
            ("duckduckgo", SEARCH_URL, {"q": query}, self._parse_ddg_lite),
            ("bing", BING_URL, {"q": query}, self._parse_bing),
        ):
            try:
                body = self._get(url, data)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name}: {e}")
                continue
            if "anomaly" in body[:4000].lower():
                errors.append(f"{name}: blocked")
                continue
            results = parser(body, max_results)
            if results:
                return json.dumps(
                    {"query": query, "engine": name, "n": len(results), "results": results}
                )
            errors.append(f"{name}: no results")
        return json.dumps({"query": query, "n": 0, "results": [], "errors": errors})

    def fetch(self, url, max_chars=None):
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            return json.dumps({"error": "url must start with http:// or https://"})
        max_chars = max(500, min(int(max_chars or self.fetch_chars), 60_000))
        req = urllib.request.Request(
            url,
            headers={"User-Agent": UA, "Accept": "text/html,text/plain,*/*"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read(MAX_FETCH_BYTES)
                ctype = r.headers.get("Content-Type", "")
                charset = "utf-8"
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": f"fetch failed: {e}", "url": url})

        text = raw.decode(charset, "replace")
        if "html" in ctype.lower() or "<html" in text[:500].lower():
            text = _strip_html(text)
        text = text.strip()
        truncated = len(text) > max_chars
        return json.dumps(
            {
                "url": url,
                "chars": len(text),
                "truncated": truncated,
                "text": text[:max_chars],
            }
        )
