from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import ScriptOutlineDraft
from ..utils import json_loads
from .base import LLMProvider
from .mock_provider import MockLLMProvider
from .openai_provider import OpenAICompatibleProvider


REQUIRED_KEYS = {
    "hook",
    "audience",
    "core_point",
    "outline_1",
    "outline_2",
    "outline_3",
    "cta",
    "evidence_links",
    "risk_notes",
}


@dataclass
class OutlineGeneratorService:
    provider: LLMProvider
    prompt_template: str
    max_retries: int = 2

    def _render_prompt(self, cluster_row: dict[str, Any], example_posts: list[dict[str, Any]]) -> str:
        examples_lines: list[str] = []
        for idx, post in enumerate(example_posts[:5], start=1):
            examples_lines.append(
                f"{idx}. [{post.get('platform')}] {post.get('title') or ''}\n"
                f"   链接: {post.get('url')}\n"
                f"   摘要: {(post.get('body_text') or '')[:180]}"
            )
        prompt = self.prompt_template
        replacements = {
            "{{topic_title}}": str(cluster_row.get("title_suggestion") or ""),
            "{{topic_summary}}": str(cluster_row.get("summary") or ""),
            "{{total_score}}": str(cluster_row.get("total_score") or ""),
            "{{examples}}": "\n".join(examples_lines) if examples_lines else "无",
        }
        for key, value in replacements.items():
            prompt = prompt.replace(key, value)
        return prompt

    def _extract_json(self, text: str) -> dict[str, Any]:
        text = text.strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            snippet = text[start : end + 1]
            data = json_loads(snippet, default={})
            if isinstance(data, dict):
                return data
        raise ValueError("LLM output is not valid JSON object")

    def _validate_payload(self, payload: dict[str, Any], evidence_links: list[str]) -> dict[str, Any]:
        missing = REQUIRED_KEYS - set(payload.keys())
        if missing:
            raise ValueError(f"Missing keys: {sorted(missing)}")
        normalized = dict(payload)
        links = normalized.get("evidence_links")
        if not isinstance(links, list):
            raise ValueError("evidence_links must be a list")
        allowed = set(evidence_links)
        filtered_links = [str(link) for link in links if str(link) in allowed]
        normalized["evidence_links"] = filtered_links or evidence_links[:3]
        for key in REQUIRED_KEYS - {"evidence_links"}:
            normalized[key] = str(normalized.get(key, "")).strip()
        return normalized

    def generate_outline(self, cluster_row: dict[str, Any], example_posts: list[dict[str, Any]]) -> ScriptOutlineDraft:
        prompt = self._render_prompt(cluster_row, example_posts)
        evidence_links = [str(p.get("url")) for p in example_posts if p.get("url")]
        last_raw = ""
        for attempt in range(self.max_retries + 1):
            try:
                raw_output = self.provider.generate(prompt)
                last_raw = raw_output
                payload = self._extract_json(raw_output)
                payload = self._validate_payload(payload, evidence_links)
                return ScriptOutlineDraft(
                    cluster_id=str(cluster_row["cluster_id"]),
                    hook=payload["hook"],
                    audience=payload["audience"],
                    core_point=payload["core_point"],
                    outline_1=payload["outline_1"],
                    outline_2=payload["outline_2"],
                    outline_3=payload["outline_3"],
                    cta=payload["cta"],
                    evidence_links=payload["evidence_links"],
                    risk_notes=payload["risk_notes"],
                    provider=self.provider.name,
                    model=self.provider.model,
                    status="generated",
                    retry_count=attempt,
                    raw_output=raw_output,
                )
            except Exception as exc:
                if attempt >= self.max_retries:
                    return ScriptOutlineDraft(
                        cluster_id=str(cluster_row["cluster_id"]),
                        hook="",
                        audience="",
                        core_point="",
                        outline_1="",
                        outline_2="",
                        outline_3="",
                        cta="",
                        evidence_links=evidence_links[:3],
                        risk_notes=f"生成失败：{exc}",
                        provider=self.provider.name,
                        model=self.provider.model,
                        status="needs_retry",
                        retry_count=attempt,
                        raw_output=last_raw or str(exc),
                    )
        raise AssertionError("unreachable")


def load_prompt_template(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_outline_generator(env: dict[str, str], prompt_file: Path) -> OutlineGeneratorService:
    provider_name = (env.get("LLM_PROVIDER") or "mock").strip().lower()
    model = (env.get("LLM_MODEL") or "gpt-4o-mini").strip()
    provider: LLMProvider
    if provider_name == "mock":
        provider = MockLLMProvider(model=model)
    else:
        api_key = (
            env.get("OPENAI_API_KEY")
            or env.get("DEEPSEEK_API_KEY")
            or env.get("QWEN_API_KEY")
            or ""
        ).strip()
        if not api_key:
            provider = MockLLMProvider(model="mock-fallback-no-key")
        else:
            base_url = (env.get("LLM_BASE_URL") or "https://api.openai.com/v1").strip()
            provider = OpenAICompatibleProvider(base_url=base_url, api_key=api_key, model=model)
    return OutlineGeneratorService(provider=provider, prompt_template=load_prompt_template(prompt_file))
