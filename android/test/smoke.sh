#!/usr/bin/env bash
# The APK on a device or emulator: the engine starts, its ffmpeg runs, and the one-click remix renders — and
# goes on when Android ends the page's own process (the WebView renderer) halfway, as it does to reclaim memory.
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
  adb logcat -d -b all > "$OUT/logcat.txt" 2>/dev/null || adb logcat -d > "$OUT/logcat.txt" 2>/dev/null || true
  if [ "$code" != 0 ]; then
    echo "==> failed ($code); app process: $(adb shell pidof $PKG 2>/dev/null || echo gone)"
    adb shell dumpsys meminfo $PKG > "$OUT/meminfo.txt" 2>/dev/null || true
    grep -aiE "FATAL|AndroidRuntime|ANR in|Killing|am_kill|am_proc_died|am_anr|lowmemorykiller|oom-kill|Out of memory|Killed process|has died|died|SIGSEGV|SIGABRT|SIGKILL|Fatal signal|backtrace|Traceback|Render process|aw_browser|page process|python|SpartaGen|gen\.sparta|chaquo" \
      "$OUT/logcat.txt" | grep -v "^--------- beginning" | tail -150 || true
  fi
}
trap on_exit EXIT

root=""
if [ "$APK" != "-" ]; then
  # (Root, where the device allows it — emulator images do — only to end the page's process below.)
  if adb root >/dev/null 2>&1; then
    for _ in $(seq 1 30); do                     # adbd restarts as root: wait until it is back
      [ "$(adb shell id -u 2>/dev/null | tr -d '\r')" = 0 ] && { root=1; break; }
      sleep 1
    done
  fi
  adb logcat -c || true
  adb install -r "$APK"
  adb shell am start -W -n gen.sparta.remix/.MainActivity
  adb forward "tcp:$PORT" "tcp:$PORT"
fi

up=""
for _ in $(seq 1 150); do
  if curl -sf --max-time 20 "$BASE/api/status" -o "$OUT/status.json"; then up=1; break; fi
  sleep 2
done
if [ -z "$up" ]; then
  echo "the engine did not answer on port $PORT"
  exit 1
fi
python3 - "$OUT/status.json" <<'EOF'
import json, sys
st = json.load(open(sys.argv[1]))
print("engine", st["version"], "·", st["ffmpeg_version"])
assert st["ffmpeg"], "ffmpeg is not usable inside the app"
EOF
app_pid=""
[ "$APK" = "-" ] || app_pid=$(adb shell pidof $PKG | tr -d '\r' || true)

end_page() {                       # end the WebView renderer like Android's memory reclaim does (kill -9)
  pids=$(adb shell ps -A -o PID,NAME 2>/dev/null | tr -d '\r' | awk '$2 ~ /:sandboxed_process/ {print $1}' | xargs || true)
  if [ -z "$pids" ]; then
    echo "  (no page process to end)"
    return
  fi
  adb shell kill -9 $pids && ended=1 && echo "  ended the page's process ($pids) — the render has to go on" \
    || echo "  (could not end the page's process)"
}

echo "==> uploading the source"
curl -sf -X POST -H "X-Filename: source.mp4" --data-binary @"$SRC" "$BASE/api/source/upload" > "$OUT/upload.json"
echo "==> one click: samples, remix, preview"
job=$(curl -sf -X POST -H "Content-Type: application/json" -d '{"quality": "preview"}' "$BASE/api/auto" \
      | python3 -c "import json, sys; print(json.load(sys.stdin)['id'])")
status=running
start=$(date +%s)
misses=0
peak=0
ended=""
while [ "$status" = running ]; do
  sleep 3
  if ! curl -sf --max-time 20 "$BASE/api/job/$job" > "$OUT/job.json"; then
    misses=$((misses + 1))
    echo "  (the engine did not answer: $misses)"
    [ "$misses" -ge 3 ] && { echo "the engine stopped answering"; exit 1; }
    continue
  fi
  misses=0
  IFS='|' read -r status pct line < <(python3 -c "import json; j = json.load(open('$OUT/job.json')); \
print(f\"{j['status']}|{int(j['progress'] * 100)}|{j['progress']*100:5.1f}%  {j['message']}\")")
  mem=""
  if [ "$APK" != "-" ]; then       # the app's memory (PSS: "TOTAL PSS: <kB>", older Android "TOTAL: <kB>")
    adb shell dumpsys meminfo $PKG > "$OUT/meminfo-now.txt" 2>/dev/null || true
    mem=$(tr -d , < "$OUT/meminfo-now.txt" | awk '/TOTAL PSS:/ {print int($3 / 1024); exit} /^ *TOTAL: / {print int($2 / 1024); exit}')
    if [ -n "$mem" ] && [ "$mem" -gt "$peak" ]; then
      peak=$mem
      cp "$OUT/meminfo-now.txt" "$OUT/meminfo-peak.txt"
    fi
  fi
  echo "  $line  ${mem:+· app $mem MB}"
  if [ -n "$root" ] && [ -z "$ended" ] && [ "$status" = running ] && [ "$pct" -ge 40 ]; then
    end_page
    ended=${ended:-no}
  fi
  if [ $(( $(date +%s) - start )) -gt 2400 ]; then echo "timed out"; break; fi
done
if [ "$status" != done ]; then
  cat "$OUT/job.json"
  exit 1
fi
url=$(python3 -c "import json; print(json.load(open('$OUT/job.json'))['result']['file_url'])")
curl -sf "$BASE$url" -o "$OUT/remix-preview.mp4"
echo "==> rendered in $(( $(date +%s) - start ))s: $(du -h "$OUT/remix-preview.mp4" | cut -f1)"
if [ "$peak" -gt 0 ]; then echo "==> the app used at most ~$peak MB (PSS) while rendering"; fi
if [ "$ended" = 1 ]; then
  now=$(adb shell pidof $PKG | tr -d '\r' || true)
  if [ "$now" != "$app_pid" ]; then echo "the app restarted (pid $app_pid -> ${now:-none}) after its page's process ended"; exit 1; fi
  echo "==> the page's process was ended halfway: the app ($app_pid) kept rendering and made its page again"
  adb logcat -d | grep -a "page process gone" | tail -1 || true
fi
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height -of compact "$OUT/remix-preview.mp4"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/remix-preview.mp4" \
  | python3 -c "import sys; d = float(sys.stdin.read()); print('duration', d); assert d > 20"
