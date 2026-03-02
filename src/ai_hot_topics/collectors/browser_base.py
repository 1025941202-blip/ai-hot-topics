from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from ..models import RawItem
from ..utils import now_utc, stable_hash
from .base import CollectorResult


def _load_playwright():
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return None
    return sync_playwright


class BrowserSearchCollectorBase:
    platform = "browser"

    def __init__(self, env: dict[str, str], source_id: str):
        self.env = env
        self.source_id = source_id

    def search_url(self, keyword: str) -> str:
        raise NotImplementedError

    def _generic_extract(self, page, keyword: str, max_per_keyword: int) -> list[RawItem]:
        anchors = page.evaluate(
            """
            (limit) => {
              const list = [];
              for (const a of Array.from(document.querySelectorAll('a[href]'))) {
                const text = (a.innerText || a.textContent || '').trim();
                const href = a.href || '';
                if (!text || !href) continue;
                if (text.length < 6) continue;
                list.push({ text, href });
                if (list.length >= limit * 3) break;
              }
              return list;
            }
            """,
            max_per_keyword,
        )
        items: list[RawItem] = []
        now = now_utc()
        for entry in anchors:
            href = str(entry.get("href") or "")
            text = str(entry.get("text") or "").strip()
            if not href or not text:
                continue
            if keyword.lower() not in text.lower() and "ai" not in text.lower() and "人工智能" not in text:
                continue
            items.append(
                RawItem(
                    platform=self.platform,
                    source_id=self.source_id,
                    query=keyword,
                    platform_post_id=stable_hash(f"{self.platform}|{href}", 20),
                    url=href,
                    title=text[:200],
                    text=text[:500],
                    author="",
                    published_at=None,
                    metrics={},
                    language="zh" if self.platform in {"douyin", "xiaohongshu"} else "en",
                    raw_payload={"source": "generic_anchor_extract"},
                    collected_at=now,
                )
            )
            if len(items) >= max_per_keyword:
                break
        return items

    def _extract_page_items(self, page, keyword: str, max_per_keyword: int) -> list[RawItem]:
        return self._generic_extract(page, keyword, max_per_keyword)

    def collect(
        self,
        keywords: list[str],
        since_ts: datetime,
        max_per_keyword: int = 5,
    ) -> CollectorResult:
        sync_playwright = _load_playwright()
        if sync_playwright is None:
            return CollectorResult(
                platform=self.platform,
                warning="Playwright 未安装，浏览器平台采集已跳过（可安装 optional dependency browser）",
            )

        user_data_dir = self.env.get("PLAYWRIGHT_USER_DATA_DIR", "").strip()
        if not user_data_dir:
            return CollectorResult(
                platform=self.platform,
                warning="未设置 PLAYWRIGHT_USER_DATA_DIR，浏览器登录态采集已跳过",
            )

        headless = self.env.get("BROWSER_HEADLESS", "false").lower() == "true"
        channel = self.env.get("PLAYWRIGHT_BROWSER_CHANNEL") or None
        all_items: list[RawItem] = []
        try:
            with sync_playwright() as p:
                browser_type = p.chromium
                ctx = browser_type.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=headless,
                    channel=channel,
                )
                page = ctx.new_page()
                for kw in keywords:
                    url = self.search_url(kw)
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)
                    all_items.extend(self._extract_page_items(page, kw, max_per_keyword=max_per_keyword))
                ctx.close()
        except Exception as exc:
            return CollectorResult(platform=self.platform, items=all_items, error=str(exc))

        return CollectorResult(platform=self.platform, items=all_items, metadata={"since_ts": since_ts.isoformat()})

    @staticmethod
    def q(value: str) -> str:
        return quote(value, safe="")
