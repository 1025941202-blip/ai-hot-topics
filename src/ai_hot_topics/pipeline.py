from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from .collectors import (
    DouyinCollector,
    HuitunCollector,
    XCollector,
    XiaohongshuCollector,
    YouTubeCollector,
)
from .config import RuntimeConfig, SUPPORTED_PLATFORMS
from .generators import OutlineGeneratorService
from .models import NormalizedPost, RawItem, RunSummary
from .processing import cluster_posts, normalize_raw_items, score_clusters
from .storage import Database
from .sync import FeishuSyncService
from .utils import ensure_dir, isoformat_z, json_dumps, json_loads, now_utc


def build_collectors(cfg: RuntimeConfig):
    source_map: dict[str, str] = {}
    for source in cfg.sources:
        source_key = source.id.lower()
        for platform in SUPPORTED_PLATFORMS:
            if source_key == platform or source_key.startswith(f"{platform}-"):
                source_map[platform] = source.id
    return {
        "douyin": DouyinCollector(cfg.env, source_id=source_map.get("douyin", "douyin-search")),
        "xiaohongshu": XiaohongshuCollector(cfg.env, source_id=source_map.get("xiaohongshu", "xiaohongshu-search")),
        "huitun": HuitunCollector(cfg.env, source_id=source_map.get("huitun", "huitun-dashboard")),
        "x": XCollector(cfg.env, source_id=source_map.get("x", "x-search")),
        "youtube": YouTubeCollector(cfg.env, source_id=source_map.get("youtube", "youtube-search")),
    }


