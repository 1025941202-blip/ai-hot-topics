#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/Users/jiejie/Desktop/LVYU/projects/AI热点}"
PYTHON_BIN="${2:-$PROJECT_DIR/.venv/bin/python}"
REMOTE="${3:-origin}"
BRANCH="${4:-main}"

RUN_COLLECT="${PAGES_RUN_COLLECT:-1}"
RUN_PROCESS="${PAGES_RUN_PROCESS:-1}"
COLLECT_PLATFORMS="${PAGES_COLLECT_PLATFORMS:-xiaohongshu,huitun}"
SINCE_HOURS="${PAGES_SINCE_HOURS:-48}"
MAX_PER_KEYWORD="${PAGES_MAX_PER_KEYWORD:-20}"
EXPORT_LIMIT="${PAGES_EXPORT_LIMIT:-300}"
SORT_BY="${PAGES_SORT_BY:-likes}"
SORT_ORDER="${PAGES_SORT_ORDER:-desc}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[ERROR] Python not executable: $PYTHON_BIN" >&2
  exit 1
fi

if [[ ! -d "$PROJECT_DIR/.git" ]]; then
  echo "[ERROR] Not a git repository: $PROJECT_DIR" >&2
  exit 1
fi

cd "$PROJECT_DIR"

echo "[pages-publish] start $(date '+%Y-%m-%d %H:%M:%S')"
echo "[pages-publish] project=$PROJECT_DIR remote=$REMOTE branch=$BRANCH"

run_cmd() {
  local label="$1"
  shift
  echo "[pages-publish] $label"
  "$@"
}

if ! run_cmd "git pull --ff-only" git pull --ff-only "$REMOTE" "$BRANCH"; then
  echo "[pages-publish] WARN: git pull failed, continue with local branch state"
fi

if [[ "$RUN_COLLECT" == "1" ]]; then
  IFS=',' read -r -a platforms <<< "$COLLECT_PLATFORMS"
  for p in "${platforms[@]}"; do
    p="$(echo "$p" | xargs)"
    if [[ -z "$p" ]]; then
      continue
    fi
    if ! run_cmd "collect platform=$p" \
      env PYTHONPATH="$PROJECT_DIR/src" "$PYTHON_BIN" -m ai_hot_topics.cli \
        --project-dir "$PROJECT_DIR" \
        collect --platform "$p" --since-hours "$SINCE_HOURS" --max-per-keyword "$MAX_PER_KEYWORD"; then
      echo "[pages-publish] WARN: collect failed platform=$p, continue"
    fi
  done
fi

if [[ "$RUN_PROCESS" == "1" ]]; then
  if ! run_cmd "process" \
    env PYTHONPATH="$PROJECT_DIR/src" "$PYTHON_BIN" -m ai_hot_topics.cli \
      --project-dir "$PROJECT_DIR" \
      process; then
    echo "[pages-publish] WARN: process failed, continue to export"
  fi
fi

run_cmd "export docs/data/candidates.json" \
  env PYTHONPATH="$PROJECT_DIR/src" "$PYTHON_BIN" "$PROJECT_DIR/scripts/export_pages_data.py" \
    --project-dir "$PROJECT_DIR" \
    --output "$PROJECT_DIR/docs/data/candidates.json" \
    --limit "$EXPORT_LIMIT" \
    --sort-by "$SORT_BY" \
    --sort-order "$SORT_ORDER"

git add docs/data/candidates.json

if git diff --cached --quiet; then
  echo "[pages-publish] no data changes, skip commit/push"
  exit 0
fi

commit_msg="chore: update pages snapshot $(date '+%Y-%m-%d %H:%M:%S')"
run_cmd "git commit" git commit -m "$commit_msg"
run_cmd "git push" git push "$REMOTE" "$BRANCH"

echo "[pages-publish] done"
