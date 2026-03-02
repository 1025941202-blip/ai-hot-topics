from __future__ import annotations

import unittest
from datetime import timedelta

from test_support import make_temp_project

from ai_hot_topics.config import load_runtime_config
from ai_hot_topics.generators import build_outline_generator
from ai_hot_topics.models import RawItem
from ai_hot_topics.pipeline import Pipeline
from ai_hot_topics.storage import Database
from ai_hot_topics.sync import build_feishu_sync_service
from ai_hot_topics.utils import now_utc


class _FakeCollector:
    def __init__(self, platform: str, source_id: str):
        self.platform = platform
        self.source_id = source_id

    def collect(self, keywords, since_ts, max_per_keyword=5):
        from ai_hot_topics.collectors.base import CollectorResult

        keyword = keywords[0]
        item = RawItem(
            platform=self.platform,
            source_id=self.source_id,
            query=keyword,
            platform_post_id=f"{self.platform}-1",
            url=f"https://example.com/{self.platform}/1",
            title=f"{keyword} 教程拆解 {self.platform}",
            text="AI workflow 实测，3步完成自动化",
            author="demo",
            published_at=now_utc() - timedelta(hours=3),
            metrics={"views": 10000, "likes": 800, "comments": 50, "shares": 20},
            language="zh" if self.platform in {"douyin", "xiaohongshu"} else "en",
            raw_payload={"fake": True},
            collected_at=now_utc(),
        )
        return CollectorResult(platform=self.platform, items=[item])


class PipelineSmokeTests(unittest.TestCase):
    def test_pipeline_stages_run_end_to_end_with_fake_collectors(self):
        project_dir = make_temp_project()
        cfg = load_runtime_config(project_dir)
        db = Database(cfg.paths.db_path)
        try:
            pipeline = Pipeline(
                cfg=cfg,
                db=db,
                outline_generator=build_outline_generator(cfg.env, cfg.paths.prompt_file),
                feishu_sync=build_feishu_sync_service(cfg.env),
            )
            pipeline.cfg.scoring.generation_threshold = 0
            pipeline.collectors = {
                "douyin": _FakeCollector("douyin", "douyin-search"),
                "xiaohongshu": _FakeCollector("xiaohongshu", "xiaohongshu-search"),
                "x": _FakeCollector("x", "x-search"),
                "youtube": _FakeCollector("youtube", "youtube-search"),
            }
            run_id = db.new_run_id(prefix="smoke")
            collect_stats = pipeline.collect_stage(run_id, since_hours=48, max_per_keyword=1)
            self.assertGreaterEqual(collect_stats["normalized_count"], 1)
            process_stats = pipeline.process_stage(run_id)
            self.assertGreaterEqual(process_stats["clusters"], 1)
            gen_stats = pipeline.generate_scripts_stage(run_id, limit=10)
            self.assertGreaterEqual(gen_stats["generated_or_updated"], 1)
            sync_stats = pipeline.sync_feishu_stage(run_id)
            self.assertIn("candidate_sync", sync_stats)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
