from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .models import NormalizedPost, ScriptOutlineDraft, TopicCluster, TopicScoreBreakdown
from .utils import ensure_dir, isoformat_z, json_dumps, json_loads, now_utc, stable_hash


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS raw_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  source_id TEXT NOT NULL,
  query TEXT NOT NULL,
  platform_post_id TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT,
  text TEXT,
  author TEXT,
  published_at TEXT,
  language TEXT,
  metrics_json TEXT NOT NULL,
  raw_payload_json TEXT NOT NULL,
  collected_at TEXT NOT NULL,
  UNIQUE(platform, platform_post_id),
  UNIQUE(url)
);

CREATE TABLE IF NOT EXISTS normalized_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  source_id TEXT NOT NULL,
  query TEXT NOT NULL,
  platform_post_id TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT,
  body_text TEXT,
  author TEXT,
  published_at TEXT,
  language TEXT,
  metrics_json TEXT NOT NULL,
  keyword_hits_json TEXT NOT NULL,
  content_fingerprint TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(platform, platform_post_id),
  UNIQUE(url)
);

CREATE TABLE IF NOT EXISTS topic_clusters (
  cluster_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  title_suggestion TEXT NOT NULL,
  summary TEXT NOT NULL,
  keyword_hits_json TEXT NOT NULL,
  representative_urls_json TEXT NOT NULL,
  representative_post_refs_json TEXT NOT NULL,
  evidence_post_ids_json TEXT NOT NULL,
  novelty_score REAL NOT NULL,
  candidate_status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_scores (
  cluster_id TEXT PRIMARY KEY,
  hotness_score REAL NOT NULL,
  freshness_score REAL NOT NULL,
  reproducibility_score REAL NOT NULL,
  china_fit_score REAL NOT NULL,
  total_score REAL NOT NULL,
  penalties_json TEXT NOT NULL,
  weights_version TEXT NOT NULL,
  debug_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(cluster_id) REFERENCES topic_clusters(cluster_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS script_drafts (
  cluster_id TEXT PRIMARY KEY,
  hook TEXT,
  audience TEXT,
  core_point TEXT,
  outline_1 TEXT,
  outline_2 TEXT,
  outline_3 TEXT,
  cta TEXT,
  evidence_links_json TEXT NOT NULL,
  risk_notes TEXT,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  status TEXT NOT NULL,
  retry_count INTEGER NOT NULL DEFAULT 0,
  raw_output TEXT,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(cluster_id) REFERENCES topic_clusters(cluster_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS review_states (
  cluster_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  reviewer TEXT,
  reviewed_at TEXT,
  notes TEXT,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(cluster_id) REFERENCES topic_clusters(cluster_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS main_topic_library (
  cluster_id TEXT PRIMARY KEY,
  version INTEGER NOT NULL DEFAULT 1,
  promoted_at TEXT NOT NULL,
  execution_suggestion TEXT,
  snapshot_json TEXT NOT NULL,
  FOREIGN KEY(cluster_id) REFERENCES topic_clusters(cluster_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS run_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  platform TEXT,
  status TEXT NOT NULL,
  started_at TEXT,
  ended_at TEXT,
  duration_ms INTEGER,
  message TEXT,
  metrics_json TEXT NOT NULL
);
"""


class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        ensure_dir(self.db_path.parent)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self):
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def new_run_id(self, prefix: str = "run") -> str:
        now = now_utc()
        return f"{prefix}-{now.strftime('%Y%m%dT%H%M%SZ')}-{stable_hash(now.isoformat(), 8)}"

    def log_run(
        self,
        run_id: str,
        stage: str,
        status: str,
        *,
        platform: str | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        message: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        duration_ms = None
        if started_at and ended_at:
            duration_ms = int((ended_at - started_at).total_seconds() * 1000)
        self.conn.execute(
            """
            INSERT INTO run_logs (
              run_id, stage, platform, status, started_at, ended_at, duration_ms, message, metrics_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                stage,
                platform,
                status,
                isoformat_z(started_at),
                isoformat_z(ended_at),
                duration_ms,
                message,
                json_dumps(metrics or {}),
            ),
        )
        self.conn.commit()

    def upsert_raw_items(self, run_id: str, raw_items: Iterable[dict[str, Any]]) -> int:
        count = 0
        now = isoformat_z(now_utc())
        with self.transaction():
            for item in raw_items:
                self.conn.execute(
                    """
                    INSERT INTO raw_posts (
                      run_id, platform, source_id, query, platform_post_id, url, title, text, author,
                      published_at, language, metrics_json, raw_payload_json, collected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(platform, platform_post_id) DO UPDATE SET
                      run_id=excluded.run_id,
                      source_id=excluded.source_id,
                      query=excluded.query,
                      url=excluded.url,
                      title=excluded.title,
                      text=excluded.text,
                      author=excluded.author,
                      published_at=excluded.published_at,
                      language=excluded.language,
                      metrics_json=excluded.metrics_json,
                      raw_payload_json=excluded.raw_payload_json,
                      collected_at=excluded.collected_at
                    """,
                    (
                        run_id,
                        item["platform"],
                        item["source_id"],
                        item["query"],
                        item["platform_post_id"],
                        item["url"],
                        item.get("title", ""),
                        item.get("text", ""),
                        item.get("author", ""),
                        item.get("published_at"),
                        item.get("language", "und"),
                        json_dumps(item.get("metrics", {})),
                        json_dumps(item.get("raw_payload", {})),
                        item.get("collected_at") or now,
                    ),
                )
                count += 1
        return count

    def upsert_normalized_posts(self, run_id: str, posts: Iterable[NormalizedPost]) -> int:
        count = 0
        updated_at = isoformat_z(now_utc())
        with self.transaction():
            for post in posts:
                self.conn.execute(
                    """
                    INSERT INTO normalized_posts (
                      run_id, platform, source_id, query, platform_post_id, url, title, body_text, author,
                      published_at, language, metrics_json, keyword_hits_json, content_fingerprint, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(platform, platform_post_id) DO UPDATE SET
                      run_id=excluded.run_id,
                      source_id=excluded.source_id,
                      query=excluded.query,
                      url=excluded.url,
                      title=excluded.title,
                      body_text=excluded.body_text,
                      author=excluded.author,
                      published_at=excluded.published_at,
                      language=excluded.language,
                      metrics_json=excluded.metrics_json,
                      keyword_hits_json=excluded.keyword_hits_json,
                      content_fingerprint=excluded.content_fingerprint,
                      updated_at=excluded.updated_at
                    """,
                    (
                        run_id,
                        post.platform,
                        post.source_id,
                        post.query,
                        post.platform_post_id,
                        post.url,
                        post.title,
                        post.body_text,
                        post.author,
                        isoformat_z(post.published_at),
                        post.language,
                        json_dumps(post.metrics),
                        json_dumps(post.keyword_hits),
                        post.content_fingerprint,
                        updated_at,
                    ),
                )
                count += 1
        return count

    def fetch_recent_normalized_posts(self, since_hours: int = 72) -> list[sqlite3.Row]:
        # MVP 使用最近更新时间窗口，而不是复杂的增量游标。
        return list(
            self.conn.execute(
                """
                SELECT * FROM normalized_posts
                ORDER BY COALESCE(published_at, updated_at) DESC, updated_at DESC
                """
            )
        )

    def upsert_topic_clusters(self, run_id: str, clusters: Iterable[TopicCluster]) -> int:
        created_at = isoformat_z(now_utc())
        count = 0
        with self.transaction():
            for cluster in clusters:
                post_refs = [f"{p.platform}:{p.platform_post_id}" for p in cluster.posts]
                self.conn.execute(
                    """
                    INSERT INTO topic_clusters (
                      cluster_id, run_id, title_suggestion, summary, keyword_hits_json,
                      representative_urls_json, representative_post_refs_json, evidence_post_ids_json,
                      novelty_score, candidate_status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cluster_id) DO UPDATE SET
                      run_id=excluded.run_id,
                      title_suggestion=excluded.title_suggestion,
                      summary=excluded.summary,
                      keyword_hits_json=excluded.keyword_hits_json,
                      representative_urls_json=excluded.representative_urls_json,
                      representative_post_refs_json=excluded.representative_post_refs_json,
                      evidence_post_ids_json=excluded.evidence_post_ids_json,
                      novelty_score=excluded.novelty_score,
                      candidate_status=excluded.candidate_status,
                      updated_at=excluded.updated_at
                    """,
                    (
                        cluster.cluster_id,
                        run_id,
                        cluster.title_suggestion,
                        cluster.summary,
                        json_dumps(cluster.keyword_hits),
                        json_dumps(cluster.representative_urls),
                        json_dumps([f"{platform}:{pid}" for platform, pid in cluster.representative_post_refs]),
                        json_dumps(post_refs),
                        float(cluster.novelty_score),
                        cluster.candidate_status,
                        created_at,
                        created_at,
                    ),
                )
                self.conn.execute(
                    """
                    INSERT INTO review_states (cluster_id, status, updated_at)
                    VALUES (?, 'candidate', ?)
                    ON CONFLICT(cluster_id) DO NOTHING
                    """,
                    (cluster.cluster_id, created_at),
                )
                count += 1
        return count

    def upsert_topic_scores(self, scores: Iterable[TopicScoreBreakdown]) -> int:
        updated_at = isoformat_z(now_utc())
        count = 0
        with self.transaction():
            for score in scores:
                self.conn.execute(
                    """
                    INSERT INTO topic_scores (
                      cluster_id, hotness_score, freshness_score, reproducibility_score, china_fit_score,
                      total_score, penalties_json, weights_version, debug_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cluster_id) DO UPDATE SET
                      hotness_score=excluded.hotness_score,
                      freshness_score=excluded.freshness_score,
                      reproducibility_score=excluded.reproducibility_score,
                      china_fit_score=excluded.china_fit_score,
                      total_score=excluded.total_score,
                      penalties_json=excluded.penalties_json,
                      weights_version=excluded.weights_version,
                      debug_json=excluded.debug_json,
                      updated_at=excluded.updated_at
                    """,
                    (
                        score.cluster_id,
                        score.hotness_score,
                        score.freshness_score,
                        score.reproducibility_score,
                        score.china_fit_score,
                        score.total_score,
                        json_dumps(score.penalties),
                        score.weights_version,
                        json_dumps(score.debug),
                        updated_at,
                    ),
                )
                count += 1
        return count

    def upsert_script_drafts(self, drafts: Iterable[ScriptOutlineDraft]) -> int:
        updated_at = isoformat_z(now_utc())
        count = 0
        with self.transaction():
            for draft in drafts:
                self.conn.execute(
                    """
                    INSERT INTO script_drafts (
                      cluster_id, hook, audience, core_point, outline_1, outline_2, outline_3, cta,
                      evidence_links_json, risk_notes, provider, model, status, retry_count, raw_output, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cluster_id) DO UPDATE SET
                      hook=excluded.hook,
                      audience=excluded.audience,
                      core_point=excluded.core_point,
                      outline_1=excluded.outline_1,
                      outline_2=excluded.outline_2,
                      outline_3=excluded.outline_3,
                      cta=excluded.cta,
                      evidence_links_json=excluded.evidence_links_json,
                      risk_notes=excluded.risk_notes,
                      provider=excluded.provider,
                      model=excluded.model,
                      status=excluded.status,
                      retry_count=excluded.retry_count,
                      raw_output=excluded.raw_output,
                      updated_at=excluded.updated_at
                    """,
                    (
                        draft.cluster_id,
                        draft.hook,
                        draft.audience,
                        draft.core_point,
                        draft.outline_1,
                        draft.outline_2,
                        draft.outline_3,
                        draft.cta,
                        json_dumps(draft.evidence_links),
                        draft.risk_notes,
                        draft.provider,
                        draft.model,
                        draft.status,
                        draft.retry_count,
                        draft.raw_output,
                        updated_at,
                    ),
                )
                count += 1
        return count

    def fetch_clusters_for_generation(self, min_total_score: float, limit: int = 50) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT c.*, s.total_score, s.hotness_score, s.freshness_score, s.reproducibility_score,
                       s.china_fit_score, s.penalties_json,
                       d.cluster_id AS has_draft
                FROM topic_clusters c
                JOIN topic_scores s ON s.cluster_id = c.cluster_id
                LEFT JOIN script_drafts d ON d.cluster_id = c.cluster_id
                WHERE s.total_score >= ? AND (d.cluster_id IS NULL OR d.status IN ('needs_retry', 'failed'))
                ORDER BY s.total_score DESC, c.updated_at DESC
                LIMIT ?
                """,
                (min_total_score, limit),
            )
        )

    def fetch_cluster_posts(self, cluster_id: str) -> list[sqlite3.Row]:
        row = self.conn.execute(
            "SELECT evidence_post_ids_json FROM topic_clusters WHERE cluster_id = ?",
            (cluster_id,),
        ).fetchone()
        if row is None:
            return []
        refs = json_loads(row["evidence_post_ids_json"], default=[]) or []
        result: list[sqlite3.Row] = []
        for ref in refs:
            if ":" not in ref:
                continue
            platform, platform_post_id = ref.split(":", 1)
            item = self.conn.execute(
                """
                SELECT * FROM normalized_posts
                WHERE platform = ? AND platform_post_id = ?
                """,
                (platform, platform_post_id),
            ).fetchone()
            if item:
                result.append(item)
        return result

    def fetch_candidates_for_sync(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT c.cluster_id AS candidate_id, c.title_suggestion, c.summary, c.keyword_hits_json,
                       c.representative_urls_json, c.novelty_score, c.updated_at,
                       COALESCE(r.status, 'candidate') AS review_status,
                       r.notes AS review_notes,
                       s.hotness_score, s.freshness_score, s.reproducibility_score, s.china_fit_score, s.total_score,
                       d.hook, d.audience, d.core_point, d.outline_1, d.outline_2, d.outline_3, d.cta,
                       d.evidence_links_json, d.risk_notes, d.provider, d.model, d.status AS draft_status
                FROM topic_clusters c
                LEFT JOIN topic_scores s ON s.cluster_id = c.cluster_id
                LEFT JOIN script_drafts d ON d.cluster_id = c.cluster_id
                LEFT JOIN review_states r ON r.cluster_id = c.cluster_id
                ORDER BY COALESCE(s.total_score, 0) DESC, c.updated_at DESC
                """
            )
        )

    def apply_review_state_updates(self, updates: dict[str, dict[str, Any]]) -> int:
        updated_at = isoformat_z(now_utc())
        count = 0
        with self.transaction():
            for cluster_id, payload in updates.items():
                status = str(payload.get("status", "candidate"))
                reviewer = payload.get("reviewer")
                notes = payload.get("notes")
                reviewed_at = payload.get("reviewed_at")
                self.conn.execute(
                    """
                    INSERT INTO review_states (cluster_id, status, reviewer, reviewed_at, notes, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cluster_id) DO UPDATE SET
                      status=excluded.status,
                      reviewer=excluded.reviewer,
                      reviewed_at=excluded.reviewed_at,
                      notes=excluded.notes,
                      updated_at=excluded.updated_at
                    """,
                    (cluster_id, status, reviewer, reviewed_at, notes, updated_at),
                )
                count += 1
        return count

    def promote_approved_candidates(self) -> int:
        rows = list(
            self.conn.execute(
                """
                SELECT c.cluster_id, c.title_suggestion, c.summary, c.keyword_hits_json, c.representative_urls_json,
                       c.novelty_score, c.updated_at, s.total_score, d.hook, d.core_point, d.outline_1, d.outline_2,
                       d.outline_3, d.cta
                FROM topic_clusters c
                JOIN review_states r ON r.cluster_id = c.cluster_id
                LEFT JOIN topic_scores s ON s.cluster_id = c.cluster_id
                LEFT JOIN script_drafts d ON d.cluster_id = c.cluster_id
                WHERE r.status = 'approved'
                """
            )
        )
        promoted_at = isoformat_z(now_utc())
        count = 0
        with self.transaction():
            for row in rows:
                snapshot = {k: row[k] for k in row.keys()}
                self.conn.execute(
                    """
                    INSERT INTO main_topic_library (cluster_id, promoted_at, snapshot_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(cluster_id) DO UPDATE SET
                      promoted_at=excluded.promoted_at,
                      snapshot_json=excluded.snapshot_json,
                      version=main_topic_library.version + 1
                    """,
                    (row["cluster_id"], promoted_at, json_dumps(snapshot)),
                )
                count += 1
        return count

    def get_run_logs(self, run_id: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM run_logs WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            )
        )

    def get_summary_counts(self) -> dict[str, int]:
        tables = [
            "raw_posts",
            "normalized_posts",
            "topic_clusters",
            "topic_scores",
            "script_drafts",
            "main_topic_library",
        ]
        summary: dict[str, int] = {}
        for table in tables:
            row = self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            summary[table] = int(row["n"])
        return summary

    def fetch_top_candidate_ids(self, limit: int = 20) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT c.cluster_id
            FROM topic_clusters c
            LEFT JOIN topic_scores s ON s.cluster_id = c.cluster_id
            ORDER BY COALESCE(s.total_score, 0) DESC, c.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [str(r["cluster_id"]) for r in rows]

