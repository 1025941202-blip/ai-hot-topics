from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .utils import json_loads, now_utc


ALLOWED_REVIEW_STATUS = {"candidate", "approved", "rejected"}
REVIEW_STATUS_ALIASES = {
    "candidate": "candidate",
    "pending": "candidate",
    "待处理": "candidate",
    "待审核": "candidate",
    "approved": "approved",
    "pass": "approved",
    "已通过": "approved",
    "rejected": "rejected",
    "reject": "rejected",
    "已拒绝": "rejected",
}
REVIEW_STATUS_LABELS = {
    "candidate": "待处理",
    "approved": "已通过",
    "rejected": "已拒绝",
}
SORT_FIELD_ALIASES = {
    "likes": "like_count",
    "like": "like_count",
    "like_count": "like_count",
    "点赞": "like_count",
    "favorites": "favorite_count",
    "favorite": "favorite_count",
    "fav": "favorite_count",
    "favorite_count": "favorite_count",
    "收藏": "favorite_count",
    "comments": "comment_count",
    "comment": "comment_count",
    "comment_count": "comment_count",
    "评论": "comment_count",
    "shares": "share_count",
    "share": "share_count",
    "share_count": "share_count",
    "分享": "share_count",
    "views": "view_count",
    "view": "view_count",
    "view_count": "view_count",
    "阅读": "view_count",
}
SORT_ORDER_ALIASES = {
    "desc": "desc",
    "descending": "desc",
    "降序": "desc",
    "asc": "asc",
    "ascending": "asc",
    "升序": "asc",
}


