from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def make_temp_project() -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="ai-hot-topics-test-"))
    (temp_dir / "prompts").mkdir(parents=True, exist_ok=True)
    (temp_dir / "data" / "raw").mkdir(parents=True, exist_ok=True)
    for file_name in ["sources.yaml", "keywords.yaml", "scoring.yaml", ".env.example"]:
        shutil.copy(PROJECT_ROOT / file_name, temp_dir / file_name)
    shutil.copy(PROJECT_ROOT / "prompts" / "short_video_outline.md", temp_dir / "prompts" / "short_video_outline.md")
    (temp_dir / ".env").write_text(
        "\n".join(
            [
                "LLM_PROVIDER=mock",
                f"DB_PATH={temp_dir / 'data' / 'hot_topics.db'}",
                f"DATA_DIR={temp_dir / 'data'}",
                f"RAW_DATA_DIR={temp_dir / 'data' / 'raw'}",
            ]
        ),
        encoding="utf-8",
    )
    return temp_dir

