#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ai_hot_topics.config import load_runtime_config
from ai_hot_topics.dashboard import DashboardService
from ai_hot_topics.utils import ensure_dir, now_utc


def _pick_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": row.get("candidate_id"),
        "title": row.get("title_suggestion") or "",
        "summary": row.get("summary") or "",
        "platforms": row.get("platforms") or [],
        "source_links": row.get("representative_urls") or [],
        "published_at": row.get("note_published_at") or "",
        "publish_time_text": row.get("note_publish_time_text") or "",
        "view_count": int(row.get("view_count") or 0),
        "like_count": int(row.get("like_count") or 0),
        "favorite_count": int(row.get("favorite_count") or 0),
        "comment_count": int(row.get("comment_count") or 0),
        "share_count": int(row.get("share_count") or 0),
        "author_name": row.get("author_name") or "",
        "author_avatar": row.get("author_avatar") or "",
        "author_bio": row.get("author_bio") or "",
        "author_fans_count": int(row.get("author_fans_count") or 0),
        "status": row.get("review_status_text") or "待处理",
        "total_score": float(row.get("total_score") or 0),
    }


def build_payload(
    service: DashboardService,
    *,
    platform: str,
    limit: int,
    min_score: float,
    sort_by: str,
    sort_order: str,
) -> dict[str, Any]:
    summary = service.fetch_summary()
    rows = service.fetch_candidates(
        platform=platform,
        limit=limit,
        min_score=min_score,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return {
        "generated_at": now_utc().isoformat().replace("+00:00", "Z"),
        "filters": {
            "platform": platform or "all",
            "limit": limit,
            "min_score": min_score,
            "sort_by": sort_by or "default",
            "sort_order": sort_order,
        },
        "summary": summary,
        "items": [_pick_fields(row) for row in rows],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 GitHub Pages 用的候选数据 JSON")
    parser.add_argument(
        "--project-dir",
        default="/Users/jiejie/Desktop/LVYU/projects/AI热点",
        help="项目目录",
    )
    parser.add_argument(
        "--output",
        default="/Users/jiejie/Desktop/LVYU/projects/AI热点/docs/data/candidates.json",
        help="输出 JSON 文件路径",
    )
    parser.add_argument("--platform", default="", help="平台筛选，例如 xiaohongshu/huitun")
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--sort-by", default="likes", help="likes/favorites/comments/views/shares")
    parser.add_argument("--sort-order", default="desc", choices=["asc", "desc"])
    args = parser.parse_args()

    cfg = load_runtime_config(args.project_dir)
    service = DashboardService(cfg.paths.db_path)
    payload = build_payload(
        service,
        platform=args.platform.strip(),
        limit=max(1, min(int(args.limit), 1000)),
        min_score=float(args.min_score),
        sort_by=args.sort_by.strip(),
        sort_order=args.sort_order.strip().lower(),
    )

    output = Path(args.output).resolve()
    ensure_dir(output.parent)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(output),
                "items": len(payload.get("items") or []),
                "generated_at": payload.get("generated_at"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
