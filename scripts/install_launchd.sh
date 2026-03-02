#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/Users/jiejie/Desktop/LVYU/projects/AI热点}"
PYTHON_BIN="${2:-$(command -v python3)}"
LABEL="com.jiejie.aihot.daily"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$PROJECT_DIR/data/logs"

mkdir -p "$LOG_DIR"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>${PYTHON_BIN}</string>
      <string>-m</string>
      <string>ai_hot_topics.cli</string>
      <string>run-daily</string>
      <string>--project-dir</string>
      <string>${PROJECT_DIR}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PYTHONPATH</key>
      <string>${PROJECT_DIR}/src</string>
    </dict>
    <key>StartCalendarInterval</key>
    <dict>
      <key>Hour</key>
      <integer>9</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/launchd.err.log</string>
    <key>RunAtLoad</key>
    <false/>
  </dict>
</plist>
PLIST

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"
echo "Installed launchd job: ${LABEL}"
echo "plist: $PLIST_PATH"

