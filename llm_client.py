"""OpenAI-compatible chat client (OpenRouter or OpenCode Go; stdlib only)."""

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

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://sugi.bio",
            "X-Title": "biobtree-benchmark",
            "User-Agent": "biobtree-benchmark/1.0",
        }
        # Required by the OpenCode Go inference endpoint; ignored elsewhere.
        if config.OPENCODE_SESSION:
            headers["x-opencode-session"] = config.OPENCODE_SESSION

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        start = time.time()
        body = None
        last_err = None
        attempts = 6
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body = json.loads(r.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                last_err = LLMError(f"HTTP {e.code}: {detail}")
                retryable = e.code in (429, 500, 502, 503, 504)
                # Capacity errors ("overloaded", "prefill_cap_refused") need
                # longer waits than a normal rate limit.
                capacity = any(
                    k in detail.lower()
                    for k in ("overloaded", "capacity", "prefill_cap")
                )
                if retryable and attempt < attempts - 1:
                    wait = min(2 ** attempt, 30) * (3 if capacity else 1)
                    time.sleep(min(wait, 90))
                    continue
                raise last_err from e
            except Exception as e:  # noqa: BLE001
                last_err = LLMError(f"request failed: {e}")
                if attempt < attempts - 1:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise last_err from e
        if body is None:
            raise last_err or LLMError("request failed")
        latency = time.time() - start

        if "error" in body:
            raise LLMError(str(body["error"]))

        choice = (body.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        usage = body.get("usage", {}) or {}
        oc = usage.get("opencode") or {}
        cost = usage.get("cost")
        if not cost:
            cost = oc.get("list_cost", 0)

        return {
            "content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls") or [],
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "cost_usd": float(cost or 0),
                "allowance_usd": float(oc.get("allowance") or 0),
            },
            "raw_model": body.get("model", model),
            "finish_reason": choice.get("finish_reason"),
            "latency": latency,
        }
