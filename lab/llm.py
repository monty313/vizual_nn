"""Minimal LLM client. Works with any OpenAI-compatible endpoint (OpenAI, OpenRouter, LM Studio, Ollama)
or Anthropic. Configure in .env. No key -> the lab uses the offline lesson-memory student.
"""
from __future__ import annotations

import json
import os
import re
import time

import httpx


def config() -> dict:
    prov = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not prov:
        return {"provider": None, "model": None, "ready": False}
    model = os.getenv("LLM_MODEL") or {"openai": "gpt-4o-mini", "anthropic": "claude-sonnet-4-5", "ollama": "llama3.1"}.get(prov, "")
    base = os.getenv("LLM_BASE_URL") or {"openai": "https://api.openai.com/v1", "ollama": "http://localhost:11434/v1",
                                         "anthropic": "https://api.anthropic.com"}.get(prov, "")
    key = os.getenv("LLM_API_KEY", "")
    ready = prov == "ollama" or bool(key)
    return {"provider": prov, "model": model, "base": base, "key": key, "ready": ready}


class LLMError(RuntimeError):
    pass


def chat(system: str, messages: list[dict], max_tokens: int = 1600, temperature: float = 0.2) -> tuple[str, dict]:
    cfg = config()
    if not cfg["ready"]:
        raise LLMError("LLM not configured (set LLM_PROVIDER / LLM_API_KEY / LLM_MODEL in .env)")
    t0 = time.time()
    with httpx.Client(timeout=float(os.getenv("LLM_TIMEOUT", "90"))) as c:
        if cfg["provider"] == "anthropic":
            r = c.post(f"{cfg['base'].rstrip('/')}/v1/messages",
                       headers={"x-api-key": cfg["key"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
                       json={"model": cfg["model"], "max_tokens": max_tokens, "temperature": temperature, "system": system, "messages": messages})
            if r.status_code != 200:
                raise LLMError(f"Anthropic {r.status_code}: {r.text[:300]}")
            js = r.json()
            text = "".join(b.get("text", "") for b in js.get("content", []))
            usage = js.get("usage", {})
        else:
            headers = {"content-type": "application/json"}
            if cfg["key"]:
                headers["authorization"] = f"Bearer {cfg['key']}"
            r = c.post(f"{cfg['base'].rstrip('/')}/chat/completions", headers=headers,
                       json={"model": cfg["model"], "temperature": temperature, "max_tokens": max_tokens,
                             "messages": [{"role": "system", "content": system}] + messages})
            if r.status_code != 200:
                raise LLMError(f"{cfg['provider']} {r.status_code}: {r.text[:300]}")
            js = r.json()
            text = js["choices"][0]["message"].get("content") or ""
            usage = js.get("usage", {})
    return text, {"latency_s": round(time.time() - t0, 2), "usage": usage, "model": cfg["model"], "provider": cfg["provider"]}


def parse_json(text: str) -> dict:
    """Extract the first JSON object from model text (tolerates code fences / prose)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else None
    if raw is None:
        start = text.find("{")
        if start < 0:
            raise LLMError("model did not return JSON")
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    raw = text[start:i + 1]
                    break
    try:
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"bad JSON from model: {e}") from e