@dataclass
class DashboardService:
    db_path: Path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def fetch_summary(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            total_posts = _count(conn, "SELECT COUNT(*) AS n FROM normalized_posts")
            total_clusters = _count(conn, "SELECT COUNT(*) AS n FROM topic_clusters")
            approved = _count(
                conn,
                "SELECT COUNT(*) AS n FROM review_states WHERE status='approved'",
            )
            generated_drafts = _count(
                conn,
                "SELECT COUNT(*) AS n FROM script_drafts WHERE status='generated'",
            )
            xiaohongshu_posts = _count(
                conn,
                "SELECT COUNT(*) AS n FROM normalized_posts WHERE platform='xiaohongshu'",
            )
            huitun_posts = _count(
                conn,
                "SELECT COUNT(*) AS n FROM normalized_posts WHERE platform='huitun'",
            )
            row = conn.execute(
                """
                SELECT MAX(updated_at) AS max_updated_at
                FROM topic_clusters
                """
            ).fetchone()
            by_platform_rows = conn.execute(
                """
                SELECT platform, COUNT(*) AS n
                FROM normalized_posts
                GROUP BY platform
                ORDER BY n DESC
                """
            ).fetchall()
            return {
                "total_posts": total_posts,
                "total_candidates": total_clusters,
                "approved_candidates": approved,
                "generated_drafts": generated_drafts,
                "xiaohongshu_posts": xiaohongshu_posts,
                "huitun_posts": huitun_posts,
                "last_updated_at": row["max_updated_at"] if row else None,
                "by_platform": [
                    {"platform": str(r["platform"]), "count": int(r["n"])} for r in by_platform_rows
                ],
            }
        finally:
            conn.close()

    def fetch_candidates(
        self,
        *,
        platform: str = "",
        min_score: float = 0.0,
        limit: int = 200,
        review_status: str = "",
        query: str = "",
        sort_by: str = "",
        sort_order: str = "desc",
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            limit = max(1, min(int(limit), 500))
            min_score = float(min_score)
            platform = platform.strip().lower()
            normalized_review_status = _normalize_review_status(review_status)
            if review_status and not normalized_review_status:
                return []
            sort_metric = _normalize_sort_field(sort_by)
            normalized_sort_order = _normalize_sort_order(sort_order)
            sql_limit = 500 if sort_metric else limit
            like_query = f"%{query.strip()}%" if query.strip() else ""
            rows = conn.execute(
                """
                SELECT
                  c.cluster_id AS candidate_id,
                  c.title_suggestion,
                  c.summary,
                  c.keyword_hits_json,
                  c.representative_urls_json,
                  c.representative_post_refs_json,
                  c.updated_at,
                  COALESCE(r.status, 'candidate') AS review_status,
                  COALESCE(r.notes, '') AS review_notes,
                  COALESCE(s.total_score, 0) AS total_score,
                  COALESCE(s.hotness_score, 0) AS hotness_score,
                  COALESCE(s.freshness_score, 0) AS freshness_score,
                  COALESCE(s.reproducibility_score, 0) AS reproducibility_score,
                  COALESCE(s.china_fit_score, 0) AS china_fit_score,
                  COALESCE(d.status, '') AS draft_status
                FROM topic_clusters c
                LEFT JOIN topic_scores s ON s.cluster_id = c.cluster_id
                LEFT JOIN review_states r ON r.cluster_id = c.cluster_id
                LEFT JOIN script_drafts d ON d.cluster_id = c.cluster_id
                WHERE COALESCE(s.total_score, 0) >= ?
                  AND (? = '' OR COALESCE(r.status, 'candidate') = ?)
                  AND (? = '' OR c.representative_post_refs_json LIKE '%' || ? || ':%')
                  AND (
                    ? = ''
                    OR c.title_suggestion LIKE ?
                    OR c.summary LIKE ?
                  )
                ORDER BY COALESCE(s.total_score, 0) DESC, c.updated_at DESC
                LIMIT ?
                """,
                (
                    min_score,
                    normalized_review_status,
                    normalized_review_status,
                    platform,
                    platform,
                    like_query,
                    like_query,
                    like_query,
                    sql_limit,
                ),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["keyword_hits"] = json_loads(item.pop("keyword_hits_json"), default=[]) or []
                item["representative_urls"] = (
                    json_loads(item.pop("representative_urls_json"), default=[]) or []
                )
                refs = json_loads(item.pop("representative_post_refs_json"), default=[]) or []
                item["platforms"] = sorted(
                    {ref.split(":", 1)[0] for ref in refs if isinstance(ref, str) and ":" in ref}
                )
                item["review_status_text"] = REVIEW_STATUS_LABELS.get(
                    str(item.get("review_status") or ""),
                    "待处理",
                )
                primary_ref = _pick_primary_ref(refs, preferred_platform=platform)
                item.update(self._fetch_post_context(conn, primary_ref))
                result.append(item)
            if sort_metric:
                reverse = normalized_sort_order == "desc"
                result.sort(
                    key=lambda row: (
                        _to_int(row.get(sort_metric)),
                        float(row.get("total_score") or 0),
                    ),
                    reverse=reverse,
                )
                result = result[:limit]
            return result
        finally:
            conn.close()

    def update_review_state(
        self,
        *,
        candidate_id: str,
        status: str,
        reviewer: str = "",
        notes: str = "",
    ) -> None:
        status = _normalize_review_status(status)
        if status not in ALLOWED_REVIEW_STATUS:
            raise ValueError(f"Invalid status: {status}")
        candidate_id = candidate_id.strip()
        if not candidate_id:
            raise ValueError("candidate_id is required")
        conn = self._connect()
        try:
            now = now_utc().isoformat().replace("+00:00", "Z")
            conn.execute(
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
                (candidate_id, status, reviewer or None, now, notes or None, now),
            )
            conn.commit()
        finally:
            conn.close()

    def _fetch_post_context(self, conn: sqlite3.Connection, ref: str | None) -> dict[str, Any]:
        default = {
            "note_url": "",
            "note_title": "",
            "note_published_at": "",
            "note_publish_time_text": "",
            "view_count": 0,
            "like_count": 0,
            "favorite_count": 0,
            "comment_count": 0,
            "share_count": 0,
            "author_name": "",
            "author_avatar": "",
            "author_bio": "",
            "author_fans_count": 0,
            "author_follows_count": 0,
            "author_likes_collects_count": 0,
            "author_profile_url": "",
        }
        if not ref or ":" not in ref:
            return default
        platform, platform_post_id = ref.split(":", 1)
        row = conn.execute(
            """
            SELECT
              n.url,
              n.title,
              n.author,
              n.published_at,
              n.metrics_json AS normalized_metrics_json,
              r.metrics_json AS raw_metrics_json,
              r.raw_payload_json
            FROM normalized_posts n
            LEFT JOIN raw_posts r
              ON r.platform = n.platform AND r.platform_post_id = n.platform_post_id
            WHERE n.platform = ? AND n.platform_post_id = ?
            LIMIT 1
            """,
            (platform, platform_post_id),
        ).fetchone()
        if not row:
            return default

        normalized_metrics = json_loads(row["normalized_metrics_json"], default={}) or {}
        raw_metrics = json_loads(row["raw_metrics_json"], default={}) or {}
        if not isinstance(normalized_metrics, dict):
            normalized_metrics = {}
        if not isinstance(raw_metrics, dict):
            raw_metrics = {}
        raw_payload = json_loads(row["raw_payload_json"], default={}) or {}
        if not isinstance(raw_payload, dict):
            raw_payload = {}
        author_profile = raw_payload.get("author_profile")
        if not isinstance(author_profile, dict):
            author_profile = {}

        note_url = str(row["url"] or "")
        note_title = str(row["title"] or "")
        note_published_at = str(row["published_at"] or "")
        note_publish_time_text = str(raw_payload.get("publish_time_text") or "")

        author_name = str(raw_payload.get("author_name") or row["author"] or "")
        author_avatar = str(raw_payload.get("author_avatar") or author_profile.get("avatar") or "")
        author_bio = str(author_profile.get("bio") or "")
        author_profile_url = str(raw_payload.get("author_profile_url") or "")

        return {
            "note_url": note_url,
            "note_title": note_title,
            "note_published_at": note_published_at,
            "note_publish_time_text": note_publish_time_text,
            "view_count": _metric_value("views", normalized_metrics, raw_metrics),
            "like_count": _metric_value("likes", normalized_metrics, raw_metrics),
            "favorite_count": _metric_value("favorites", normalized_metrics, raw_metrics),
            "comment_count": _metric_value("comments", normalized_metrics, raw_metrics),
            "share_count": _metric_value("shares", normalized_metrics, raw_metrics),
            "author_name": author_name,
            "author_avatar": author_avatar,
            "author_bio": author_bio,
            "author_fans_count": _to_int(author_profile.get("fans_count")),
            "author_follows_count": _to_int(author_profile.get("follows_count")),
            "author_likes_collects_count": _to_int(author_profile.get("likes_and_collects_count")),
            "author_profile_url": author_profile_url,
        }


def _count(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    if not row:
        return 0
    return int(row["n"])


def _normalize_review_status(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    return REVIEW_STATUS_ALIASES.get(normalized, "")


def _normalize_sort_field(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    return SORT_FIELD_ALIASES.get(normalized, "")


def _normalize_sort_order(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "desc"
    return SORT_ORDER_ALIASES.get(normalized, "desc")


def _pick_primary_ref(refs: list[Any], preferred_platform: str = "") -> str | None:
    normalized_refs = [ref for ref in refs if isinstance(ref, str) and ":" in ref]
    if not normalized_refs:
        return None
    if preferred_platform:
        for ref in normalized_refs:
            if ref.startswith(f"{preferred_platform}:"):
                return ref
    for ref in normalized_refs:
        if ref.startswith("xiaohongshu:"):
            return ref
    return normalized_refs[0]


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _metric_value(key: str, *metric_maps: dict[str, Any]) -> int:
    for data in metric_maps:
        value = _to_int(data.get(key))
        if value > 0:
            return value
    return 0


def _dashboard_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI 选题看板</title>
  <style>
    :root {
      --bg: #f3f5f8;
      --card: #ffffff;
      --text: #1f2937;
      --muted: #6b7280;
      --accent: #0f766e;
      --accent-soft: #ccfbf1;
      --border: #e5e7eb;
      --good: #15803d;
      --warn: #b45309;
      --bad: #b91c1c;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: radial-gradient(circle at 10% 10%, #d1fae5 0%, #f3f5f8 35%) fixed;
      color: var(--text);
      font-family: "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
    }
    .container { max-width: 1240px; margin: 0 auto; padding: 24px; }
    .header {
      display: flex; align-items: center; justify-content: space-between;
      gap: 16px; margin-bottom: 20px;
    }
    .title-wrap h1 { margin: 0; font-size: 26px; font-weight: 700; letter-spacing: 0.4px; }
    .title-wrap p { margin: 6px 0 0; color: var(--muted); }
    .pill {
      background: var(--accent-soft); color: #115e59; border: 1px solid #99f6e4;
      border-radius: 999px; padding: 8px 12px; font-size: 13px; font-weight: 600;
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .summary-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px 16px;
    }
    .summary-card .label { color: var(--muted); font-size: 12px; }
    .summary-card .value { margin-top: 6px; font-size: 28px; font-weight: 700; }
    .toolbar {
      display: grid;
      grid-template-columns: 1fr 150px 120px 150px 140px 110px 100px;
      gap: 8px;
      margin-bottom: 16px;
    }
    .toolbar input, .toolbar select, .toolbar button {
      border: 1px solid var(--border);
      background: #fff;
      border-radius: 10px;
      padding: 9px 10px;
      font-size: 14px;
    }
    .toolbar button {
      background: linear-gradient(90deg, #0f766e, #0d9488);
      color: #fff;
      border: none;
      font-weight: 600;
      cursor: pointer;
    }
    .board {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
      gap: 12px;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
      box-shadow: 0 1px 4px rgba(15, 23, 42, 0.03);
    }
    .card h3 { margin: 0 0 8px; font-size: 16px; line-height: 1.45; }
    .meta { font-size: 12px; color: var(--muted); margin-bottom: 8px; }
    .author-row {
      display: grid;
      grid-template-columns: 48px 1fr;
      gap: 10px;
      margin-bottom: 10px;
      align-items: start;
    }
    .avatar {
      width: 48px;
      height: 48px;
      border-radius: 999px;
      object-fit: cover;
      border: 1px solid var(--border);
      background: #f3f4f6;
    }
    .avatar-fallback {
      width: 48px;
      height: 48px;
      border-radius: 999px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #e2e8f0;
      color: #334155;
      font-weight: 700;
      border: 1px solid var(--border);
      font-size: 15px;
    }
    .author-name {
      margin: 0 0 4px;
      font-size: 14px;
      font-weight: 700;
      line-height: 1.25;
    }
    .author-stats {
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 4px;
    }
    .author-bio {
      color: #4b5563;
      font-size: 12px;
      line-height: 1.35;
      max-height: 34px;
      overflow: hidden;
    }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 6px;
      margin-bottom: 8px;
    }
    .metric-item {
      border: 1px solid var(--border);
      background: #f8fafc;
      border-radius: 10px;
      padding: 6px 7px;
    }
    .metric-label {
      color: var(--muted);
      font-size: 11px;
      line-height: 1;
      margin-bottom: 5px;
    }
    .metric-value {
      font-size: 14px;
      font-weight: 700;
      color: #0f172a;
      line-height: 1.1;
    }
    .badges { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
    .badge {
      border-radius: 999px; padding: 3px 8px; font-size: 12px; border: 1px solid var(--border);
      background: #f9fafb;
    }
    .links { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
    .links a {
      font-size: 12px; color: #0f766e; text-decoration: none;
      background: #ecfeff; padding: 3px 8px; border-radius: 999px;
      border: 1px solid #bae6fd;
    }
    .review-row {
      display: grid;
      grid-template-columns: 1fr 1fr auto;
      gap: 8px;
      margin-top: 8px;
    }
    .review-row button {
      border: none; border-radius: 10px; padding: 8px 10px;
      background: #111827; color: #fff; cursor: pointer;
      font-size: 13px;
    }
    .status-candidate { color: var(--warn); }
    .status-approved { color: var(--good); }
    .status-rejected { color: var(--bad); }
    .empty {
      background: #fff; border: 1px dashed #d1d5db; border-radius: 14px; padding: 24px;
      text-align: center; color: #6b7280;
    }
    @media (max-width: 960px) {
      .toolbar {
        grid-template-columns: 1fr 1fr;
      }
      .metric-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="title-wrap">
        <h1>AI 爆款选题看板</h1>
        <p>先聚焦小红书，支持审核流转，后续可一键同步飞书</p>
      </div>
      <div class="pill" id="lastUpdated">最近更新：-</div>
    </div>
    <div class="summary-grid" id="summary"></div>
    <div class="toolbar">
      <input id="q" placeholder="搜标题/摘要关键词，例如：AI工具、工作流" />
      <select id="platform">
        <option value="">全部平台</option>
        <option value="xiaohongshu" selected>小红书</option>
        <option value="huitun">灰豚</option>
        <option value="douyin">抖音</option>
        <option value="x">X</option>
        <option value="youtube">YouTube</option>
      </select>
      <input id="minScore" type="number" value="0" min="0" max="100" step="1" placeholder="最低总分(可选)" />
      <select id="reviewStatus">
        <option value="">全部状态</option>
        <option value="candidate">待处理</option>
        <option value="approved">已通过</option>
        <option value="rejected">已拒绝</option>
      </select>
      <select id="sortBy">
        <option value="">默认排序</option>
        <option value="likes">按点赞</option>
        <option value="favorites">按收藏</option>
        <option value="comments">按评论</option>
      </select>
      <select id="sortOrder">
        <option value="desc">降序</option>
        <option value="asc">升序</option>
      </select>
      <button id="refreshBtn">刷新</button>
    </div>
    <div class="board" id="board"></div>
  </div>
  <script>
    const boardEl = document.getElementById("board");
    const summaryEl = document.getElementById("summary");
    const lastUpdatedEl = document.getElementById("lastUpdated");
    const qEl = document.getElementById("q");
    const platformEl = document.getElementById("platform");
    const minScoreEl = document.getElementById("minScore");
    const reviewStatusEl = document.getElementById("reviewStatus");
    const sortByEl = document.getElementById("sortBy");
    const sortOrderEl = document.getElementById("sortOrder");
    const refreshBtn = document.getElementById("refreshBtn");
    const STATUS_LABELS = {
      candidate: "待处理",
      approved: "已通过",
      rejected: "已拒绝",
    };

    async function fetchJSON(url, options = {}) {
      const resp = await fetch(url, options);
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `HTTP ${resp.status}`);
      }
      return await resp.json();
    }

    function statusClass(value) {
      if (value === "approved") return "status-approved";
      if (value === "rejected") return "status-rejected";
      return "status-candidate";
    }

    function statusLabel(value) {
      return STATUS_LABELS[value] || STATUS_LABELS.candidate;
    }

    function escapeHtml(value) {
      return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function formatCount(value) {
      const n = Number(value || 0);
      if (!Number.isFinite(n) || n <= 0) return "0";
      if (n >= 100000000) return `${(n / 100000000).toFixed(1).replace(/\\.0$/, "")}亿`;
      if (n >= 10000) return `${(n / 10000).toFixed(1).replace(/\\.0$/, "")}万`;
      return String(Math.round(n));
    }

    function pickAvatar(row) {
      const avatar = String(row.author_avatar || "").trim();
      if (!avatar) {
        const name = String(row.author_name || "").trim();
        const fallback = escapeHtml(name ? name.slice(0, 1) : "博");
        return `<div class="avatar-fallback">${fallback}</div>`;
      }
      const name = escapeHtml(row.author_name || "博主");
      return `<img class="avatar" src="${escapeHtml(avatar)}" alt="${name}" />`;
    }

    function displayPublishTime(row) {
      if (row.note_publish_time_text) return String(row.note_publish_time_text);
      if (!row.note_published_at) return "-";
      return String(row.note_published_at).replace("T", " ").replace("Z", "");
    }

    function renderSummary(data) {
      const cards = [
        ["总候选", data.total_candidates || 0],
        ["小红书内容", data.xiaohongshu_posts || 0],
        ["灰豚内容", data.huitun_posts || 0],
        ["总内容", data.total_posts || 0],
        ["已通过", data.approved_candidates || 0],
        ["脚本草稿", data.generated_drafts || 0],
      ];
      summaryEl.innerHTML = cards.map(([label, value]) =>
        `<div class="summary-card"><div class="label">${label}</div><div class="value">${value}</div></div>`
      ).join("");
      lastUpdatedEl.textContent = `最近更新：${data.last_updated_at || "-"}`;
    }

    function renderCandidates(rows) {
      if (!rows.length) {
        boardEl.innerHTML = `<div class="empty">当前筛选条件下暂无候选，尝试修改关键词或状态筛选。</div>`;
        return;
      }
      boardEl.innerHTML = rows.map(row => {
        const links = (row.representative_urls || []).slice(0, 4)
          .map(url => `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">来源链接</a>`).join("");
        const keywords = (row.keyword_hits || []).slice(0, 6)
          .map(x => `<span class="badge">${escapeHtml(x)}</span>`).join("");
        const platforms = (row.platforms || []).map(p => `<span class="badge">${escapeHtml(p)}</span>`).join("");
        const status = row.review_status || "candidate";
        const statusText = statusLabel(status);
        const notePublishedText = displayPublishTime(row);
        const authorFans = formatCount(row.author_fans_count || 0);
        const authorName = escapeHtml(row.author_name || row.author || "未知博主");
        const authorBio = escapeHtml((row.author_bio || "").slice(0, 80));
        return `
          <div class="card">
            <h3>${escapeHtml(row.title_suggestion || "未命名主题")}</h3>
            <div class="meta">${escapeHtml((row.summary || "").slice(0, 120))}</div>
            <div class="author-row">
              ${pickAvatar(row)}
              <div>
                <div class="author-name">${authorName}</div>
                <div class="author-stats">粉丝 ${authorFans}</div>
                <div class="author-bio">${authorBio || "暂无博主简介"}</div>
              </div>
            </div>
            <div class="metric-grid">
              <div class="metric-item"><div class="metric-label">阅读</div><div class="metric-value">${formatCount(row.view_count)}</div></div>
              <div class="metric-item"><div class="metric-label">点赞</div><div class="metric-value">${formatCount(row.like_count)}</div></div>
              <div class="metric-item"><div class="metric-label">收藏</div><div class="metric-value">${formatCount(row.favorite_count)}</div></div>
              <div class="metric-item"><div class="metric-label">评论</div><div class="metric-value">${formatCount(row.comment_count)}</div></div>
              <div class="metric-item"><div class="metric-label">分享</div><div class="metric-value">${formatCount(row.share_count)}</div></div>
            </div>
            <div class="meta">发布时间：${escapeHtml(notePublishedText)}</div>
            <div class="badges">${platforms}${keywords}</div>
            <div class="links">${links}</div>
            <div class="meta">状态：<strong class="${statusClass(status)}">${statusText}</strong></div>
            <div class="review-row">
              <select data-id="${row.candidate_id}" class="statusSelect">
                <option value="candidate" ${status === "candidate" ? "selected" : ""}>待处理</option>
                <option value="approved" ${status === "approved" ? "selected" : ""}>已通过</option>
                <option value="rejected" ${status === "rejected" ? "selected" : ""}>已拒绝</option>
              </select>
              <input data-id="${row.candidate_id}" class="noteInput" placeholder="审核备注（可选）" value="${escapeHtml(row.review_notes || "")}" />
              <button data-id="${row.candidate_id}" class="saveBtn">保存</button>
            </div>
          </div>
        `;
      }).join("");

      document.querySelectorAll(".saveBtn").forEach(btn => {
        btn.addEventListener("click", async () => {
          const id = btn.dataset.id;
          const status = document.querySelector(`.statusSelect[data-id="${id}"]`).value;
          const notes = document.querySelector(`.noteInput[data-id="${id}"]`).value;
          btn.disabled = true;
          btn.textContent = "保存中...";
          try {
            await fetchJSON("/api/review", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ candidate_id: id, status, notes })
            });
            btn.textContent = "已保存";
            setTimeout(() => { btn.textContent = "保存"; btn.disabled = false; }, 800);
            await loadSummary();
          } catch (err) {
            console.error(err);
            btn.textContent = "失败重试";
            btn.disabled = false;
          }
        });
      });
    }

    async function loadSummary() {
      const data = await fetchJSON("/api/summary");
      renderSummary(data);
    }

    async function loadCandidates() {
      const q = encodeURIComponent(qEl.value.trim());
      const platform = encodeURIComponent(platformEl.value);
      const minScore = encodeURIComponent(minScoreEl.value || "0");
      const reviewStatus = encodeURIComponent(reviewStatusEl.value);
      const sortBy = encodeURIComponent(sortByEl.value);
      const sortOrder = encodeURIComponent(sortOrderEl.value);
      const url = `/api/candidates?q=${q}&platform=${platform}&min_score=${minScore}&review_status=${reviewStatus}&sort_by=${sortBy}&sort_order=${sortOrder}&limit=200`;
      const data = await fetchJSON(url);
      renderCandidates(data.items || []);
    }

    async function reload() {
      await Promise.all([loadSummary(), loadCandidates()]);
    }

    refreshBtn.addEventListener("click", reload);
    qEl.addEventListener("keydown", (e) => { if (e.key === "Enter") reload(); });
    sortByEl.addEventListener("change", reload);
    sortOrderEl.addEventListener("change", reload);
    reload().catch(err => {
      console.error(err);
      boardEl.innerHTML = `<div class="empty">加载失败：${String(err)}</div>`;
    });
  </script>
</body>
</html>
"""


def make_handler(service: DashboardService):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(_dashboard_html())
                return
            if parsed.path == "/api/summary":
                self._send_json(service.fetch_summary())
                return
            if parsed.path == "/api/candidates":
                qs = parse_qs(parsed.query)
                platform = _first(qs, "platform")
                review_status = _first(qs, "review_status")
                q = _first(qs, "q")
                sort_by = _first(qs, "sort_by")
                sort_order = _first(qs, "sort_order")
                try:
                    min_score = float(_first(qs, "min_score") or 0)
                except ValueError:
                    min_score = 0.0
                try:
                    limit = int(_first(qs, "limit") or 200)
                except ValueError:
                    limit = 200
                items = service.fetch_candidates(
                    platform=platform,
                    min_score=min_score,
                    limit=limit,
                    review_status=review_status,
                    query=q,
                    sort_by=sort_by,
                    sort_order=sort_order,
                )
                self._send_json({"items": items})
                return
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/review":
                self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                payload = self._read_json()
                service.update_review_state(
                    candidate_id=str(payload.get("candidate_id") or ""),
                    status=str(payload.get("status") or ""),
                    reviewer=str(payload.get("reviewer") or ""),
                    notes=str(payload.get("notes") or ""),
                )
                self._send_json({"ok": True})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def log_message(self, format: str, *args):  # noqa: A003
            # 保持 CLI 输出干净，避免前端轮询刷屏。
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(body.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be object")
            return payload

        def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DashboardHandler


def _first(qs: dict[str, list[str]], key: str) -> str:
    values = qs.get(key) or [""]
    return str(values[0] or "")


def run_dashboard_server(db_path: str | Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    service = DashboardService(db_path=Path(db_path))
    server = ThreadingHTTPServer((host, int(port)), make_handler(service))
    print(f"[dashboard] serving http://{host}:{port}")
    print(f"[dashboard] db={Path(db_path)}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
