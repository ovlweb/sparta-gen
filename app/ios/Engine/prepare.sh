#!/usr/bin/env bash
# What the iOS app's engine needs, fetched before `flutter build ios` (on a Mac with Xcode; ~350 MB, not in the
# repository).  Run it again any time: it skips what is already here.
#
#   Frameworks/Python.xcframework        Python for iOS — CPython's own iOS build, from BeeWare's
#                                        Python-Apple-support
#   Frameworks/ffmpegkit.xcframework …   FFmpegKit: ffmpeg as a library (the full-gpl build: x264, lame, opus …),
#                                        its device + simulator frameworks made into xcframeworks
#   site-packages/iphoneos, iphonesimulator   numpy (built for iOS), yt-dlp and certifi, for the device and the
#                                        simulator
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_SUPPORT=3.13-b15      # https://github.com/beeware/Python-Apple-support/releases
PYTHON_VERSION=3.13
FFMPEGKIT_VERSION=8.1.2      # https://github.com/sk3llo/ffmpeg_kit_flutter/releases (a maintained FFmpegKit)
FFMPEGKIT_VARIANT=full-gpl
FFMPEGKIT_FRAMEWORKS="ffmpegkit libavcodec libavdevice libavfilter libavformat libavutil libswresample libswscale"
PACKAGES="numpy yt-dlp certifi"
# numpy for iOS: BeeWare's and Flet's package indexes (PyPI has no iOS builds of it yet)
INDEXES="--extra-index-url https://pypi.anaconda.org/beeware/simple --extra-index-url https://pypi.flet.dev"

mkdir -p Frameworks site-packages .downloads

fetch() {   # url file
  if [ ! -s "$2" ]; then
    echo "downloading $1"
    curl -fL --retry 3 --retry-delay 2 -o "$2.part" "$1"
    mv "$2.part" "$2"
  fi
}

# ── Python ──
if [ ! -d Frameworks/Python.xcframework ]; then
  fetch "https://github.com/beeware/Python-Apple-support/releases/download/$PYTHON_SUPPORT/Python-$PYTHON_VERSION-iOS-support.${PYTHON_SUPPORT#*-}.tar.gz" \
    .downloads/python.tar.gz
  rm -rf .downloads/python && mkdir -p .downloads/python
  tar -xzf .downloads/python.tar.gz -C .downloads/python
  mv .downloads/python/Python.xcframework Frameworks/
  cat .downloads/python/VERSIONS
fi

# ── FFmpegKit ──
# Its frameworks are "fat": device arm64 (+ arm64e) and simulator x86_64 in one binary.  An xcframework needs a
# device slice (arm64) and a simulator slice — x86_64, and arm64 for Apple silicon Macs: the device arm64 code
# marked as simulator code (plain C, the same instructions).
if [ ! -d Frameworks/ffmpegkit.xcframework ]; then
  fetch "https://github.com/sk3llo/ffmpeg_kit_flutter/releases/download/$FFMPEGKIT_VERSION-$FFMPEGKIT_VARIANT/ffmpeg-kit-ios-$FFMPEGKIT_VARIANT-$FFMPEGKIT_VERSION.zip" \
    .downloads/ffmpegkit.zip
  rm -rf .downloads/ffmpegkit && mkdir -p .downloads/ffmpegkit
  unzip -q .downloads/ffmpegkit.zip -d .downloads/ffmpegkit
  for fw in $FFMPEGKIT_FRAMEWORKS; do
    src=".downloads/ffmpegkit/$fw.framework"
    bin="$src/$fw"
    xcrun bitcode_strip -r "$bin" -o "$bin" 2>/dev/null || true
    minos=$(otool -l -arch arm64 "$bin" | awk '/LC_BUILD_VERSION/ {b = 1} b && /minos/ {print $2; exit}')
    sdk=$(otool -l -arch arm64 "$bin" | awk '/LC_BUILD_VERSION/ {b = 1} b && /sdk/ {print $2; exit}')
    minos=${minos:-14.0}
    work=".downloads/xcframework/$fw"
    rm -rf "$work" && mkdir -p "$work/device" "$work/simulator"
    cp -R "$src" "$work/device/$fw.framework"
    cp -R "$src" "$work/simulator/$fw.framework"
    lipo "$bin" -thin arm64 -output "$work/device/$fw.framework/$fw"
    lipo "$bin" -thin arm64 -output "$work/arm64"
    vtool -arch arm64 -set-build-version 7 "$minos" "${sdk:-$minos}" -replace -output "$work/arm64-simulator" "$work/arm64"
    lipo "$bin" -thin x86_64 -output "$work/x86_64"
    lipo -create "$work/arm64-simulator" "$work/x86_64" -output "$work/simulator/$fw.framework/$fw"
    rm -rf "Frameworks/$fw.xcframework"
    xcodebuild -create-xcframework -framework "$work/device/$fw.framework" -framework "$work/simulator/$fw.framework" \
      -output "Frameworks/$fw.xcframework"
  done
fi

# ── the engine's packages ──
PIP="${PYTHON:-python3} -m pip"
for platform in iphoneos iphonesimulator; do
  [ -d "site-packages/$platform/numpy" ] && continue
  rm -rf "site-packages/$platform"
  tags=""
  for v in 13_0 12_0; do tags="$tags --platform ios_${v}_arm64_$platform"; done
  # shellcheck disable=SC2086
  $PIP install --disable-pip-version-check --no-compile --only-binary=:all: --target "site-packages/$platform" \
    $tags --python-version "$PYTHON_VERSION" --implementation cp $INDEXES $PACKAGES
done
echo "the iOS engine is ready:"
du -sh Frameworks/* site-packages/* | sed 's/^/  /'
