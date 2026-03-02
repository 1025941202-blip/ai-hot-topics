#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ai_hot_topics.feishu_webhook import FeishuWebhookError, chunk_text_by_lines, send_text_message  # noqa: E402


DEFAULT_OUTBOX_DIR = PROJECT_DIR / "outbox"
DEFAULT_FILE_PREFIX = "ai-hotspot-"


def pick_report_file(outbox_dir: Path, explicit_file: str | None) -> Path:
    if explicit_file:
        p = Path(explicit_file).expanduser()
        if not p.exists():
            raise FeishuWebhookError(f"report file not found: {p}")
        return p

    outbox_dir.mkdir(parents=True, exist_ok=True)
    candidates = sorted(
        [p for p in outbox_dir.iterdir() if p.is_file() and p.name.startswith(DEFAULT_FILE_PREFIX)],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FeishuWebhookError(f"no report file found in {outbox_dir}")
    return candidates[0]


def build_messages(report_path: Path, *, keyword: str, max_chars: int) -> list[str]:
    body = report_path.read_text(encoding="utf-8").strip()
    if not body:
        raise FeishuWebhookError(f"report file is empty: {report_path}")

    chunks = chunk_text_by_lines(body, max_chars=max_chars)
    if len(chunks) == 1:
        return [chunks[0]]

    total = len(chunks)
    messages: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        title = f"{keyword}（{idx}/{total}）" if keyword else f"({idx}/{total})"
        messages.append(f"{title}\n{chunk}")
    return messages


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Send latest outbox report to Feishu webhook")
    p.add_argument("--file", help="Explicit report file path")
    p.add_argument("--outbox-dir", default=str(DEFAULT_OUTBOX_DIR))
    p.add_argument("--keyword", default="AI热点")
    p.add_argument("--max-chars", type=int, default=2600)
    p.add_argument("--timeout", type=int, default=15)
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--webhook-env", default="FEISHU_WEBHOOK_URL")
    p.add_argument("--secret-env", default="FEISHU_SIGNING_SECRET")
    p.add_argument("--env-file", default=str(PROJECT_DIR / ".env"))
    p.add_argument("--skip-dns-precheck", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = pick_report_file(Path(args.outbox_dir).expanduser(), args.file)
        messages = build_messages(report, keyword=args.keyword, max_chars=args.max_chars)
        for msg in messages:
            send_text_message(
                msg,
                keyword=args.keyword,
                webhook_env=args.webhook_env,
                secret_env=args.secret_env,
                env_file=args.env_file,
                timeout=args.timeout,
                retries=args.retries,
                dns_precheck=not args.skip_dns_precheck,
            )
        print(f"sent ok ({len(messages)} message(s)) from {report}")
        return 0
    except FeishuWebhookError as exc:
        print(f"send failed: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"send failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
