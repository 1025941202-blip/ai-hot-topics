from __future__ import annotations

import unittest

from test_support import PROJECT_ROOT

from ai_hot_topics.generators.service import OutlineGeneratorService, load_prompt_template


class _FlakyProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self):
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        if self.calls == 1:
            return "not-json"
        return (
            '{"hook":"开头钩子","audience":"创作者","core_point":"核心点","outline_1":"一","outline_2":"二",'
            '"outline_3":"三","cta":"评论区见","evidence_links":["https://example.com/1"],"risk_notes":"核对"}'
        )


class _BadProvider:
    name = "bad"
    model = "bad-1"

    def generate(self, prompt: str) -> str:
        return "{}"


class GenerationTests(unittest.TestCase):
    def test_retry_then_success(self):
        svc = OutlineGeneratorService(
            provider=_FlakyProvider(),
            prompt_template=load_prompt_template(PROJECT_ROOT / "prompts" / "short_video_outline.md"),
            max_retries=2,
        )
        row = {"cluster_id": "topic-1", "title_suggestion": "AI Agent 拆解", "summary": "summary", "total_score": 88}
        examples = [{"platform": "x", "title": "x", "url": "https://example.com/1", "body_text": "demo"}]
        draft = svc.generate_outline(row, examples)
        self.assertEqual(draft.status, "generated")
        self.assertEqual(draft.retry_count, 1)
        self.assertEqual(draft.evidence_links, ["https://example.com/1"])

    def test_failure_marks_needs_retry(self):
        svc = OutlineGeneratorService(
            provider=_BadProvider(),
            prompt_template=load_prompt_template(PROJECT_ROOT / "prompts" / "short_video_outline.md"),
            max_retries=1,
        )
        row = {"cluster_id": "topic-2", "title_suggestion": "AI News", "summary": "summary", "total_score": 71}
        draft = svc.generate_outline(row, [])
        self.assertEqual(draft.status, "needs_retry")
        self.assertIn("生成失败", draft.risk_notes)


if __name__ == "__main__":
    unittest.main()

