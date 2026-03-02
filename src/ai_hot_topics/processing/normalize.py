from __future__ import annotations

from collections.abc import Iterable

from ..config import KeywordsConfig
from ..models import NormalizedPost, RawItem
from ..utils import stable_hash, tokenize, unique_keep_order


def _contains_any(text: str, patterns: list[str]) -> bool:
    lowered = text.lower()
    return any(p.lower() in lowered for p in patterns)


def _find_keyword_hits(text: str, keywords: list[str], hashtags: list[str]) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    for kw in [*keywords, *hashtags]:
        if kw.lower() in lowered:
            hits.append(kw)
    return unique_keep_order(hits)


def normalize_raw_item(raw: RawItem, keywords_cfg: KeywordsConfig) -> NormalizedPost | None:
    full_text = " ".join([raw.title or "", raw.text or ""]).strip()
    if not full_text:
        return None

    platform_keywords = keywords_cfg.keywords_for_platform(raw.platform)
    if keywords_cfg.exclude_keywords and _contains_any(full_text, keywords_cfg.exclude_keywords):
        return None

    keyword_hits = _find_keyword_hits(full_text, platform_keywords, keywords_cfg.include_hashtags)
    if not keyword_hits:
        # 第一版只保留命中关键词的内容，以降低噪音。
        return None

    token_stream = tokenize(full_text)
    fingerprint = stable_hash(" ".join(token_stream[:48]) or raw.url, 20)
    return NormalizedPost(
        platform=raw.platform,
        platform_post_id=raw.platform_post_id,
        url=raw.url,
        title=raw.title or "",
        body_text=raw.text or "",
        author=raw.author or "",
        published_at=raw.published_at,
        language=raw.language or keywords_cfg.language_hint,
        metrics=dict(raw.metrics or {}),
        keyword_hits=keyword_hits,
        source_id=raw.source_id,
        query=raw.query,
        content_fingerprint=fingerprint,
    )


def normalize_raw_items(raw_items: Iterable[RawItem], keywords_cfg: KeywordsConfig) -> list[NormalizedPost]:
    results: list[NormalizedPost] = []
    for item in raw_items:
        normalized = normalize_raw_item(item, keywords_cfg)
        if normalized:
            results.append(normalized)
    return results

