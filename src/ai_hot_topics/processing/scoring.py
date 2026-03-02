from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from ..config import ScoringConfig
from ..models import TopicCluster, TopicScoreBreakdown


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def _metric(metrics: dict[str, float | int], key: str) -> float:
    value = metrics.get(key, 0)
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _platform_hotness(post_metrics: dict[str, float | int], platform: str, cfg: ScoringConfig) -> float:
    norm = cfg.platform_normalization.get(platform, {})
    if not norm:
        total = sum(float(v) for v in post_metrics.values() if isinstance(v, (int, float)))
        return _clamp(math.log1p(total) * 10)

    score = 0.0
    weight_total = 0.0
    weights = {
        "views_scale": 0.25,
        "likes_scale": 0.35,
        "comments_scale": 0.25,
        "shares_scale": 0.15,
    }
    metric_name_map = {
        "views_scale": "views",
        "likes_scale": "likes",
        "comments_scale": "comments",
        "shares_scale": "shares",
    }
    for scale_key, scale in norm.items():
        if scale <= 0:
            continue
        metric_name = metric_name_map.get(scale_key)
        if not metric_name:
            continue
        metric_value = _metric(post_metrics, metric_name)
        weight = weights.get(scale_key, 0.1)
        part = min(metric_value / float(scale), 1.5) * 100
        score += part * weight
        weight_total += weight
    if weight_total == 0:
        return 0.0
    return _clamp(score / weight_total)


def _freshness_score(cluster: TopicCluster, hotness_score: float, now: datetime) -> float:
    ages: list[float] = []
    for post in cluster.posts:
        if not post.published_at:
            continue
        dt = post.published_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (now - dt.astimezone(timezone.utc)).total_seconds() / 3600)
        ages.append(age_hours)
    if not ages:
        return 35.0
    avg_age = sum(ages) / len(ages)
    recency = _clamp(100 - avg_age * 1.8)
    velocity = _clamp(hotness_score * (24 / max(avg_age + 4, 6)))
    return round(_clamp(recency * 0.7 + velocity * 0.3), 2)


REPRO_PATTERNS = [
    r"\bworkflow\b",
    r"\bprompt\b",
    r"\bcase\b",
    r"\btutorial\b",
    r"\bstep\b",
    r"教程",
    r"拆解",
    r"实测",
    r"清单",
    r"对比",
    r"方法",
    r"流程",
    r"模板",
]


def _reproducibility_score(cluster: TopicCluster, cfg: ScoringConfig) -> tuple[float, list[str]]:
    text = " ".join([cluster.title_suggestion, cluster.summary] + cluster.keyword_hits).lower()
    score = 35.0
    reasons: list[str] = []
    hit_count = 0
    for pattern in REPRO_PATTERNS:
        if re.search(pattern, text):
            hit_count += 1
    cfg_hits = sum(1 for kw in cfg.heuristics.get("reproducibility_keywords", []) if kw.lower() in text)
    hit_count += cfg_hits
    if hit_count:
        score += min(hit_count * 8, 40)
        reasons.append(f"repro_hits:{hit_count}")
    if any(ch.isdigit() for ch in text):
        score += 8
        reasons.append("has_numbers")
    if len(cluster.posts) >= 2:
        score += 8
        reasons.append("multi_examples")
    if len(cluster.representative_urls) >= 2:
        score += 5
        reasons.append("multiple_sources")
    return round(_clamp(score), 2), reasons


def _china_fit_score(cluster: TopicCluster, cfg: ScoringConfig) -> tuple[float, list[str]]:
    text = " ".join([cluster.title_suggestion, cluster.summary] + cluster.keyword_hits).lower()
    score = 30.0
    reasons: list[str] = []
    zh_ratio = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff") / max(len(text), 1)
    if zh_ratio > 0.15:
        score += 20
        reasons.append("zh_text")
    for kw in cfg.heuristics.get("china_fit_keywords", []):
        if kw.lower() in text:
            score += 7
            reasons.append(f"kw:{kw}")
    if any(post.platform in {"douyin", "xiaohongshu", "huitun"} for post in cluster.posts):
        score += 20
        reasons.append("cn_platform")
    if any(post.language.startswith("zh") for post in cluster.posts):
        score += 10
        reasons.append("zh_lang")
    return round(_clamp(score), 2), reasons


def _penalty_points(cluster: TopicCluster, cfg: ScoringConfig) -> tuple[float, list[str]]:
    text = " ".join([cluster.title_suggestion, cluster.summary]).lower()
    penalties: list[str] = []
    total = 0.0
    ad_markers = ["领取", "私信", "合作", "招商", "培训", "付费社群", "课程", "加v"]
    if sum(1 for marker in ad_markers if marker in text) >= 2:
        total += cfg.penalties.get("ad_like", 20.0)
        penalties.append("ad_like")
    if len(text) < 30:
        total += cfg.penalties.get("low_info_density", 10.0)
        penalties.append("low_info_density")
    if "搬运" in text or "转载" in text or "repost" in text:
        total += cfg.penalties.get("obvious_repost", 15.0)
        penalties.append("obvious_repost")
    return total, penalties


def score_cluster(cluster: TopicCluster, cfg: ScoringConfig, now: datetime | None = None) -> TopicScoreBreakdown:
    if now is None:
        now = datetime.now(timezone.utc)
    per_post_hotness = [
        _platform_hotness(post.metrics, post.platform, cfg)
        for post in cluster.posts
    ]
    hotness_score = round(_clamp(sum(per_post_hotness) / max(len(per_post_hotness), 1)), 2)
    freshness_score = _freshness_score(cluster, hotness_score, now)
    reproducibility_score, repro_reasons = _reproducibility_score(cluster, cfg)
    china_fit_score, china_reasons = _china_fit_score(cluster, cfg)
    penalty_points, penalties = _penalty_points(cluster, cfg)

    w = cfg.weights
    total = (
        hotness_score * w["hotness"]
        + freshness_score * w["freshness"]
        + reproducibility_score * w["reproducibility"]
        + china_fit_score * w["china_fit"]
        - penalty_points
    )
    total = round(_clamp(total), 2)

    return TopicScoreBreakdown(
        cluster_id=cluster.cluster_id,
        hotness_score=hotness_score,
        freshness_score=freshness_score,
        reproducibility_score=reproducibility_score,
        china_fit_score=china_fit_score,
        total_score=total,
        penalties=penalties,
        weights_version=cfg.weights_version,
        debug={
            "per_post_hotness": per_post_hotness,
            "repro_reasons": repro_reasons,
            "china_reasons": china_reasons,
            "penalty_points": penalty_points,
        },
    )


def score_clusters(clusters: list[TopicCluster], cfg: ScoringConfig) -> list[TopicScoreBreakdown]:
    now = datetime.now(timezone.utc)
    return [score_cluster(cluster, cfg, now=now) for cluster in clusters]
