from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..utils import isoformat_z, json_loads, now_utc


CANDIDATE_KEY_FIELD = "candidate_id"
MAIN_KEY_FIELD = "candidate_id"
RUN_LOG_KEY_FIELD = "log_key"


class BitableAdapter(Protocol):
    def is_enabled(self) -> bool:
        ...

    def upsert_records(self, table_id: str, key_field: str, records: list[dict[str, Any]]) -> dict[str, int]:
        ...

    def list_records(self, table_id: str) -> list[dict[str, Any]]:
        ...


@dataclass
class DryRunBitableAdapter:
    tables: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)

    def is_enabled(self) -> bool:
        return False

    def upsert_records(self, table_id: str, key_field: str, records: list[dict[str, Any]]) -> dict[str, int]:
        table = self.tables.setdefault(table_id, {})
        created = 0
        updated = 0
        for record in records:
            key = str(record.get(key_field, ""))
            if not key:
                continue
            if key in table:
                table[key].update(record)
                updated += 1
            else:
                table[key] = dict(record)
                created += 1
        return {"created": created, "updated": updated}

    def list_records(self, table_id: str) -> list[dict[str, Any]]:
        return list(self.tables.get(table_id, {}).values())


class MemoryBitableAdapter(DryRunBitableAdapter):
    def is_enabled(self) -> bool:
        return True


class FeishuHttpBitableAdapter:
    BASE = "https://open.feishu.cn/open-apis"

    def __init__(self, app_id: str, app_secret: str, app_token: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.app_token = app_token
        self._tenant_token: str | None = None

    def is_enabled(self) -> bool:
        return True

    def _http_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.BASE}{path}"
        data = None
        headers = {"User-Agent": "ai-hot-topics/0.1", "Content-Type": "application/json"}
        if path != "/auth/v3/tenant_access_token/internal":
            headers["Authorization"] = f"Bearer {self._get_tenant_token()}"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=30) as resp:  # noqa: S310
                body = json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"Feishu HTTP error: {exc}") from exc
        if body.get("code") not in (0, "0", None):
            raise RuntimeError(f"Feishu API error: {body}")
        return body

    def _get_tenant_token(self) -> str:
        if self._tenant_token:
            return self._tenant_token
        body = self._http_json(
            "POST",
            "/auth/v3/tenant_access_token/internal",
            {"app_id": self.app_id, "app_secret": self.app_secret},
        )
        token = body.get("tenant_access_token")
        if not token:
            raise RuntimeError("Feishu auth missing tenant_access_token")
        self._tenant_token = str(token)
        return self._tenant_token

    def list_records(self, table_id: str) -> list[dict[str, Any]]:
        all_records: list[dict[str, Any]] = []
        page_token = ""
        while True:
            query = urlencode(
                {
                    "page_size": 200,
                    **({"page_token": page_token} if page_token else {}),
                }
            )
            path = f"/bitable/v1/apps/{self.app_token}/tables/{table_id}/records?{query}"
            body = self._http_json("GET", path)
            data = body.get("data", {}) or {}
            items = data.get("items", []) or []
            for item in items:
                fields = item.get("fields", {}) or {}
                fields["_record_id"] = item.get("record_id")
                all_records.append(fields)
            page_token = str(data.get("page_token") or "")
            has_more = bool(data.get("has_more"))
            if not has_more:
                break
        return all_records

    def upsert_records(self, table_id: str, key_field: str, records: list[dict[str, Any]]) -> dict[str, int]:
        existing = self.list_records(table_id)
        existing_by_key = {
            str(item.get(key_field)): item
            for item in existing
            if item.get(key_field) not in (None, "")
        }
        to_create: list[dict[str, Any]] = []
        to_update: list[dict[str, Any]] = []
        for fields in records:
            key = str(fields.get(key_field, ""))
            if not key:
                continue
            matched = existing_by_key.get(key)
            if matched and matched.get("_record_id"):
                to_update.append({"record_id": matched["_record_id"], "fields": fields})
            else:
                to_create.append({"fields": fields})

        created = 0
        updated = 0
        for chunk in _chunks(to_create, 200):
            if not chunk:
                continue
            path = f"/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/batch_create"
            self._http_json("POST", path, {"records": chunk})
            created += len(chunk)
        for chunk in _chunks(to_update, 200):
            if not chunk:
                continue
            path = f"/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/batch_update"
            self._http_json("POST", path, {"records": chunk})
            updated += len(chunk)
        return {"created": created, "updated": updated}


def _chunks(items: list[Any], n: int) -> list[list[Any]]:
    return [items[i : i + n] for i in range(0, len(items), n)]


