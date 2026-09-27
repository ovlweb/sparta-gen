#!/usr/bin/env bash
# The APK on a device or emulator: the engine starts, its ffmpeg runs, and the one-click remix renders.
#
#   bash android/test/smoke.sh app.apk source.mp4 [out-dir]
#
# With APK "-" the engine is expected to be listening already (e.g. `python -m spartagen.android` on a
# desktop): only the HTTP part runs.
set -euo pipefail
APK="$1"
SRC="$2"
OUT="${3:-android-test}"
PORT=8757
BASE="http://127.0.0.1:$PORT"
PKG=gen.sparta.remix
mkdir -p "$OUT"

on_exit() {                        # whatever happened: keep the device log, and show why it failed
  code=$?
  [ "$APK" = "-" ] && return
  adb logcat -d > "$OUT/logcat.txt" 2>/dev/null || true
  if [ "$code" != 0 ]; then
    echo "==> failed ($code); app process: $(adb shell pidof $PKG 2>/dev/null || echo gone)"
    adb shell dumpsys meminfo $PKG > "$OUT/meminfo.txt" 2>/dev/null || true
    grep -aiE "FATAL|AndroidRuntime|lowmemorykiller|lmkd|am_kill|has died|died|SIGSEGV|SIGABRT|SIGKILL|Fatal signal|backtrace|Traceback|python|SpartaGen|chaquo" \
      "$OUT/logcat.txt" | grep -v "^--------- beginning" | tail -120 || true
  fi
}
trap on_exit EXIT

if [ "$APK" != "-" ]; then
  adb logcat -c || true
  adb install -r "$APK"
  adb shell am start -W -n gen.sparta.remix/.MainActivity
  adb forward "tcp:$PORT" "tcp:$PORT"
fi

up=""
for _ in $(seq 1 150); do
  if curl -sf "$BASE/api/status" -o "$OUT/status.json"; then up=1; break; fi
  sleep 2
done
[ "$APK" = "-" ] || adb logcat -d > "$OUT/logcat-start.txt" || true
if [ -z "$up" ]; then
  echo "the engine did not answer on port $PORT"
  [ -f "$OUT/logcat-start.txt" ] && grep -iE "python|spartagen|chaquo|fatal|exception" "$OUT/logcat-start.txt" | tail -80
  exit 1
fi
python3 - "$OUT/status.json" <<'EOF'
import json, sys
st = json.load(open(sys.argv[1]))
print("engine", st["version"], "·", st["ffmpeg_version"])
assert st["ffmpeg"], "ffmpeg is not usable inside the app"
EOF

echo "==> uploading the source"
curl -sf -X POST -H "X-Filename: source.mp4" --data-binary @"$SRC" "$BASE/api/source/upload" > "$OUT/upload.json"
echo "==> one click: samples, remix, preview"
job=$(curl -sf -X POST -H "Content-Type: application/json" -d '{"quality": "preview"}' "$BASE/api/auto" \
      | python3 -c "import json, sys; print(json.load(sys.stdin)['id'])")
status=running
start=$(date +%s)
misses=0
while [ "$status" = running ]; do
  sleep 3
  if ! curl -sf "$BASE/api/job/$job" > "$OUT/job.json"; then
    misses=$((misses + 1))
    echo "  (the engine did not answer: $misses)"
    [ "$misses" -ge 3 ] && { echo "the engine stopped answering"; exit 1; }
    continue
  fi
  misses=0
  status=$(python3 -c "import json; j = json.load(open('$OUT/job.json')); print(j['status'])")
  line=$(python3 -c "import json; j = json.load(open('$OUT/job.json')); print(f\"{j['progress']*100:5.1f}%  {j['message']}\")")
  mem=""
  if [ "$APK" != "-" ]; then
    mem=$(adb shell dumpsys meminfo $PKG 2>/dev/null | awk '/TOTAL PSS:|TOTAL:/ {print $2 / 1024 " MB"; exit}' || true)
  fi
  echo "  $line  ${mem:+· app $mem}"
  if [ $(( $(date +%s) - start )) -gt 2400 ]; then echo "timed out"; break; fi
done
if [ "$status" != done ]; then
  cat "$OUT/job.json"
  exit 1
fi
url=$(python3 -c "import json; print(json.load(open('$OUT/job.json'))['result']['file_url'])")
curl -sf "$BASE$url" -o "$OUT/remix-preview.mp4"
echo "==> rendered in $(( $(date +%s) - start ))s: $(du -h "$OUT/remix-preview.mp4" | cut -f1)"
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height -of compact "$OUT/remix-preview.mp4"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/remix-preview.mp4" \
  | python3 -c "import sys; d = float(sys.stdin.read()); print('duration', d); assert d > 20"
