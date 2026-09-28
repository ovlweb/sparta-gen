#!/usr/bin/env bash
# The APK on a device or emulator: the app starts its engine, the engine's ffmpeg runs, and the one-click remix
# renders — and goes on when the app is sent to the background halfway (another app in front, screen off).
# Screenshots of the app are kept (screen-*.png).
#
#   bash app/android/test/smoke.sh app-debug.apk source.mp4 [out-dir]
#
# The APK must be a debug build: the engine's port and token are read with `adb shell run-as` (the engine writes
# them to the app's private files only in debug builds).
set -euo pipefail
APK="$1"
SRC="$2"
OUT="${3:-android-test}"
PKG=gen.sparta.remix
mkdir -p "$OUT"

on_exit() {                        # whatever happened: keep the device log and a screenshot, and show why it failed
  code=$?
  adb exec-out screencap -p > "$OUT/screen-last.png" 2>/dev/null || true
  adb logcat -d -b all > "$OUT/logcat.txt" 2>/dev/null || adb logcat -d > "$OUT/logcat.txt" 2>/dev/null || true
  if [ "$code" != 0 ]; then
    echo "==> failed ($code); app process: $(adb shell pidof $PKG 2>/dev/null || echo gone)"
    adb shell dumpsys meminfo $PKG > "$OUT/meminfo.txt" 2>/dev/null || true
    grep -aiE "FATAL|AndroidRuntime|ANR in|Killing|am_kill|am_proc_died|am_anr|lowmemorykiller|oom-kill|Out of memory|Killed process|has died|SIGSEGV|SIGABRT|SIGKILL|Fatal signal|backtrace|Traceback|E/flutter|flutter :|python|SpartaGen|gen\.sparta|chaquo" \
      "$OUT/logcat.txt" | grep -v "^--------- beginning" | tail -150 || true
  fi
}
trap on_exit EXIT

adb logcat -c || true
adb install -r "$APK"
adb shell pm grant $PKG android.permission.POST_NOTIFICATIONS 2>/dev/null || true
adb shell am start -W -n $PKG/.MainActivity

echo "==> waiting for the engine"
info=""
for _ in $(seq 1 150); do
  info=$(adb shell run-as $PKG cat files/engine.json 2>/dev/null | tr -d '\r' || true)
  if [ -n "$info" ] && echo "$info" | grep -q '"port"'; then break; fi
  info=""
  sleep 2
done
if [ -z "$info" ]; then
  echo "the engine did not start (no files/engine.json)"
  exit 1
fi
PORT=$(echo "$info" | python3 -c "import json, sys; print(json.load(sys.stdin)['port'])")
TOKEN=$(echo "$info" | python3 -c "import json, sys; print(json.load(sys.stdin)['token'])")
adb forward "tcp:$PORT" "tcp:$PORT"
BASE="http://127.0.0.1:$PORT"
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
assert st["ffmpeg"], "ffmpeg is not usable inside the app"
EOF
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "$BASE/api/status")
[ "$code" = 401 ] || { echo "the engine answered without its token ($code)"; exit 1; }
connected=""
for _ in $(seq 1 60); do                         # the app itself talks to its engine (plain HTTP on 127.0.0.1)
  if adb logcat -d | grep -aq "SpartaGen: connected to the engine"; then connected=1; break; fi
  sleep 2
done
[ -n "$connected" ] || { echo "the app did not connect to its engine"; adb logcat -d | grep -a "flutter" | tail -30; exit 1; }
echo "==> the app is connected to its engine"
sleep 3
adb exec-out screencap -p > "$OUT/screen-start.png" || true
app_pid=$(adb shell pidof $PKG | tr -d '\r' || true)

echo "==> uploading the source"
api -X POST -H "X-Filename: source.mp4" --data-binary @"$SRC" "$BASE/api/source/upload" > "$OUT/upload.json"
echo "==> one click: samples, remix, preview"
job=$(api -X POST -H "Content-Type: application/json" -d '{"quality": "preview"}' "$BASE/api/auto" \
      | python3 -c "import json, sys; print(json.load(sys.stdin)['id'])")
status=running
start=$(date +%s)
misses=0
peak=0
away=""
while [ "$status" = running ]; do
  sleep 3
  if ! api "$BASE/api/job/$job" > "$OUT/job.json"; then
    misses=$((misses + 1))
    echo "  (the engine did not answer: $misses)"
    [ "$misses" -ge 3 ] && { echo "the engine stopped answering"; exit 1; }
    continue
  fi
  misses=0
  IFS='|' read -r status pct line < <(python3 -c "import json; j = json.load(open('$OUT/job.json')); \
print(f\"{j['status']}|{int(j['progress'] * 100)}|{j['progress']*100:5.1f}%  {j['message']}\")")
  # the app's memory (PSS: "TOTAL PSS: <kB>", older Android "TOTAL: <kB>")
  adb shell dumpsys meminfo $PKG > "$OUT/meminfo-now.txt" 2>/dev/null || true
  mem=$(tr -d , < "$OUT/meminfo-now.txt" | awk '/TOTAL PSS:/ {print int($3 / 1024); exit} /^ *TOTAL: / {print int($2 / 1024); exit}')
  if [ -n "$mem" ] && [ "$mem" -gt "$peak" ]; then
    peak=$mem
    cp "$OUT/meminfo-now.txt" "$OUT/meminfo-peak.txt"
  fi
  echo "  $line  ${mem:+· app $mem MB}"
  if [ -z "$away" ] && [ "$status" = running ] && [ "$pct" -ge 40 ]; then
    adb shell input keyevent KEYCODE_HOME && away=1 && echo "  sent the app to the background — the render has to go on"
  fi
  if [ $(( $(date +%s) - start )) -gt 2400 ]; then echo "timed out"; break; fi
done
if [ "$status" != done ]; then
  cat "$OUT/job.json"
  exit 1
fi
url=$(python3 -c "import json; print(json.load(open('$OUT/job.json'))['result']['file_url'])")
api "$BASE$url" -o "$OUT/remix-preview.mp4"
echo "==> rendered in $(( $(date +%s) - start ))s: $(du -h "$OUT/remix-preview.mp4" | cut -f1)"
if [ "$peak" -gt 0 ]; then echo "==> the app used at most ~$peak MB (PSS) while rendering"; fi
now=$(adb shell pidof $PKG | tr -d '\r' || true)
if [ "$now" != "$app_pid" ]; then echo "the app restarted (pid $app_pid -> ${now:-none})"; exit 1; fi
[ -n "$away" ] && echo "==> the app was in the background from 40% on: it ($app_pid) kept rendering"
adb shell am start -W -n $PKG/.MainActivity >/dev/null
sleep 4
adb exec-out screencap -p > "$OUT/screen-end.png" || true
if adb logcat -d | grep -a "E/flutter" | grep -aq "Unhandled Exception"; then
  echo "the app hit errors:"; adb logcat -d | grep -a "E/flutter" | tail -30
  exit 1
fi
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height -of compact "$OUT/remix-preview.mp4"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/remix-preview.mp4" \
  | python3 -c "import sys; d = float(sys.stdin.read()); print('duration', d); assert d > 20"
