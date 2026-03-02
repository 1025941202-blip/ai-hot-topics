from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


PlatformName = str


@dataclass
class RawItem:
    platform: PlatformName
    source_id: str
    query: str
    platform_post_id: str
    url: str
    title: str
    text: str
    author: str
    published_at: datetime | None
    metrics: dict[str, float | int]
    language: str
    raw_payload: dict[str, Any] = field(default_factory=dict)
    collected_at: datetime | None = None


@dataclass
class NormalizedPost:
    platform: PlatformName
    platform_post_id: str
    url: str
    title: str
    body_text: str
    author: str
    published_at: datetime | None
    language: str
    metrics: dict[str, float | int]
    keyword_hits: list[str]
    source_id: str
    query: str
    content_fingerprint: str

    @property
    def combined_text(self) -> str:
        return " ".join([self.title or "", self.body_text or ""]).strip()


@dataclass
class TopicCluster:
    cluster_id: str
    title_suggestion: str
    summary: str
    keyword_hits: list[str]
    representative_urls: list[str]
    representative_post_refs: list[tuple[str, str]]
    posts: list[NormalizedPost]
    novelty_score: float
    candidate_status: str = "candidate"


@dataclass
class TopicScoreBreakdown:
    cluster_id: str
    hotness_score: float
    freshness_score: float
    reproducibility_score: float
    china_fit_score: float
    total_score: float
    penalties: list[str] = field(default_factory=list)
    weights_version: str = "v1"
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScriptOutlineDraft:
    cluster_id: str
    hook: str
    audience: str
    core_point: str
    outline_1: str
    outline_2: str
    outline_3: str
    cta: str
    evidence_links: list[str]
    risk_notes: str
    provider: str
    model: str
    status: str
    retry_count: int = 0
    raw_output: str | None = None


@dataclass
class SourceEntry:
    id: str
    name: str
    url: str
    category: str
    language: str
    region: str | None
    status: str
    priority: int
    notes: str | None
    added_at: str


@dataclass
class RunSummary:
    run_id: str
    raw_count: int
    normalized_count: int
    cluster_count: int
    generated_count: int
    approved_promoted: int
