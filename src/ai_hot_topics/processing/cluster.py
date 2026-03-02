from __future__ import annotations

from dataclasses import dataclass, field

from ..models import NormalizedPost, TopicCluster
from ..utils import stable_hash, tokenize, unique_keep_order


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "you",
    "your",
    "from",
    "how",
    "what",
    "why",
    "are",
    "was",
    "can",
    "new",
    "best",
    "using",
    "use",
    "via",
    "about",
    "一个",
    "这个",
    "那个",
    "我们",
    "你们",
    "如何",
    "今天",
    "真的",
    "就是",
    "可以",
    "一下",
    "教程",
    "工具",
    "ai",
}


def _token_set(text: str) -> set[str]:
    return {t for t in tokenize(text) if t not in STOPWORDS and len(t) >= 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / max(len(a | b), 1)


def _char_ngrams(text: str, n: int = 2) -> set[str]:
    compact = "".join(ch.lower() for ch in text if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"))
    if len(compact) < n:
        return {compact} if compact else set()
    return {compact[i : i + n] for i in range(len(compact) - n + 1)}


@dataclass
class _ClusterBucket:
    posts: list[NormalizedPost] = field(default_factory=list)
    token_union: set[str] = field(default_factory=set)
    char_ngram_union: set[str] = field(default_factory=set)
    keyword_hits: list[str] = field(default_factory=list)


def cluster_posts(posts: list[NormalizedPost]) -> list[TopicCluster]:
    if not posts:
        return []
    ordered = sorted(
        posts,
        key=lambda p: (
            p.published_at.timestamp() if p.published_at else 0,
            sum(float(v) for v in p.metrics.values() if isinstance(v, (int, float))),
        ),
        reverse=True,
    )
    buckets: list[_ClusterBucket] = []
    for post in ordered:
        text_tokens = _token_set(post.combined_text)
        char_ngrams = _char_ngrams(post.combined_text)
        placed = False
        for bucket in buckets:
            token_similarity = _jaccard(text_tokens, bucket.token_union)
            char_similarity = _jaccard(char_ngrams, bucket.char_ngram_union)
            similarity = max(token_similarity, char_similarity)
            keyword_overlap = len(set(post.keyword_hits) & set(bucket.keyword_hits))
            if (
                similarity >= 0.22
                or post.content_fingerprint in {p.content_fingerprint for p in bucket.posts}
                or (keyword_overlap >= 2 and similarity >= 0.12)
                or (keyword_overlap >= 1 and similarity >= 0.35)
            ):
                bucket.posts.append(post)
                bucket.token_union |= text_tokens
                bucket.char_ngram_union |= char_ngrams
                bucket.keyword_hits = unique_keep_order([*bucket.keyword_hits, *post.keyword_hits])
                placed = True
                break
        if not placed:
            buckets.append(
                _ClusterBucket(
                    posts=[post],
                    token_union=set(text_tokens),
                    char_ngram_union=set(char_ngrams),
                    keyword_hits=list(post.keyword_hits),
                )
            )

    clusters: list[TopicCluster] = []
    for bucket in buckets:
        rep = bucket.posts[0]
        unique_platforms = {p.platform for p in bucket.posts}
        novelty_score = min(100.0, 40 + len(unique_platforms) * 15 + min(len(bucket.token_union), 20))
        representative_urls = unique_keep_order([p.url for p in bucket.posts[:5]])
        representative_post_refs = [(p.platform, p.platform_post_id) for p in bucket.posts[:5]]
        titles = [p.title.strip() for p in bucket.posts if p.title.strip()]
        title_suggestion = titles[0] if titles else rep.query
        summary = "；".join(titles[:3]) if titles else rep.combined_text[:240]
        cluster_seed = "|".join(sorted(representative_urls)[:3]) or f"{rep.platform}:{rep.platform_post_id}"
        cluster_id = f"topic-{stable_hash(cluster_seed, 18)}"
        clusters.append(
            TopicCluster(
                cluster_id=cluster_id,
                title_suggestion=title_suggestion[:160],
                summary=summary[:500],
                keyword_hits=unique_keep_order(bucket.keyword_hits),
                representative_urls=representative_urls,
                representative_post_refs=representative_post_refs,
                posts=bucket.posts,
                novelty_score=round(novelty_score, 2),
                candidate_status="candidate",
            )
        )
    return clusters
