from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..models import RawItem
from ..utils import now_utc
from .base import CollectorResult


def _http_get_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "ai-hot-topics/0.1"})
    with urlopen(req, timeout=20) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


class YouTubeCollector:
    platform = "youtube"

    def __init__(self, env: dict[str, str], source_id: str):
        self.env = env
        self.source_id = source_id

    def collect(self, keywords: list[str], since_ts: datetime, max_per_keyword: int = 5) -> CollectorResult:
        api_key = (self.env.get("YOUTUBE_API_KEY") or "").strip()
        if not api_key:
            return CollectorResult(platform=self.platform, warning="未配置 YOUTUBE_API_KEY，YouTube 采集已跳过")

        all_items: list[RawItem] = []
        errors: list[str] = []
        for kw in keywords:
            try:
                all_items.extend(self._collect_keyword(api_key, kw, since_ts, max_per_keyword))
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                errors.append(f"{kw}: {exc}")
            except Exception as exc:
                errors.append(f"{kw}: {type(exc).__name__}: {exc}")

        if errors and not all_items:
            return CollectorResult(platform=self.platform, error="; ".join(errors[:3]))
        return CollectorResult(
            platform=self.platform,
            items=all_items,
            warning=("; ".join(errors[:3]) if errors else None),
            metadata={"keyword_count": len(keywords)},
        )

    def _collect_keyword(
        self,
        api_key: str,
        keyword: str,
        since_ts: datetime,
        max_per_keyword: int,
    ) -> list[RawItem]:
        if since_ts.tzinfo is None:
            since_ts = since_ts.replace(tzinfo=timezone.utc)
        published_after = since_ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        search_params = {
            "part": "snippet",
            "type": "video",
            "q": keyword,
            "order": "date",
            "maxResults": str(min(max_per_keyword, 10)),
            "publishedAfter": published_after,
            "key": api_key,
        }
        search_url = "https://www.googleapis.com/youtube/v3/search?" + urlencode(search_params)
        search_data = _http_get_json(search_url)
        items = search_data.get("items", []) or []
        video_ids = [x.get("id", {}).get("videoId") for x in items if x.get("id", {}).get("videoId")]
        stats_map: dict[str, dict] = {}
        if video_ids:
            details_url = "https://www.googleapis.com/youtube/v3/videos?" + urlencode(
                {
                    "part": "snippet,statistics",
                    "id": ",".join(video_ids),
                    "key": api_key,
                }
            )
            details_data = _http_get_json(details_url)
            for item in details_data.get("items", []) or []:
                stats_map[str(item.get("id"))] = item

        now = now_utc()
        results: list[RawItem] = []
        for item in items:
            video_id = item.get("id", {}).get("videoId")
            if not video_id:
                continue
            snippet = item.get("snippet", {}) or {}
            detail = stats_map.get(video_id, {})
            detail_stats = detail.get("statistics", {}) or {}
            published_at = snippet.get("publishedAt")
            dt = None
            if isinstance(published_at, str):
                try:
                    dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                except ValueError:
                    dt = None
            title = str(snippet.get("title") or "")
            description = str(snippet.get("description") or "")
            results.append(
                RawItem(
                    platform="youtube",
                    source_id=self.source_id,
                    query=keyword,
                    platform_post_id=str(video_id),
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    title=title,
                    text=description,
                    author=str(snippet.get("channelTitle") or ""),
                    published_at=dt,
                    metrics={
                        "views": _safe_int(detail_stats.get("viewCount")),
                        "likes": _safe_int(detail_stats.get("likeCount")),
                        "comments": _safe_int(detail_stats.get("commentCount")),
                        "shares": 0,
                    },
                    language="en",
                    raw_payload={"search_item": item, "video_item": detail},
                    collected_at=now,
                )
            )
        return results


def _safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

