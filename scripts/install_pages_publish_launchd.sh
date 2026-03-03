#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/Users/jiejie/Desktop/LVYU/projects/AI热点}"
PYTHON_BIN="${2:-$PROJECT_DIR/.venv/bin/python}"
HOUR="${3:-9}"
MINUTE="${4:-20}"
LABEL="com.jiejie.aihot.pages.publish"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$PROJECT_DIR/data/logs"
PUBLISH_SCRIPT="$PROJECT_DIR/scripts/publish_pages_snapshot.sh"

mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"

if [[ ! -x "$PUBLISH_SCRIPT" ]]; then
  echo "[ERROR] Missing publish script: $PUBLISH_SCRIPT" >&2
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[ERROR] Python not executable: $PYTHON_BIN" >&2
  exit 1
fi

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/bash</string>
      <string>${PUBLISH_SCRIPT}</string>
      <string>${PROJECT_DIR}</string>
      <string>${PYTHON_BIN}</string>
      <string>origin</string>
      <string>main</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PYTHONPATH</key>
      <string>${PROJECT_DIR}/src</string>
      <key>PAGES_RUN_COLLECT</key>
      <string>1</string>
      <key>PAGES_RUN_PROCESS</key>
      <string>1</string>
      <key>PAGES_COLLECT_PLATFORMS</key>
      <string>xiaohongshu,huitun,douyin,x,youtube</string>
      <key>PAGES_SINCE_HOURS</key>
      <string>48</string>
      <key>PAGES_MAX_PER_KEYWORD</key>
      <string>20</string>
      <key>PAGES_EXPORT_LIMIT</key>
      <string>300</string>
      <key>PAGES_SORT_BY</key>
      <string>likes</string>
      <key>PAGES_SORT_ORDER</key>
      <string>desc</string>
    </dict>
    <key>StartCalendarInterval</key>
    <dict>
      <key>Hour</key>
      <integer>${HOUR}</integer>
      <key>Minute</key>
      <integer>${MINUTE}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/pages-publish.out.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/pages-publish.err.log</string>
    <key>RunAtLoad</key>
    <false/>
  </dict>
</plist>
PLIST

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"

echo "Installed launchd job: ${LABEL}"
echo "plist: ${PLIST_PATH}"
echo "schedule: $(printf '%02d:%02d' "$HOUR" "$MINUTE") daily"
echo "stdout log: ${LOG_DIR}/pages-publish.out.log"
echo "stderr log: ${LOG_DIR}/pages-publish.err.log"
