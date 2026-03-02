from __future__ import annotations

import unittest
from datetime import timedelta

from ai_hot_topics.collectors.xiaohongshu import XiaohongshuCollector
from ai_hot_topics.utils import now_utc


class XiaohongshuCollectorTests(unittest.TestCase):
    def test_parse_count_text(self):
        self.assertEqual(XiaohongshuCollector._parse_count_text("1.6万"), 16000)
        self.assertEqual(XiaohongshuCollector._parse_count_text("5272"), 5272)
        self.assertEqual(XiaohongshuCollector._parse_count_text("02-13"), 0)
        self.assertEqual(XiaohongshuCollector._parse_count_text("1天前"), 0)
        self.assertEqual(XiaohongshuCollector._parse_count_text(""), 0)

    def test_cards_to_raw_items_builds_notes_and_dedups(self):
        collector = XiaohongshuCollector(env={}, source_id="xiaohongshu-search")
        cards = [
            {
                "href": "https://www.xiaohongshu.com/explore/abc123",
                "title": "AI工具推荐｜打工人效率翻倍",
                "author": "小胖讲AI",
                "metricText": "1.2万",
                "dateText": "02-13",
                "text": "AI工具推荐｜打工人效率翻倍\\n小胖讲AI\\n02-13\\n1.2万",
                "lines": ["AI工具推荐｜打工人效率翻倍", "小胖讲AI", "02-13", "1.2万"],
            },
            {
                "href": "https://www.xiaohongshu.com/explore/abc123",
                "title": "重复卡片",
                "author": "小胖讲AI",
                "metricText": "300",
                "dateText": "02-14",
                "text": "重复卡片",
                "lines": ["重复卡片"],
            },
            {
                "href": "https://www.xiaohongshu.com/explore/def456",
                "title": "大家都在搜",
                "author": "",
                "metricText": "",
                "dateText": "",
                "text": "大家都在搜\\nai工具排行榜",
                "lines": ["大家都在搜", "ai工具排行榜"],
            },
        ]
        items = collector._cards_to_raw_items(cards, keyword="AI工具")
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.platform, "xiaohongshu")
        self.assertEqual(item.platform_post_id, "abc123")
        self.assertEqual(item.author, "小胖讲AI")
        self.assertEqual(item.metrics.get("likes"), 12000)
        self.assertIn("AI工具推荐", item.title)

    def test_state_items_to_raw_items_extracts_metrics_and_author(self):
        collector = XiaohongshuCollector(env={}, source_id="xiaohongshu-search")
        state_items = [
            {
                "noteId": "note-001",
                "xsecToken": "note_token",
                "title": "AI工作流模板，效率提升50%",
                "user": {
                    "userId": "user-001",
                    "nickname": "效率研究员",
                    "avatar": "https://example.com/a.jpg",
                    "xsecToken": "user_token",
                },
                "interactInfo": {
                    "likedCount": "1.5万",
                    "collectedCount": "3200",
                    "commentCount": "268",
                    "shareCount": "96",
                    "viewCount": "23.4万",
                },
                "publishTimeText": "2天前",
                "type": "normal",
            }
        ]
        items = collector._state_items_to_raw_items(state_items, keyword="AI工作流")
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.platform_post_id, "note-001")
        self.assertEqual(item.author, "效率研究员")
        self.assertEqual(item.metrics.get("views"), 234000)
        self.assertEqual(item.metrics.get("likes"), 15000)
        self.assertEqual(item.metrics.get("favorites"), 3200)
        self.assertEqual(item.metrics.get("comments"), 268)
        self.assertEqual(item.metrics.get("shares"), 96)
        self.assertIn("xsec_token=note_token", item.url)
        self.assertEqual(item.raw_payload.get("author_name"), "效率研究员")
        self.assertEqual(item.raw_payload.get("author_avatar"), "https://example.com/a.jpg")

    def test_parse_publish_time_relative(self):
        parsed = XiaohongshuCollector._parse_publish_time("3小时前")
        self.assertIsNotNone(parsed)
        self.assertLessEqual(now_utc() - parsed, timedelta(hours=4))


if __name__ == "__main__":
    unittest.main()
