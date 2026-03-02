from __future__ import annotations

import unittest
from datetime import timedelta

from test_support import make_temp_project

from ai_hot_topics.config import load_runtime_config
from ai_hot_topics.models import NormalizedPost, ScriptOutlineDraft, TopicCluster, TopicScoreBreakdown
from ai_hot_topics.storage import Database
from ai_hot_topics.sync.feishu import FeishuSyncService, MemoryBitableAdapter
from ai_hot_topics.utils import now_utc


class StorageAndSyncTests(unittest.TestCase):
    def setUp(self):
        self.project_dir = make_temp_project()
        self.cfg = load_runtime_config(self.project_dir)
        self.db = Database(self.cfg.paths.db_path)

    def tearDown(self):
        self.db.close()

    def _sample_post(self) -> NormalizedPost:
        return NormalizedPost(
            platform="youtube",
            platform_post_id="abc",
            url="https://youtube.com/watch?v=abc",
            title="AI Agent Workflow Tutorial",
            body_text="step by step tutorial for ai agent workflow",
            author="demo",
            published_at=now_utc() - timedelta(hours=8),
            language="en",
            metrics={"views": 10000, "likes": 500, "comments": 50, "shares": 0},
            keyword_hits=["AI", "Agent"],
            source_id="youtube-search",
            query="AI Agent",
            content_fingerprint="fp-abc",
        )

    def test_db_upsert_idempotency_and_promotion(self):
        run_id = self.db.new_run_id()
        post = self._sample_post()
        self.db.upsert_normalized_posts(run_id, [post])
        self.db.upsert_normalized_posts(run_id, [post])
        row = self.db.conn.execute("SELECT COUNT(*) AS n FROM normalized_posts").fetchone()
        self.assertEqual(row["n"], 1)

        cluster = TopicCluster(
            cluster_id="topic-xyz",
            title_suggestion="AI Agent Workflow 拆解",
            summary="教程拆解",
            keyword_hits=["AI", "Agent"],
            representative_urls=[post.url],
            representative_post_refs=[(post.platform, post.platform_post_id)],
            posts=[post],
            novelty_score=66.0,
        )
        score = TopicScoreBreakdown(
            cluster_id="topic-xyz",
            hotness_score=80,
            freshness_score=70,
            reproducibility_score=90,
            china_fit_score=50,
            total_score=77,
            penalties=[],
            weights_version="v1",
            debug={},
        )
        draft = ScriptOutlineDraft(
            cluster_id="topic-xyz",
            hook="hook",
            audience="创作者",
            core_point="core",
            outline_1="1",
            outline_2="2",
            outline_3="3",
            cta="cta",
            evidence_links=[post.url],
            risk_notes="",
            provider="mock",
            model="mock",
            status="generated",
        )
        self.db.upsert_topic_clusters(run_id, [cluster])
        self.db.upsert_topic_scores([score])
        self.db.upsert_script_drafts([draft])
        self.db.apply_review_state_updates({"topic-xyz": {"status": "approved", "reviewer": "tester"}})
        promoted = self.db.promote_approved_candidates()
        self.assertEqual(promoted, 1)

    def test_feishu_memory_sync_is_idempotent_and_reads_review_status(self):
        adapter = MemoryBitableAdapter()
        svc = FeishuSyncService(adapter=adapter, table_candidates="tbl_candidates", table_main="tbl_main", table_run_logs="tbl_logs")
        rows = [
            {
                "candidate_id": "topic-1",
                "title_suggestion": "Title",
                "summary": "Summary",
                "keyword_hits_json": '["AI"]',
                "representative_urls_json": '["https://example.com"]',
                "novelty_score": 60,
                "updated_at": "2026-02-25T09:00:00Z",
                "review_status": "candidate",
                "review_notes": "",
                "hotness_score": 80,
                "freshness_score": 70,
                "reproducibility_score": 75,
                "china_fit_score": 50,
                "total_score": 73,
                "hook": "",
                "audience": "",
                "core_point": "",
                "outline_1": "",
                "outline_2": "",
                "outline_3": "",
                "cta": "",
                "evidence_links_json": "[]",
                "risk_notes": "",
                "provider": "mock",
                "model": "mock",
                "draft_status": "generated",
            }
        ]
        first = svc.sync_candidates(rows)
        second = svc.sync_candidates(rows)
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["updated"], 1)
        # 模拟人工审核回写
        adapter.upsert_records("tbl_candidates", "candidate_id", [{"candidate_id": "topic-1", "状态": "approved", "审核备注": "ok"}])
        updates = svc.fetch_review_state_updates()
        self.assertEqual(updates["topic-1"]["status"], "approved")


if __name__ == "__main__":
    unittest.main()

