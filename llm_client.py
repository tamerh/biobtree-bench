"""OpenAI-compatible chat client (OpenRouter by default), stdlib only."""

import json
import time
import urllib.error
import urllib.request

import config


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, api_key=None, base_url=None, timeout=180):
        self.api_key = api_key or config.OPENROUTER_API_KEY
        self.base_url = (base_url or config.OPENROUTER_URL).rstrip("/")
        self.timeout = timeout

    def chat(self, model, messages, tools=None, temperature=None, max_tokens=None):
        """One completion. Returns {content, tool_calls, usage, raw_model, latency}."""
        if not self.api_key:
            raise LLMError("OPENROUTER_API_KEY is not set")

        payload = {
            "model": model,
            "messages": messages,
            "temperature": config.TEMPERATURE if temperature is None else temperature,
            "max_tokens": config.MAX_TOKENS if max_tokens is None else max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://sugi.bio",
                "X-Title": "biobtree-benchmark",
            },
            method="POST",
        )

        start = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                body = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            raise LLMError(f"HTTP {e.code}: {detail}") from e
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"request failed: {e}") from e
        latency = time.time() - start

        if "error" in body:
            raise LLMError(str(body["error"]))

        choice = (body.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        usage = body.get("usage", {}) or {}

        return {
            "content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls") or [],
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "raw_model": body.get("model", model),
            "finish_reason": choice.get("finish_reason"),
            "latency": latency,
        }
