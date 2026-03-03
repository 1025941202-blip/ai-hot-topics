from __future__ import annotations

import unittest
from datetime import timedelta

from test_support import make_temp_project

from ai_hot_topics.config import load_runtime_config
from ai_hot_topics.dashboard import DashboardService
from ai_hot_topics.models import NormalizedPost, TopicCluster, TopicScoreBreakdown
from ai_hot_topics.storage import Database
from ai_hot_topics.utils import now_utc


class DashboardServiceTests(unittest.TestCase):
    def setUp(self):
        self.project_dir = make_temp_project()
        self.cfg = load_runtime_config(self.project_dir)
        self.db = Database(self.cfg.paths.db_path)
        self.service = DashboardService(self.cfg.paths.db_path)
        self._seed_data()

    def tearDown(self):
        self.db.close()

    def _seed_data(self):
        run_id = self.db.new_run_id(prefix="dashboard-test")
        post = NormalizedPost(
            platform="xiaohongshu",
            platform_post_id="abc123",
            url="https://www.xiaohongshu.com/explore/abc123",
            title="AI工具推荐",
            body_text="AI 工具测评与工作流拆解",
            author="作者A",
            published_at=now_utc() - timedelta(hours=6),
            language="zh",
            metrics={"likes": 12000, "comments": 300, "shares": 80},
            keyword_hits=["AI", "工具"],
            source_id="xiaohongshu-search",
            query="AI工具",
            content_fingerprint="fp-abc123",
        )
        self.db.upsert_normalized_posts(run_id, [post])
        self.db.upsert_raw_items(
            run_id,
            [
                {
                    "platform": "xiaohongshu",
                    "source_id": "xiaohongshu-search",
                    "query": "AI工具",
                    "platform_post_id": "abc123",
                    "url": "https://www.xiaohongshu.com/explore/abc123",
                    "title": "AI工具推荐",
                    "text": "AI 工具测评与工作流拆解",
                    "author": "作者A",
                    "published_at": (now_utc() - timedelta(hours=6))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "language": "zh",
                    "metrics": {
                        "views": 230000,
                        "likes": 12000,
                        "favorites": 5600,
                        "comments": 300,
                        "shares": 80,
                    },
                    "raw_payload": {
                        "publish_time_text": "6小时前",
                        "author_name": "作者A",
                        "author_avatar": "https://example.com/avatar.jpg",
                        "author_profile_url": "https://www.xiaohongshu.com/user/profile/user-abc",
                        "author_profile": {
                            "bio": "AI 创作者，专注效率工具",
                            "fans_count": 95000,
                            "follows_count": 123,
                            "likes_and_collects_count": 560000,
                        },
                    },
                    "collected_at": now_utc().isoformat().replace("+00:00", "Z"),
                }
            ],
        )
        post_2 = NormalizedPost(
            platform="xiaohongshu",
            platform_post_id="def456",
            url="https://www.xiaohongshu.com/explore/def456",
            title="AI写作提效",
            body_text="AI 写作提示词与模板",
            author="作者B",
            published_at=now_utc() - timedelta(hours=3),
            language="zh",
            metrics={"likes": 2200, "comments": 999, "shares": 120},
            keyword_hits=["AI", "写作"],
            source_id="xiaohongshu-search",
            query="AI写作",
            content_fingerprint="fp-def456",
        )
        self.db.upsert_normalized_posts(run_id, [post_2])
        self.db.upsert_raw_items(
            run_id,
            [
                {
                    "platform": "xiaohongshu",
                    "source_id": "xiaohongshu-search",
                    "query": "AI写作",
                    "platform_post_id": "def456",
                    "url": "https://www.xiaohongshu.com/explore/def456",
                    "title": "AI写作提效",
                    "text": "AI 写作提示词与模板",
                    "author": "作者B",
                    "published_at": (now_utc() - timedelta(hours=3))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "language": "zh",
                    "metrics": {
                        "views": 120000,
                        "likes": 2200,
                        "favorites": 22000,
                        "comments": 999,
                        "shares": 120,
                    },
                    "raw_payload": {
                        "publish_time_text": "3小时前",
                        "author_name": "作者B",
                        "author_avatar": "https://example.com/avatar-b.jpg",
                        "author_profile_url": "https://www.xiaohongshu.com/user/profile/user-def",
                        "author_profile": {
                            "bio": "专注AI写作",
                            "fans_count": 120000,
                            "follows_count": 88,
                            "likes_and_collects_count": 880000,
                        },
                    },
                    "collected_at": now_utc().isoformat().replace("+00:00", "Z"),
                }
            ],
        )
        cluster = TopicCluster(
            cluster_id="topic-abc123",
            title_suggestion="AI工具推荐：效率翻倍清单",
            summary="围绕 AI 工具的爆款选题",
            keyword_hits=["AI", "工具"],
            representative_urls=[post.url],
            representative_post_refs=[("xiaohongshu", "abc123")],
            posts=[post],
            novelty_score=70.0,
        )
        score = TopicScoreBreakdown(
            cluster_id="topic-abc123",
            hotness_score=82.0,
            freshness_score=76.0,
            reproducibility_score=88.0,
            china_fit_score=90.0,
            total_score=83.0,
            penalties=[],
            weights_version="v1",
            debug={},
        )
        cluster_2 = TopicCluster(
            cluster_id="topic-def456",
            title_suggestion="AI写作模板：爆款标题拆解",
            summary="围绕 AI 写作模板的爆款选题",
            keyword_hits=["AI", "写作"],
            representative_urls=[post_2.url],
            representative_post_refs=[("xiaohongshu", "def456")],
            posts=[post_2],
            novelty_score=72.0,
        )
        score_2 = TopicScoreBreakdown(
            cluster_id="topic-def456",
            hotness_score=65.0,
            freshness_score=80.0,
            reproducibility_score=82.0,
            china_fit_score=88.0,
            total_score=72.0,
            penalties=[],
            weights_version="v1",
            debug={},
        )
        self.db.upsert_topic_clusters(run_id, [cluster])
        self.db.upsert_topic_clusters(run_id, [cluster_2])
        self.db.upsert_topic_scores([score, score_2])

    def test_fetch_candidates_and_summary(self):
        summary = self.service.fetch_summary()
        self.assertGreaterEqual(summary["total_candidates"], 1)
        self.assertGreaterEqual(summary["xiaohongshu_posts"], 1)
        self.assertIn("huitun_posts", summary)

        rows = self.service.fetch_candidates(platform="xiaohongshu", min_score=70, limit=20)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["candidate_id"], "topic-abc123")
        self.assertIn("xiaohongshu", rows[0]["platforms"])
        self.assertEqual(rows[0]["view_count"], 230000)
        self.assertEqual(rows[0]["like_count"], 12000)
        self.assertEqual(rows[0]["favorite_count"], 5600)
        self.assertEqual(rows[0]["comment_count"], 300)
        self.assertEqual(rows[0]["share_count"], 80)
        self.assertEqual(rows[0]["author_name"], "作者A")
        self.assertEqual(rows[0]["author_bio"], "AI 创作者，专注效率工具")
        self.assertEqual(rows[0]["author_fans_count"], 95000)
        self.assertEqual(rows[0]["review_status_text"], "待处理")

    def test_update_review_state(self):
        self.service.update_review_state(candidate_id="topic-abc123", status="approved", notes="值得做")
        rows = self.service.fetch_candidates(platform="xiaohongshu", review_status="approved")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["review_status"], "approved")

    def test_update_review_state_accepts_chinese_status(self):
        self.service.update_review_state(candidate_id="topic-abc123", status="已通过", notes="中文状态")
        rows = self.service.fetch_candidates(platform="xiaohongshu", review_status="已通过")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["review_status"], "approved")
        self.assertEqual(rows[0]["review_status_text"], "已通过")

    def test_sort_by_metric_fields(self):
        by_likes = self.service.fetch_candidates(
            platform="xiaohongshu",
            sort_by="likes",
            sort_order="desc",
            limit=20,
        )
        self.assertEqual(by_likes[0]["candidate_id"], "topic-abc123")

        by_favorites = self.service.fetch_candidates(
            platform="xiaohongshu",
            sort_by="收藏",
            sort_order="降序",
            limit=20,
        )
        self.assertEqual(by_favorites[0]["candidate_id"], "topic-def456")

        by_comments = self.service.fetch_candidates(
            platform="xiaohongshu",
            sort_by="comments",
            sort_order="desc",
            limit=20,
        )
        self.assertEqual(by_comments[0]["candidate_id"], "topic-def456")

        by_comments_top1 = self.service.fetch_candidates(
            platform="xiaohongshu",
            sort_by="comments",
            sort_order="desc",
            limit=1,
        )
        self.assertEqual(len(by_comments_top1), 1)
        self.assertEqual(by_comments_top1[0]["candidate_id"], "topic-def456")

    def test_sort_by_published_at(self):
        by_publish_desc = self.service.fetch_candidates(
            platform="xiaohongshu",
            sort_by="发布时间",
            sort_order="降序",
            limit=20,
        )
        self.assertEqual(by_publish_desc[0]["candidate_id"], "topic-def456")

        by_publish_asc = self.service.fetch_candidates(
            platform="xiaohongshu",
            sort_by="published_at",
            sort_order="asc",
            limit=20,
        )
        self.assertEqual(by_publish_asc[0]["candidate_id"], "topic-abc123")


if __name__ == "__main__":
    unittest.main()
