#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/Users/jiejie/Desktop/LVYU/projects/AI热点}"
PYTHON_BIN="${2:-$PROJECT_DIR/.venv/bin/python}"
HOST="${3:-0.0.0.0}"
PORT="${4:-8765}"
LABEL="com.jiejie.aihot.dashboard"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$PROJECT_DIR/data/logs"

mkdir -p "$LOG_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python not found or not executable: $PYTHON_BIN" >&2
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
      <string>${PYTHON_BIN}</string>
      <string>-m</string>
      <string>ai_hot_topics.cli</string>
      <string>--project-dir</string>
      <string>${PROJECT_DIR}</string>
      <string>dashboard</string>
      <string>--host</string>
      <string>${HOST}</string>
      <string>--port</string>
      <string>${PORT}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PYTHONPATH</key>
      <string>${PROJECT_DIR}/src</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/dashboard.launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/dashboard.launchd.err.log</string>
  </dict>
</plist>
PLIST

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"
launchctl kickstart -k "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true

echo "Installed dashboard launchd job: ${LABEL}"
echo "plist: $PLIST_PATH"
echo "host=${HOST} port=${PORT}"
