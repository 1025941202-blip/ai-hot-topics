#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path


PLATFORM_URLS = {
    "douyin": "https://www.douyin.com/",
    "xiaohongshu": "https://www.xiaohongshu.com/",
    "x": "https://x.com/home",
}


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化 Playwright 浏览器登录态（持久化到项目目录）")
    parser.add_argument(
        "--project-dir",
        default="/Users/jiejie/Desktop/LVYU/projects/AI热点",
        help="项目目录（包含 .env）",
    )
    parser.add_argument(
        "--platform",
        choices=["all", "douyin", "xiaohongshu", "x"],
        default="all",
        help="要打开的登录平台",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="无头模式（登录初始化通常不建议）",
    )
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    env = load_dotenv(project_dir / ".env")
    env.update(os.environ)
    user_data_dir = Path(
        env.get("PLAYWRIGHT_USER_DATA_DIR", str(project_dir / "data" / "playwright-user-data"))
    ).expanduser()
    channel = env.get("PLAYWRIGHT_BROWSER_CHANNEL", "chrome")
    user_data_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"[ERROR] Playwright 未安装或不可用: {exc}")
        print("请先安装依赖：.venv/bin/pip install -e '.[browser]'")
        return 1

    targets = list(PLATFORM_URLS) if args.platform == "all" else [args.platform]
    print(f"[INFO] user_data_dir={user_data_dir}")
    print(f"[INFO] channel={channel}")
    print(f"[INFO] 将打开平台: {', '.join(targets)}")
    print("[INFO] 请在打开的浏览器中完成登录。登录完成后回到终端按 Enter 关闭浏览器。")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=args.headless,
            channel=channel,
        )
        for platform in targets:
            page = context.new_page()
            page.goto(PLATFORM_URLS[platform], wait_until="domcontentloaded", timeout=30000)
        try:
            input()
        finally:
            context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

