from __future__ import annotations

import json


class MockLLMProvider:
    name = "mock"

    def __init__(self, model: str = "mock-outline-v1"):
        self.model = model

    def generate(self, prompt: str) -> str:
        topic_line = ""
        for line in prompt.splitlines():
            if line.startswith("主题标题："):
                topic_line = line.split("：", 1)[1].strip()
                break
        payload = {
            "hook": f"今天聊一个值得你马上跟拍的 AI 选题：{topic_line[:36]}",
            "audience": "想做中文 AI 内容但缺稳定选题的创作者",
            "core_point": "把海外/全网热点拆成可复用的中文短视频表达框架",
            "outline_1": "先讲这个主题为什么突然火：平台热度、讨论焦点、代表案例",
            "outline_2": "再拆可复制方法：工具、步骤、适用场景、常见误区",
            "outline_3": "最后给出中文落地版本：适合谁做、怎么改写、如何差异化",
            "cta": "评论区回复“选题库”，我继续更新这一类 AI 爆款方向",
            "evidence_links": [],
            "risk_notes": "mock 模型生成，仅作流程验证，发布前请人工核对事实和链接",
        }
        return json.dumps(payload, ensure_ascii=False)

