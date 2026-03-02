from __future__ import annotations

import unittest

from ai_hot_topics.collectors.huitun import HuitunCollector


class HuitunCollectorTests(unittest.TestCase):
    def test_build_items_from_home_data_filters_by_keywords(self):
        collector = HuitunCollector(env={}, source_id="huitun-dashboard")
        data = {
            "awemeList": [
                {
                    "awemeId": "76110001",
                    "playUri": "https://www.douyin.com/video/76110001",
                    "desc": "AI 提效工作流，3分钟上手",
                    "nickname": "AI实战派",
                    "publishTime": "03-01 18:00",
                    "diggCount": "1.8w",
                    "commentCount": "268",
                    "shareCount": "112",
                    "colCount": "9021",
                    "viewCount": "0",
                    "fans": "12.3w",
                },
                {
                    "awemeId": "76110002",
                    "playUri": "https://www.douyin.com/video/76110002",
                    "desc": "美食探店合集",
                    "nickname": "吃货",
                    "diggCount": "9999",
                },
            ],
            "curTakeRank": [
                {
                    "roomId": "76120001",
                    "uid": "3250600708947220",
                    "title": "AI 大模型工具专场",
                    "nickName": "科技直播间",
                    "watchNum": "5600",
                    "followerCount": "43.2w",
                    "gmv": "2250000",
                    "sales": "12000",
                    "startTime": "2026-03-02 08:06:01",
                    "category": "科技",
                }
            ],
            "liveUserRank": [],
        }
        items = collector._build_items_from_home_data(
            data=data,
            keywords=["AI", "大模型"],
            per_feed_limit=20,
        )
        self.assertEqual(len(items), 2)

        aweme = next(x for x in items if x.platform_post_id.startswith("aweme-"))
        self.assertEqual(aweme.query, "AI")
        self.assertEqual(aweme.metrics.get("likes"), 18000)
        self.assertEqual(aweme.metrics.get("favorites"), 9021)
        self.assertEqual(aweme.metrics.get("comments"), 268)
        self.assertEqual(aweme.raw_payload.get("author_fans"), 123000)

        live = next(x for x in items if x.platform_post_id.startswith("live-"))
        self.assertEqual(live.query, "AI")
        self.assertEqual(live.metrics.get("views"), 5600)
        self.assertEqual(live.raw_payload.get("gmv"), 2250000)
        self.assertEqual(live.raw_payload.get("sales"), 12000)

    def test_to_int_supports_wan_unit(self):
        self.assertEqual(HuitunCollector._to_int("1.2w"), 12000)
        self.assertEqual(HuitunCollector._to_int("2.5万"), 25000)
        self.assertEqual(HuitunCollector._to_int(""), 0)


if __name__ == "__main__":
    unittest.main()
