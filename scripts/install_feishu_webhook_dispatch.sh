#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/Users/jiejie/Desktop/LVYU/projects/AI热点}"
PYTHON_BIN="${2:-$(command -v python3)}"
HOUR="${3:-9}"
MINUTE="${4:-2}"
DISPATCH_DIR="${5:-$HOME/.codex/ai-hotspot-dispatch}"
LABEL="com.jiejie.aihot.feishu.dispatch"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
OUTBOX_DIR="$DISPATCH_DIR/outbox"
DISPATCH_ENV="$DISPATCH_DIR/.env"
DISPATCH_SCRIPT="$DISPATCH_DIR/send_outbox_to_feishu.py"

mkdir -p "$OUTBOX_DIR" "$HOME/Library/LaunchAgents" "$DISPATCH_DIR"

if [[ ! -f "$PROJECT_DIR/.env" ]]; then
  echo "[ERROR] Missing .env at $PROJECT_DIR/.env" >&2
  exit 1
fi
if [[ ! -f "$DISPATCH_SCRIPT" ]]; then
  echo "[ERROR] Missing dispatch script at $DISPATCH_SCRIPT" >&2
  exit 1
fi

PROJECT_ENV_PATH="$PROJECT_DIR/.env" DISPATCH_ENV_PATH="$DISPATCH_ENV" python3 - <<'PY'
import os
from pathlib import Path
project_env = Path(os.environ['PROJECT_ENV_PATH'])
dispatch_env = Path(os.environ['DISPATCH_ENV_PATH'])
keys = ('FEISHU_WEBHOOK_URL', 'FEISHU_SIGNING_SECRET')
vals = {}
for raw in project_env.read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    k = k.strip()
    if k in keys:
        vals[k] = v.strip()
dispatch_env.write_text('\n'.join(f"{k}={vals.get(k, '')}" for k in keys) + '\n', encoding='utf-8')
PY

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
      <string>${DISPATCH_SCRIPT}</string>
      <string>--outbox-dir</string>
      <string>${OUTBOX_DIR}</string>
      <string>--env-file</string>
      <string>${DISPATCH_ENV}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${DISPATCH_DIR}</string>
    <key>StartCalendarInterval</key>
    <dict>
      <key>Hour</key>
      <integer>${HOUR}</integer>
      <key>Minute</key>
      <integer>${MINUTE}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${OUTBOX_DIR}/feishu-dispatch.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${OUTBOX_DIR}/feishu-dispatch.stderr.log</string>
    <key>RunAtLoad</key>
    <false/>
  </dict>
</plist>
PLIST

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"

echo "Installed launchd job: ${LABEL}"
echo "plist: ${PLIST_PATH}"
echo "dispatch dir: ${DISPATCH_DIR}"
echo "outbox dir: ${OUTBOX_DIR}"
echo "schedule: $(printf '%02d:%02d' "$HOUR" "$MINUTE") daily"
