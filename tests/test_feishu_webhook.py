from __future__ import annotations

from pathlib import Path

import pytest

from ai_hot_topics.feishu_webhook import (
    FeishuWebhookError,
    chunk_text_by_lines,
    clean_env_value,
    load_env_file,
    validate_webhook_url,
)


def test_clean_env_value_strips_quotes_and_space() -> None:
    assert clean_env_value("  'abc'  ") == "abc"
    assert clean_env_value('  "abc"  ') == "abc"
    assert clean_env_value("  abc  ") == "abc"


def test_validate_webhook_url_accepts_feishu_bot_url() -> None:
    url = "https://open.feishu.cn/open-apis/bot/v2/hook/abc123"
    assert validate_webhook_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://open.feishu.cn/open-apis/bot/v2/hook/abc",
        "https://example.com/open-apis/bot/v2/hook/abc",
        "https://open.feishu.cn/not-feishu-path",
        "https://open.feishu.cn/open-apis/bot/v2/hook/abc xyz",
    ],
)
def test_validate_webhook_url_rejects_invalid_values(url: str) -> None:
    with pytest.raises(FeishuWebhookError):
        validate_webhook_url(url)


def test_chunk_text_by_lines_splits_and_keeps_content() -> None:
    text = "line1\nline2\nline3\nline4"
    chunks = chunk_text_by_lines(text, max_chars=10)
    assert len(chunks) >= 2
    merged = "\n".join(chunks)
    assert "line1" in merged and "line4" in merged


def test_load_env_file_reads_simple_kv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nFEISHU_WEBHOOK_URL='https://open.feishu.cn/open-apis/bot/v2/hook/abc'\nexport FEISHU_SIGNING_SECRET=secret\n",
        encoding="utf-8",
    )
    data = load_env_file(env_file)
    assert data["FEISHU_WEBHOOK_URL"].startswith("https://open.feishu.cn/")
    assert data["FEISHU_SIGNING_SECRET"] == "secret"
