from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OpenAICompatibleProvider:
    name = "openai-compatible"

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": "你是结构化输出助手，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
        }
        data = json.dumps(body).encode("utf-8")
        req = Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "ai-hot-topics/0.1",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=30) as resp:  # noqa: S310
                payload = json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc
        choices = payload.get("choices", []) or []
        if not choices:
            raise RuntimeError("LLM response missing choices")
        message = choices[0].get("message", {}) or {}
        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError("LLM response missing content")
        return content