class Pipeline:
    def __init__(
        self,
        cfg: RuntimeConfig,
        db: Database,
        outline_generator: OutlineGeneratorService,
        feishu_sync: FeishuSyncService,
    ):
        self.cfg = cfg
        self.db = db
        self.outline_generator = outline_generator
        self.feishu_sync = feishu_sync
        self.collectors = build_collectors(cfg)
        ensure_dir(cfg.paths.data_dir)
        ensure_dir(cfg.paths.raw_data_dir)

    def _raw_item_to_db_dict(self, raw: RawItem) -> dict[str, Any]:
        return {
            "platform": raw.platform,
            "source_id": raw.source_id,
            "query": raw.query,
            "platform_post_id": raw.platform_post_id,
            "url": raw.url,
            "title": raw.title,
            "text": raw.text,
            "author": raw.author,
            "published_at": isoformat_z(raw.published_at),
            "language": raw.language,
            "metrics": raw.metrics,
            "raw_payload": raw.raw_payload,
            "collected_at": isoformat_z(raw.collected_at),
        }

    def _write_raw_snapshot(self, run_id: str, platform: str, items: list[RawItem]) -> Path | None:
        if not items:
            return None
        day_dir = ensure_dir(self.cfg.paths.raw_data_dir / now_utc().strftime("%Y-%m-%d"))
        file_path = day_dir / f"{platform}-{run_id}.jsonl"
        with file_path.open("a", encoding="utf-8") as fh:
            for item in items:
                fh.write(json_dumps(self._raw_item_to_db_dict(item)) + "\n")
        return file_path

    def collect_stage(
        self,
        run_id: str,
        *,
        platforms: list[str] | None = None,
        since_hours: int = 48,
        max_per_keyword: int = 5,
    ) -> dict[str, Any]:
        selected = platforms or list(SUPPORTED_PLATFORMS)
        since_ts = now_utc() - timedelta(hours=since_hours)
        all_raw_items: list[RawItem] = []
        all_normalized: list[NormalizedPost] = []
        stage_stats: dict[str, Any] = {"platforms": {}, "since_hours": since_hours}

        for platform in selected:
            collector = self.collectors.get(platform)
            if not collector:
                continue
            start = now_utc()
            keywords = self.cfg.keywords.keywords_for_platform(platform)
            try:
                result = collector.collect(keywords, since_ts=since_ts, max_per_keyword=max_per_keyword)
                snapshot_path = self._write_raw_snapshot(run_id, platform, result.items)
                raw_count = self.db.upsert_raw_items(run_id, [self._raw_item_to_db_dict(x) for x in result.items])
                normalized = normalize_raw_items(result.items, self.cfg.keywords)
                normalized_count = self.db.upsert_normalized_posts(run_id, normalized)
                all_raw_items.extend(result.items)
                all_normalized.extend(normalized)
                end = now_utc()
                metrics = {
                    "keywords": len(keywords),
                    "raw_count": raw_count,
                    "normalized_count": normalized_count,
                }
                if snapshot_path:
                    metrics["raw_snapshot"] = str(snapshot_path)
                if result.metadata:
                    metrics.update(result.metadata)
                status = "success" if not result.error else "partial_error"
                message = result.error or result.warning
                self.db.log_run(
                    run_id,
                    "collect",
                    status,
                    platform=platform,
                    started_at=start,
                    ended_at=end,
                    message=message,
                    metrics=metrics,
                )
                stage_stats["platforms"][platform] = {
                    "status": status,
                    "raw_count": raw_count,
                    "normalized_count": normalized_count,
                    "warning": result.warning,
                    "error": result.error,
                }
            except Exception as exc:
                end = now_utc()
                self.db.log_run(
                    run_id,
                    "collect",
                    "failed",
                    platform=platform,
                    started_at=start,
                    ended_at=end,
                    message=str(exc),
                    metrics={"keywords": len(keywords)},
                )
                stage_stats["platforms"][platform] = {"status": "failed", "error": str(exc)}
                continue

        stage_stats["raw_count"] = len(all_raw_items)
        stage_stats["normalized_count"] = len(all_normalized)
        return stage_stats

    def _row_to_normalized_post(self, row) -> NormalizedPost:
        from .utils import parse_datetime

        return NormalizedPost(
            platform=str(row["platform"]),
            platform_post_id=str(row["platform_post_id"]),
            url=str(row["url"]),
            title=str(row["title"] or ""),
            body_text=str(row["body_text"] or ""),
            author=str(row["author"] or ""),
            published_at=parse_datetime(row["published_at"]),
            language=str(row["language"] or "und"),
            metrics=json_loads(row["metrics_json"], default={}) or {},
            keyword_hits=json_loads(row["keyword_hits_json"], default=[]) or [],
            source_id=str(row["source_id"] or ""),
            query=str(row["query"] or ""),
            content_fingerprint=str(row["content_fingerprint"] or ""),
        )

    def process_stage(self, run_id: str) -> dict[str, Any]:
        start = now_utc()
        rows = self.db.fetch_recent_normalized_posts()
        posts = [self._row_to_normalized_post(row) for row in rows]
        clusters = cluster_posts(posts)
        scores = score_clusters(clusters, self.cfg.scoring)
        cluster_count = self.db.upsert_topic_clusters(run_id, clusters)
        score_count = self.db.upsert_topic_scores(scores)
        end = now_utc()
        metrics = {
            "input_posts": len(posts),
            "clusters": cluster_count,
            "scores": score_count,
        }
        self.db.log_run(run_id, "process", "success", started_at=start, ended_at=end, metrics=metrics)
        return metrics

    def generate_scripts_stage(self, run_id: str, limit: int = 50) -> dict[str, Any]:
        start = now_utc()
        rows = self.db.fetch_clusters_for_generation(self.cfg.scoring.generation_threshold, limit=limit)
        drafts = []
        for row in rows:
            post_rows = self.db.fetch_cluster_posts(row["cluster_id"])
            cluster_row = dict(row)
            examples = [dict(post_row) for post_row in post_rows]
            drafts.append(self.outline_generator.generate_outline(cluster_row, examples))
        count = self.db.upsert_script_drafts(drafts)
        end = now_utc()
        metrics = {"eligible_clusters": len(rows), "generated_or_updated": count}
        self.db.log_run(run_id, "generate", "success", started_at=start, ended_at=end, metrics=metrics)
        return metrics

    def sync_feishu_stage(self, run_id: str) -> dict[str, Any]:
        start = now_utc()
        candidate_rows = [dict(row) for row in self.db.fetch_candidates_for_sync()]
        candidates_result = self.feishu_sync.sync_candidates(candidate_rows)
        review_updates = self.feishu_sync.fetch_review_state_updates()
        review_updated_count = self.db.apply_review_state_updates(review_updates) if review_updates else 0
        promoted = self.db.promote_approved_candidates()
        # 重新读取候选数据，确保飞书审核状态回写能在同一轮推动主表同步。
        candidate_rows = [dict(row) for row in self.db.fetch_candidates_for_sync()]
        main_result = self.feishu_sync.sync_main_topics(candidate_rows)
        logs_result = self.feishu_sync.sync_run_logs(
            run_id, [dict(row) for row in self.db.get_run_logs(run_id)]
        )
        end = now_utc()
        metrics = {
            "candidate_sync": candidates_result,
            "main_sync": main_result,
            "logs_sync": logs_result,
            "review_updates": review_updated_count,
            "promoted": promoted,
            "feishu_enabled": self.feishu_sync.enabled(),
        }
        self.db.log_run(run_id, "sync_feishu", "success", started_at=start, ended_at=end, metrics=metrics)
        return metrics

    def run_daily(
        self,
        *,
        since_hours: int = 48,
        max_per_keyword: int = 5,
        generate_limit: int = 50,
    ) -> RunSummary:
        run_id = self.db.new_run_id(prefix="daily")
        self.db.log_run(run_id, "run_daily", "started", started_at=now_utc(), metrics={"since_hours": since_hours})
        self.collect_stage(run_id, since_hours=since_hours, max_per_keyword=max_per_keyword)
        self.process_stage(run_id)
        self.generate_scripts_stage(run_id, limit=generate_limit)
        sync_stats = self.sync_feishu_stage(run_id)
        summary_counts = self.db.get_summary_counts()
        self.db.log_run(
            run_id,
            "run_daily",
            "finished",
            ended_at=now_utc(),
            metrics={"summary_counts": summary_counts},
        )
        return RunSummary(
            run_id=run_id,
            raw_count=summary_counts.get("raw_posts", 0),
            normalized_count=summary_counts.get("normalized_posts", 0),
            cluster_count=summary_counts.get("topic_clusters", 0),
            generated_count=summary_counts.get("script_drafts", 0),
            approved_promoted=summary_counts.get("main_topic_library", 0),
        )

    def run_backfill(self, days: int, max_per_keyword: int = 5) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for i in range(days):
            since_hours = 48 + i * 24
            summary = self.run_daily(since_hours=since_hours, max_per_keyword=max_per_keyword)
            results.append(asdict(summary))
        return {"days": days, "runs": results}
