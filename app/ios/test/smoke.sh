#!/usr/bin/env bash
# The iOS app on a simulator: it starts its engine (Python and FFmpegKit inside the app), the app connects to it,
# and the one-click remix renders a test video.  Screenshots of the app are kept (screen-*.png), with its log.
#
#   bash app/ios/test/smoke.sh path/to/Runner.app source.mp4 [out-dir]
#
# The app must be a debug build for the simulator (flutter build ios --simulator --debug): it writes the engine's
# port and token into its data folder.  Needs numpy and imageio-ffmpeg (to check the render) and the repository.
set -euo pipefail
APP="$1"
SRC="$2"
OUT="${3:-ios-test}"
BUNDLE=gen.sparta.remix
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

dev=$(xcrun simctl list devices available -j | python3 -c "
import json, sys
devices = json.load(sys.stdin)['devices']
phones = [d for runtime, ds in devices.items() if 'iOS' in runtime for d in ds if d['name'].startswith('iPhone')]
print(phones[-1]['udid'] if phones else '')")
[ -n "$dev" ] || { echo "no iPhone simulator"; xcrun simctl list devices available; exit 1; }
echo "==> simulator $(xcrun simctl list devices | grep "$dev" | sed 's/^ *//')"
xcrun simctl boot "$dev" 2>/dev/null || true
xcrun simctl bootstatus "$dev" -b >/dev/null

on_exit() {                        # whatever happened: a screenshot, the app's log, and why it failed
  code=$?
  xcrun simctl io "$dev" screenshot "$OUT/screen-last.png" >/dev/null 2>&1 || true
  kill "${logger:-0}" 2>/dev/null || true
  if [ "$code" != 0 ]; then
    echo "==> failed ($code)"
    tail -60 "$OUT/app-stderr.log" "$OUT/app-stdout.log" 2>/dev/null || true
    grep -aiE "flutter|python|spartagen|error|exception|traceback|crash" "$OUT/device.log" 2>/dev/null | tail -80 || true
  fi
}
trap on_exit EXIT

xcrun simctl install "$dev" "$APP"
xcrun simctl spawn "$dev" log stream --level debug --style compact --predicate 'process == "Runner"' \
  > "$OUT/device.log" 2>&1 &
logger=$!
xcrun simctl launch --terminate-running-process --stdout="$OUT/app-stdout.log" --stderr="$OUT/app-stderr.log" \
  "$dev" "$BUNDLE"
data=$(xcrun simctl get_app_container "$dev" "$BUNDLE" data)
INFO="$data/Library/Application Support/engine.json"

echo "==> waiting for the engine"
for _ in $(seq 1 150); do
  if [ -s "$INFO" ] && grep -q '"port"' "$INFO"; then break; fi
  sleep 2
done
[ -s "$INFO" ] || { echo "the engine did not start (no engine.json)"; exit 1; }
PORT=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['port'])" "$INFO")
TOKEN=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['token'])" "$INFO")
BASE="http://127.0.0.1:$PORT"            # (a simulator's apps are processes of this Mac)
api() { curl -sf --max-time 20 -H "X-Sparta-Token: $TOKEN" "$@"; }

up=""
for _ in $(seq 1 60); do
  if api "$BASE/api/status" -o "$OUT/status.json"; then up=1; break; fi
  sleep 2
done
[ -n "$up" ] || { echo "the engine did not answer on port $PORT"; exit 1; }
python3 - "$OUT/status.json" <<'EOF'
import json, sys
st = json.load(open(sys.argv[1]))
print("engine", st["version"], "·", st["ffmpeg_version"])
assert st["ffmpeg"], "ffmpeg (FFmpegKit) is not usable inside the app"
EOF
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "$BASE/api/status")
[ "$code" = 401 ] || { echo "the engine answered without its token ($code)"; exit 1; }
connected=""
for _ in $(seq 1 60); do                          # the app itself talks to its engine
  if grep -aqs "SpartaGen: connected to the engine" "$OUT/device.log" "$OUT/app-stdout.log" "$OUT/app-stderr.log"; then
    connected=1
    break
  fi
  sleep 2
done
[ -n "$connected" ] || { echo "the app did not connect to its engine"; exit 1; }
echo "==> the app is connected to its engine"
sleep 3
xcrun simctl io "$dev" screenshot "$OUT/screen-start.png" >/dev/null || true

echo "==> uploading the source"
api -X POST -H "X-Filename: source.mp4" --data-binary @"$SRC" "$BASE/api/source/upload" > "$OUT/upload.json"
echo "==> one click: samples, remix, preview"
job=$(api -X POST -H "Content-Type: application/json" -d '{"quality": "preview"}' "$BASE/api/auto" \
      | python3 -c "import json, sys; print(json.load(sys.stdin)['id'])")
status=running
start=$(date +%s)
while [ "$status" = running ]; do
  sleep 3
  api "$BASE/api/job/$job" > "$OUT/job.json" || { echo "  (the engine did not answer)"; continue; }
  IFS='|' read -r status line < <(python3 -c "import json; j = json.load(open('$OUT/job.json')); \
print(f\"{j['status']}|{j['progress'] * 100:5.1f}%  {j['message']}\")")
  echo "  $line"
  if [ $(( $(date +%s) - start )) -gt 2400 ]; then echo "timed out"; break; fi
done
if [ "$status" != done ]; then
  cat "$OUT/job.json"
  exit 1
fi
url=$(python3 -c "import json; print(json.load(open('$OUT/job.json'))['result']['file_url'])")
api "$BASE$url" -o "$OUT/remix-preview.mp4"
echo "==> rendered in $(( $(date +%s) - start ))s: $(du -h "$OUT/remix-preview.mp4" | cut -f1)"
sleep 2
xcrun simctl io "$dev" screenshot "$OUT/screen-end.png" >/dev/null || true
PYTHONPATH="$ROOT" python3 - "$OUT/remix-preview.mp4" <<'EOF'
import sys
from spartagen import ffmpeg as ff
info = ff.probe(sys.argv[1])
print(f"remix: {info.duration:.1f} s, {info.width}x{info.height}, video {info.has_video}, audio {info.has_audio}")
assert info.duration > 20 and info.has_video and info.has_audio
EOF
