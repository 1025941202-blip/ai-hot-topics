from __future__ import annotations

import unittest
from datetime import timedelta

from test_support import PROJECT_ROOT

from ai_hot_topics.config import load_runtime_config
from ai_hot_topics.models import NormalizedPost
from ai_hot_topics.processing.cluster import cluster_posts
from ai_hot_topics.processing.scoring import score_clusters
from ai_hot_topics.utils import now_utc


def _post(post_id: str, platform: str, title: str, body: str, likes: int, comments: int, shares: int):
    return NormalizedPost(
        platform=platform,
        platform_post_id=post_id,
        url=f"https://example.com/{platform}/{post_id}",
        title=title,
        body_text=body,
        author="tester",
        published_at=now_utc() - timedelta(hours=6),
        language="zh" if platform in {"douyin", "xiaohongshu"} else "en",
        metrics={"likes": likes, "comments": comments, "shares": shares, "views": likes * 20},
        keyword_hits=["AI", "Agent", "工作流"],
        source_id=f"{platform}-search",
        query="AI Agent",
        content_fingerprint=f"fp-{post_id}",
    )


class ClusteringScoringTests(unittest.TestCase):
    def test_similar_posts_cluster_together_and_score(self):
        posts = [
            _post("1", "douyin", "AI Agent 工作流拆解", "3步做一个自动化工作流，实测效率提升", 3000, 200, 100),
            _post("2", "xiaohongshu", "AI 工作流实测：Agent 自动化", "教程拆解 + Prompt 模板", 1800, 120, 80),
            _post("3", "youtube", "AI Video Tool News", "A roundup of AI tools", 50, 2, 0),
        ]
        clusters = cluster_posts(posts)
        self.assertGreaterEqual(len(clusters), 2)
        biggest = max(clusters, key=lambda c: len(c.posts))
        self.assertGreaterEqual(len(biggest.posts), 2)

        cfg = load_runtime_config(PROJECT_ROOT).scoring
        scores = score_clusters(clusters, cfg)
        by_id = {s.cluster_id: s for s in scores}
        self.assertIn(biggest.cluster_id, by_id)
        self.assertGreaterEqual(by_id[biggest.cluster_id].total_score, 50)


if __name__ == "__main__":
    unittest.main()

