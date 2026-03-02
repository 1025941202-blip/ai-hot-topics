from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

from ..models import RawItem
from ..utils import now_utc
from .base import CollectorResult
from .browser_base import _load_playwright


class HuitunCollector:
    platform = "huitun"

    def __init__(self, env: dict[str, str], source_id: str):
        self.env = env
        self.source_id = source_id

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
                warning="Playwright 未安装，灰豚采集已跳过（可安装 optional dependency browser）",
            )

        user_data_dir = self.env.get("PLAYWRIGHT_USER_DATA_DIR", "").strip()
        if not user_data_dir:
            return CollectorResult(
                platform=self.platform,
                warning="未设置 PLAYWRIGHT_USER_DATA_DIR，灰豚采集已跳过",
            )

        base_url = (self.env.get("HUITUN_BASE_URL") or "https://dy.huitun.com/app/#/dashboard").strip()
        api_base = (self.env.get("HUITUN_API_BASE") or "https://dyapi.huitun.com").strip().rstrip("/")
        try:
            timeout_ms = int((self.env.get("HUITUN_TIMEOUT_MS") or "30000").strip())
        except ValueError:
            timeout_ms = 30000
        per_feed_limit = max(10, int(max_per_keyword) * 6)

        headless = self.env.get("BROWSER_HEADLESS", "false").lower() == "true"
        channel = self.env.get("PLAYWRIGHT_BROWSER_CHANNEL") or None

        try:
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=headless,
                    channel=channel,
                )
                page = ctx.new_page()
                page.goto(base_url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(2500)

                api_url = f"{api_base}/user/webHomePage?_t={int(time.time() * 1000)}"
                resp = page.request.get(api_url, timeout=timeout_ms)
                if resp.status != 200:
                    ctx.close()
                    return CollectorResult(
                        platform=self.platform,
                        error=f"灰豚接口请求失败 status={resp.status}",
                    )

                payload = resp.json()
                code = int(payload.get("code", -1))
                if code != 0:
                    message = str(payload.get("message") or "unknown_error")
                    ctx.close()
                    return CollectorResult(
                        platform=self.platform,
                        warning=f"灰豚接口返回异常 code={code} message={message}",
                    )

                data = payload.get("data")
                if not isinstance(data, dict):
                    ctx.close()
                    return CollectorResult(
                        platform=self.platform,
                        warning="灰豚接口未返回 data 字段",
                    )

                items = self._build_items_from_home_data(
                    data=data,
                    keywords=keywords,
                    per_feed_limit=per_feed_limit,
                )
                ctx.close()
        except Exception as exc:
            return CollectorResult(platform=self.platform, error=f"灰豚采集失败: {exc}")

        return CollectorResult(
            platform=self.platform,
            items=items,
            metadata={
                "since_ts": since_ts.isoformat(),
                "api_source": "user/webHomePage",
                "raw_total": len(items),
            },
        )

    def _build_items_from_home_data(
        self,
        *,
        data: dict[str, Any],
        keywords: list[str],
        per_feed_limit: int,
    ) -> list[RawItem]:
        rows: list[RawItem] = []
        collected_at = now_utc()
        seen_ids: set[str] = set()

        def push(item: RawItem | None) -> None:
            if item is None:
                return
            if item.platform_post_id in seen_ids:
                return
            seen_ids.add(item.platform_post_id)
            rows.append(item)

        aweme_rows = data.get("awemeList")
        if isinstance(aweme_rows, list):
            for row in aweme_rows[:per_feed_limit]:
                push(self._aweme_to_item(row, keywords=keywords, collected_at=collected_at))

        take_rows = data.get("curTakeRank")
        if isinstance(take_rows, list):
            for row in take_rows[:per_feed_limit]:
                push(self._take_rank_to_item(row, keywords=keywords, collected_at=collected_at))

        live_rows = data.get("liveUserRank")
        if isinstance(live_rows, list):
            for row in live_rows[:per_feed_limit]:
                push(self._live_user_to_item(row, keywords=keywords, collected_at=collected_at))

        return rows

    def _aweme_to_item(
        self,
        row: Any,
        *,
        keywords: list[str],
        collected_at: datetime,
    ) -> RawItem | None:
        if not isinstance(row, dict):
            return None
        aweme_id = str(row.get("awemeId") or row.get("mid") or "").strip()
        if not aweme_id:
            return None

        title = str(row.get("desc") or "").strip()
        author = str(row.get("nickname") or "").strip()
        text = " ".join(
            x
            for x in [
                title,
                author,
                str(row.get("tag1") or "").strip(),
                str(row.get("tag2") or "").strip(),
                str(row.get("tag3") or "").strip(),
                str(row.get("hotWords") or "").strip(),
            ]
            if x
        ).strip()
        query = self._match_keyword(text, keywords)
        if not query:
            return None

        url = str(row.get("playUri") or "").strip()
        if not url:
            url = f"https://www.douyin.com/video/{aweme_id}"
        published_at = self._parse_datetime(row.get("publishTime")) or self._parse_datetime(
            row.get("updateTime")
        )

        return RawItem(
            platform=self.platform,
            source_id=self.source_id,
            query=query,
            platform_post_id=f"aweme-{aweme_id}",
            url=url,
            title=(title or f"灰豚短视频 {aweme_id}")[:200],
            text=text[:1000],
            author=author[:100],
            published_at=published_at,
            metrics={
                "views": self._to_int(row.get("viewCount")),
                "likes": self._to_int(row.get("diggCount")),
                "favorites": self._to_int(row.get("colCount") or row.get("collect")),
                "comments": self._to_int(row.get("commentCount")),
                "shares": self._to_int(row.get("shareCount")),
            },
            language="zh",
            raw_payload={
                "source": "huitun_webHomePage_awemeList",
                "raw": row,
                "author_fans": self._to_int(row.get("fans")),
                "score": self._to_float(row.get("score")),
                "duration": str(row.get("duration") or ""),
            },
            collected_at=collected_at,
        )

    def _take_rank_to_item(
        self,
        row: Any,
        *,
        keywords: list[str],
        collected_at: datetime,
    ) -> RawItem | None:
        if not isinstance(row, dict):
            return None
        room_id = str(row.get("roomId") or "").strip()
        uid = str(row.get("uid") or "").strip()
        post_id = room_id or uid
        if not post_id:
            return None

        title = str(row.get("title") or "").strip()
        author = str(row.get("nickName") or "").strip()
        category = str(row.get("category") or "").strip()
        text = " ".join(x for x in [title, author, category] if x).strip()
        query = self._match_keyword(text, keywords)
        if not query:
            return None

        url = ""
        if room_id:
            url = f"https://live.douyin.com/{room_id}"
        elif uid:
            url = f"https://www.douyin.com/user/{uid}"

        published_at = self._parse_datetime(row.get("startTime"))
        return RawItem(
            platform=self.platform,
            source_id=self.source_id,
            query=query,
            platform_post_id=f"live-{post_id}",
            url=url,
            title=(title or f"灰豚直播 {post_id}")[:200],
            text=text[:1000],
            author=author[:100],
            published_at=published_at,
            metrics={
                "views": self._to_int(row.get("watchNum") or row.get("maxUserNum")),
                "likes": 0,
                "favorites": 0,
                "comments": 0,
                "shares": 0,
            },
            language="zh",
            raw_payload={
                "source": "huitun_webHomePage_curTakeRank",
                "raw": row,
                "author_fans": self._to_int(row.get("followerCount")),
                "gmv": self._to_int(row.get("gmv")),
                "sales": self._to_int(row.get("sales")),
                "category": category,
            },
            collected_at=collected_at,
        )

    def _live_user_to_item(
        self,
        row: Any,
        *,
        keywords: list[str],
        collected_at: datetime,
    ) -> RawItem | None:
        if not isinstance(row, dict):
            return None
        uid = str(row.get("uid") or "").strip()
        room_id = str(row.get("roomId") or "").strip()
        post_id = room_id or uid
        if not post_id:
            return None

        author = str(row.get("nickName") or "").strip()
        category = str(row.get("superCategory") or "").strip()
        title = f"{author} {category}".strip()
        query = self._match_keyword(title, keywords)
        if not query:
            return None

        url = str(row.get("userLink") or "").strip()
        if not url and room_id:
            url = f"https://live.douyin.com/{room_id}"

        return RawItem(
            platform=self.platform,
            source_id=self.source_id,
            query=query,
            platform_post_id=f"live-user-{post_id}",
            url=url,
            title=title[:200],
            text=title[:1000],
            author=author[:100],
            published_at=None,
            metrics={
                "views": self._to_int(row.get("watchTimes") or row.get("maxUserNum")),
                "likes": 0,
                "favorites": 0,
                "comments": 0,
                "shares": 0,
            },
            language="zh",
            raw_payload={
                "source": "huitun_webHomePage_liveUserRank",
                "raw": row,
                "author_fans": self._to_int(row.get("followerCount")),
                "gmv": self._to_int(row.get("gmv")),
                "sales": self._to_int(row.get("sales")),
                "category": category,
            },
            collected_at=collected_at,
        )

    @staticmethod
    def _match_keyword(text: str, keywords: list[str]) -> str:
        lowered = text.lower()
        for kw in keywords:
            if kw.lower() in lowered:
                return kw
        return ""

    @staticmethod
    def _to_int(value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip().replace(",", "")
        if not text:
            return 0
        text = text.lower().replace("w", "万")
        m = re.match(r"^(\d+(?:\.\d+)?)\s*万$", text)
        if m:
            return int(float(m.group(1)) * 10000)
        try:
            return int(float(text))
        except ValueError:
            return 0

    @staticmethod
    def _to_float(value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace(",", "")
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return 0.0

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        m = re.match(r"^(\d{2})-(\d{2})\s+(\d{2}:\d{2})$", text)
        if m:
            year = now_utc().year
            try:
                return datetime.strptime(f"{year}-{m.group(1)}-{m.group(2)} {m.group(3)}", "%Y-%m-%d %H:%M").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                return None
        m = re.match(r"^(\d{2})-(\d{2})$", text)
        if m:
            year = now_utc().year
            try:
                return datetime.strptime(f"{year}-{m.group(1)}-{m.group(2)}", "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                return None
        return None