@dataclass
class FeishuSyncService:
    adapter: BitableAdapter
    table_candidates: str | None = None
    table_main: str | None = None
    table_run_logs: str | None = None

    def enabled(self) -> bool:
        return self.adapter.is_enabled() and bool(self.table_candidates)

    def sync_candidates(self, candidate_rows: list[dict[str, Any]]) -> dict[str, int]:
        if not self.table_candidates:
            return {"created": 0, "updated": 0, "skipped": len(candidate_rows)}
        payloads = [self._candidate_fields(row) for row in candidate_rows]
        result = self.adapter.upsert_records(self.table_candidates, CANDIDATE_KEY_FIELD, payloads)
        result["skipped"] = 0
        return result

    def sync_main_topics(self, candidate_rows: list[dict[str, Any]]) -> dict[str, int]:
        if not self.table_main:
            return {"created": 0, "updated": 0, "skipped": len(candidate_rows)}
        approved = [row for row in candidate_rows if row.get("review_status") == "approved"]
        payloads = [self._main_fields(row) for row in approved]
        result = self.adapter.upsert_records(self.table_main, MAIN_KEY_FIELD, payloads)
        result["skipped"] = max(0, len(candidate_rows) - len(payloads))
        return result

    def sync_run_logs(self, run_id: str, log_rows: list[dict[str, Any]]) -> dict[str, int]:
        if not self.table_run_logs:
            return {"created": 0, "updated": 0, "skipped": len(log_rows)}
        payloads = []
        for row in log_rows:
            key = f"{run_id}|{row.get('id')}"
            payloads.append(
                {
                    "log_key": key,
                    "run_id": run_id,
                    "stage": row.get("stage"),
                    "platform": row.get("platform") or "",
                    "status": row.get("status"),
                    "message": row.get("message") or "",
                    "duration_ms": row.get("duration_ms") or 0,
                    "started_at": row.get("started_at") or "",
                    "ended_at": row.get("ended_at") or "",
                    "metrics_json": row.get("metrics_json") or "{}",
                }
            )
        result = self.adapter.upsert_records(self.table_run_logs, RUN_LOG_KEY_FIELD, payloads)
        result["skipped"] = 0
        return result

    def fetch_review_state_updates(self) -> dict[str, dict[str, Any]]:
        if not self.table_candidates:
            return {}
        updates: dict[str, dict[str, Any]] = {}
        for row in self.adapter.list_records(self.table_candidates):
            candidate_id = str(row.get("candidate_id") or "").strip()
            if not candidate_id:
                continue
            status = str(row.get("状态") or row.get("review_status") or "").strip()
            if not status:
                continue
            if status not in {"candidate", "approved", "rejected"}:
                continue
            updates[candidate_id] = {
                "status": status,
                "reviewer": row.get("审核人") or row.get("reviewer"),
                "notes": row.get("审核备注") or row.get("review_notes"),
                "reviewed_at": row.get("reviewed_at") or isoformat_z(now_utc()),
            }
        return updates

    def _candidate_fields(self, row: dict[str, Any]) -> dict[str, Any]:
        evidence_links = json_loads(row.get("evidence_links_json"), default=[]) or []
        keyword_hits = json_loads(row.get("keyword_hits_json"), default=[]) or []
        representative_urls = json_loads(row.get("representative_urls_json"), default=[]) or []
        draft_text = "\n".join(
            [
                f"Hook: {row.get('hook') or ''}",
                f"核心观点: {row.get('core_point') or ''}",
                f"1) {row.get('outline_1') or ''}",
                f"2) {row.get('outline_2') or ''}",
                f"3) {row.get('outline_3') or ''}",
                f"CTA: {row.get('cta') or ''}",
                f"风险提示: {row.get('risk_notes') or ''}",
            ]
        ).strip()
        return {
            "candidate_id": row.get("candidate_id"),
            "主题标题": row.get("title_suggestion") or "",
            "主题摘要": row.get("summary") or "",
            "关键词": " / ".join(keyword_hits),
            "代表链接": "\n".join(representative_urls[:5]),
            "平台来源数": len(representative_urls),
            "总分": round(float(row.get("total_score") or 0), 2),
            "热度分": round(float(row.get("hotness_score") or 0), 2),
            "增长新鲜度": round(float(row.get("freshness_score") or 0), 2),
            "可复制性分": round(float(row.get("reproducibility_score") or 0), 2),
            "中文适配分": round(float(row.get("china_fit_score") or 0), 2),
            "新颖度": round(float(row.get("novelty_score") or 0), 2),
            "脚本提纲草稿": draft_text,
            "脚本状态": row.get("draft_status") or "",
            "状态": row.get("review_status") or "candidate",
            "审核备注": row.get("review_notes") or "",
            "生成模型": f"{row.get('provider') or ''}:{row.get('model') or ''}".strip(":"),
            "证据链接": "\n".join(evidence_links[:5]),
            "最近更新时间": row.get("updated_at") or "",
        }

    def _main_fields(self, row: dict[str, Any]) -> dict[str, Any]:
        fields = self._candidate_fields(row)
        fields["执行建议"] = "人工审核通过后加入主选题库，可按发布时间和账号定位二次改写"
        return fields


def build_feishu_sync_service(env: dict[str, str]) -> FeishuSyncService:
    app_id = (env.get("FEISHU_APP_ID") or "").strip()
    app_secret = (env.get("FEISHU_APP_SECRET") or "").strip()
    app_token = (env.get("FEISHU_APP_TOKEN") or "").strip()
    table_candidates = (env.get("FEISHU_TABLE_ID_CANDIDATES") or "").strip() or None
    table_main = (env.get("FEISHU_TABLE_ID_MAIN") or "").strip() or None
    table_run_logs = (env.get("FEISHU_TABLE_ID_RUN_LOGS") or "").strip() or None

    if app_id and app_secret and app_token:
        adapter: BitableAdapter = FeishuHttpBitableAdapter(app_id, app_secret, app_token)
    else:
        adapter = DryRunBitableAdapter()
    return FeishuSyncService(
        adapter=adapter,
        table_candidates=table_candidates,
        table_main=table_main,
        table_run_logs=table_run_logs,
    )

