from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import socket
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_WEBHOOK_ENV = "FEISHU_WEBHOOK_URL"
DEFAULT_SECRET_ENV = "FEISHU_SIGNING_SECRET"


class FeishuWebhookError(RuntimeError):
    pass


def clean_env_value(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = value.strip()
    if cleaned[:1] in ("'", '"') and cleaned[-1:] == cleaned[:1]:
        cleaned = cleaned[1:-1]
    return cleaned.strip()


def load_env_file(path: str | Path) -> dict[str, str]:
    env_map: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return env_map
    for raw_line in p.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        env_map[key] = clean_env_value(value)
    return env_map


def get_env(name: str, env_file: str | Path | None = None) -> str:
    value = clean_env_value(os.getenv(name))
    if value:
        return value
    if env_file:
        return clean_env_value(load_env_file(env_file).get(name))
    return ""


def validate_webhook_url(webhook_url: str) -> str:
    if not webhook_url:
        raise FeishuWebhookError(f"missing env {DEFAULT_WEBHOOK_ENV}")
    if any(ch.isspace() for ch in webhook_url):
        raise FeishuWebhookError("webhook URL contains whitespace")

    parsed = urlparse(webhook_url)
    if parsed.scheme != "https":
        raise FeishuWebhookError("webhook URL must use https")
    if parsed.hostname != "open.feishu.cn":
        raise FeishuWebhookError(
            f"unexpected webhook host: {parsed.hostname!r} (expected 'open.feishu.cn')"
        )
    if not parsed.path.startswith("/open-apis/bot/v2/hook/"):
        raise FeishuWebhookError("invalid Feishu webhook path")
    return webhook_url


def dns_precheck_webhook(webhook_url: str) -> None:
    host = urlparse(webhook_url).hostname or "open.feishu.cn"
    try:
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise FeishuWebhookError(f"dns precheck failed for {host}: {exc}") from exc


def ensure_keyword(text: str, keyword: str | None) -> str:
    if not keyword:
        return text
    if keyword in text:
        return text
    return f"{keyword}\n{text}" if text else keyword


def chunk_text_by_lines(text: str, max_chars: int) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        line_len = len(line) + 1
        if current and current_len + line_len > max_chars:
            chunks.append("\n".join(current).strip())
            current = []
            current_len = 0

        if line_len > max_chars:
            if current:
                chunks.append("\n".join(current).strip())
                current = []
                current_len = 0
            start = 0
            while start < len(line):
                chunks.append(line[start : start + max_chars])
                start += max_chars
            continue

        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current).strip())

    return [chunk for chunk in chunks if chunk]


def build_webhook_payload(text: str, signing_secret: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "msg_type": "text",
        "content": {"text": text},
    }
    if signing_secret:
        timestamp = str(int(time.time()))
        sign_bytes = f"{timestamp}\n{signing_secret}".encode("utf-8")
        sign = base64.b64encode(
            hmac.new(sign_bytes, digestmod=hashlib.sha256).digest()
        ).decode("utf-8")
        payload["timestamp"] = timestamp
        payload["sign"] = sign
    return payload


def post_webhook_json(
    webhook_url: str,
    payload: dict[str, Any],
    *,
    timeout: int = 15,
    retries: int = 2,
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            code = data.get("code", data.get("StatusCode"))
            if code not in (0, "0"):
                raise FeishuWebhookError(f"feishu api error: {raw}")
            return
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = FeishuWebhookError(f"http {exc.code}: {detail}")
        except (URLError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
        if attempt < retries:
            time.sleep(attempt + 1)

    raise FeishuWebhookError(f"request failed: {last_error}")


def send_text_message(
    text: str,
    *,
    keyword: str | None = "AI热点",
    webhook_env: str = DEFAULT_WEBHOOK_ENV,
    secret_env: str = DEFAULT_SECRET_ENV,
    env_file: str | Path | None = None,
    timeout: int = 15,
    retries: int = 2,
    dns_precheck: bool = True,
) -> None:
    if not text.strip():
        raise FeishuWebhookError("message text is empty")

    webhook_url = validate_webhook_url(get_env(webhook_env, env_file=env_file))
    signing_secret = get_env(secret_env, env_file=env_file)
    if dns_precheck:
        dns_precheck_webhook(webhook_url)
    text = ensure_keyword(text.strip(), keyword)
    payload = build_webhook_payload(text, signing_secret=signing_secret)
    post_webhook_json(webhook_url, payload, timeout=timeout, retries=max(0, retries))
