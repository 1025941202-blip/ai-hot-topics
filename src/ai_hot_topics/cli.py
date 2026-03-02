from __future__ import annotations

import argparse
import json
import webbrowser
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import load_runtime_config
from .dashboard import run_dashboard_server
from .generators import build_outline_generator
from .pipeline import Pipeline
from .storage import Database
from .sync import build_feishu_sync_service


def _build_pipeline(project_dir: str | Path) -> tuple[Pipeline, Database]:
    cfg = load_runtime_config(project_dir)
    db = Database(cfg.paths.db_path)
    generator = build_outline_generator(cfg.env, cfg.paths.prompt_file)
    feishu_sync = build_feishu_sync_service(cfg.env)
    pipeline = Pipeline(cfg=cfg, db=db, outline_generator=generator, feishu_sync=feishu_sync)
    return pipeline, db


def _print(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _cmd_run_daily(args) -> int:
    pipeline, db = _build_pipeline(args.project_dir)
    try:
        summary = pipeline.run_daily(
            since_hours=args.since_hours,
            max_per_keyword=args.max_per_keyword,
            generate_limit=args.generate_limit,
        )
        _print({"ok": True, "summary": asdict(summary)})
        return 0
    finally:
        db.close()


def _cmd_collect(args) -> int:
    pipeline, db = _build_pipeline(args.project_dir)
    try:
        run_id = db.new_run_id(prefix="collect")
        stats = pipeline.collect_stage(
            run_id,
            platforms=[args.platform] if args.platform else None,
            since_hours=args.since_hours,
            max_per_keyword=args.max_per_keyword,
        )
        _print({"ok": True, "run_id": run_id, "collect": stats})
        return 0
    finally:
        db.close()


def _cmd_process(args) -> int:
    pipeline, db = _build_pipeline(args.project_dir)
    try:
        run_id = db.new_run_id(prefix="process")
        stats = pipeline.process_stage(run_id)
        _print({"ok": True, "run_id": run_id, "process": stats})
        return 0
    finally:
        db.close()


def _cmd_generate(args) -> int:
    pipeline, db = _build_pipeline(args.project_dir)
    try:
        run_id = db.new_run_id(prefix="generate")
        stats = pipeline.generate_scripts_stage(run_id, limit=args.limit)
        _print({"ok": True, "run_id": run_id, "generate": stats})
        return 0
    finally:
        db.close()


def _cmd_sync(args) -> int:
    pipeline, db = _build_pipeline(args.project_dir)
    try:
        run_id = db.new_run_id(prefix="sync")
        stats = pipeline.sync_feishu_stage(run_id)
        _print({"ok": True, "run_id": run_id, "sync": stats})
        return 0
    finally:
        db.close()


def _cmd_backfill(args) -> int:
    pipeline, db = _build_pipeline(args.project_dir)
    try:
        result = pipeline.run_backfill(days=args.days, max_per_keyword=args.max_per_keyword)
        _print({"ok": True, "backfill": result})
        return 0
    finally:
        db.close()


def _cmd_dashboard(args) -> int:
    cfg = load_runtime_config(args.project_dir)
    host = args.host
    port = int(args.port)
    if args.open:
        webbrowser.open(f"http://{host}:{port}")
    run_dashboard_server(cfg.paths.db_path, host=host, port=port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI 爆款选题库自动化 CLI")
    parser.add_argument(
        "--project-dir",
        default=str(Path.cwd()),
        help="项目目录（包含 sources.yaml/keywords.yaml/scoring.yaml）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run-daily", help="运行全流程")
    p_run.add_argument("--since-hours", type=int, default=48)
    p_run.add_argument("--max-per-keyword", type=int, default=5)
    p_run.add_argument("--generate-limit", type=int, default=50)
    p_run.set_defaults(func=_cmd_run_daily)

    p_collect = sub.add_parser("collect", help="只运行抓取和规范化")
    p_collect.add_argument("--platform", choices=["douyin", "xiaohongshu", "huitun", "x", "youtube"])
    p_collect.add_argument("--since-hours", type=int, default=48)
    p_collect.add_argument("--max-per-keyword", type=int, default=5)
    p_collect.set_defaults(func=_cmd_collect)

    p_process = sub.add_parser("process", help="只运行聚类与评分")
    p_process.set_defaults(func=_cmd_process)

    p_generate = sub.add_parser("generate-scripts", help="只生成脚本提纲")
    p_generate.add_argument("--limit", type=int, default=50)
    p_generate.set_defaults(func=_cmd_generate)

    p_sync = sub.add_parser("sync-feishu", help="只同步飞书并回写审核状态")
    p_sync.set_defaults(func=_cmd_sync)

    p_backfill = sub.add_parser("backfill", help="回填多日数据（重复执行 daily）")
    p_backfill.add_argument("--days", type=int, required=True)
    p_backfill.add_argument("--max-per-keyword", type=int, default=5)
    p_backfill.set_defaults(func=_cmd_backfill)

    p_dashboard = sub.add_parser("dashboard", help="启动本地可视化看板")
    p_dashboard.add_argument("--host", default="127.0.0.1")
    p_dashboard.add_argument("--port", type=int, default=8765)
    p_dashboard.add_argument("--open", action="store_true", help="启动时自动打开浏览器")
    p_dashboard.set_defaults(func=_cmd_dashboard)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
