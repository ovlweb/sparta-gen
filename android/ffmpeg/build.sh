#!/usr/bin/env bash
# Build ffmpeg (with x264) for Android and drop it into the app as jniLibs/<abi>/libffmpeg.so.
#
# Android only lets an app run programs from its native-library folder, so the ffmpeg program is
# packaged like a library; the engine finds it there (spartagen/android.py).
#
#   ANDROID_NDK_HOME=/path/to/ndk  ABIS="arm64-v8a x86_64"  bash android/ffmpeg/build.sh
#
# Needs: the Android NDK (r26+), make, pkg-config, curl; nasm for x86_64.  Everything is linked
# statically except Android's own libc/libm/libdl/libz, so the program runs on any device from
# Android 7 (API 24).  GPL: x264 is GPL, so this ffmpeg is too.
set -euo pipefail

NDK="${ANDROID_NDK_HOME:-${ANDROID_NDK_LATEST_HOME:-${ANDROID_NDK_ROOT:-}}}"
[ -d "$NDK" ] || { echo "Set ANDROID_NDK_HOME to the Android NDK"; exit 1; }
API="${ANDROID_API:-24}"
ABIS="${ABIS:-arm64-v8a x86_64}"
FFMPEG_VERSION="${FFMPEG_VERSION:-7.1.1}"
X264_BRANCH="${X264_BRANCH:-stable}"
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${OUT:-$HERE/../app/src/main/jniLibs}"
WORK="${WORK:-$HERE/build}"
JOBS="$(nproc 2>/dev/null || echo 4)"
case "$(uname -s)" in Darwin) HOST=darwin-x86_64 ;; *) HOST=linux-x86_64 ;; esac
TC="$NDK/toolchains/llvm/prebuilt/$HOST"

mkdir -p "$WORK" "$OUT"
cd "$WORK"
fetch() {   # url dir: unpack a source archive into dir (whatever its top folder is called)
  [ -d "$2" ] && return 0
  mkdir -p "$2.part" && curl -fsSL --retry 3 "$1" | tar xz -C "$2.part" --strip-components=1 && mv "$2.part" "$2"
}
fetch "https://github.com/FFmpeg/FFmpeg/archive/refs/tags/n${FFMPEG_VERSION}.tar.gz" ffmpeg-src
fetch "https://code.videolan.org/videolan/x264/-/archive/${X264_BRANCH}/x264-${X264_BRANCH}.tar.gz" x264-src

for ABI in $ABIS; do
  case "$ABI" in
    arm64-v8a)   TRIPLE=aarch64-linux-android;    ARCH=aarch64; CPU=armv8-a; X264_HOST=aarch64-linux-android ;;
    armeabi-v7a) TRIPLE=armv7a-linux-androideabi; ARCH=arm;     CPU=armv7-a; X264_HOST=arm-linux-androideabi ;;
    x86_64)      TRIPLE=x86_64-linux-android;     ARCH=x86_64;  CPU="";      X264_HOST=x86_64-linux-android ;;
    *) echo "unknown ABI $ABI"; exit 1 ;;
  esac
  CC="$TC/bin/${TRIPLE}${API}-clang"
  PREFIX="$WORK/prefix-$ABI"
  echo "==> x264 for $ABI"
  rm -rf "x264-$ABI" && cp -r x264-src "x264-$ABI"
  (
    cd "x264-$ABI"
    X264_EXTRA=()
    if [ "$ABI" = armeabi-v7a ]; then X264_EXTRA+=(--extra-cflags="-mfpu=neon -mfloat-abi=softfp"); fi
    CC="$CC" AR="$TC/bin/llvm-ar" RANLIB="$TC/bin/llvm-ranlib" STRIP="$TC/bin/llvm-strip" \
      ./configure --prefix="$PREFIX" --host="$X264_HOST" --sysroot="$TC/sysroot" \
        --enable-static --enable-pic --disable-cli --disable-opencl ${X264_EXTRA[@]+"${X264_EXTRA[@]}"}
    make -j"$JOBS" && make install
  )
  echo "==> ffmpeg $FFMPEG_VERSION for $ABI"
  rm -rf "ffmpeg-$ABI" && mkdir "ffmpeg-$ABI"
  (
    cd "ffmpeg-$ABI"
    FF_EXTRA=()
    if [ -n "$CPU" ]; then FF_EXTRA+=(--cpu="$CPU"); fi
    if [ "$ABI" = armeabi-v7a ]; then FF_EXTRA+=(--enable-neon); fi
    PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig" PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig" \
    ../ffmpeg-src/configure \
      --prefix="$PREFIX" --target-os=android --arch="$ARCH" --enable-cross-compile \
      --cc="$CC" --cxx="${CC}++" --ar="$TC/bin/llvm-ar" --ranlib="$TC/bin/llvm-ranlib" \
      --nm="$TC/bin/llvm-nm" --strip="$TC/bin/llvm-strip" --sysroot="$TC/sysroot" \
      --pkg-config=pkg-config --pkg-config-flags=--static \
      --enable-gpl --enable-libx264 --enable-zlib --disable-autodetect \
      --enable-static --disable-shared --enable-pic \
      --disable-doc --disable-ffplay --disable-ffprobe --disable-debug --disable-network \
      --disable-vulkan --disable-jni --disable-mediacodec \
      --extra-cflags="-I$PREFIX/include -O2 -fPIC" --extra-ldflags="-L$PREFIX/lib" --extra-libs="-lm" \
      ${FF_EXTRA[@]+"${FF_EXTRA[@]}"}
    make -j"$JOBS" ffmpeg
    mkdir -p "$OUT/$ABI"
    "$TC/bin/llvm-strip" -o "$OUT/$ABI/libffmpeg.so" ffmpeg
  )
  ls -la "$OUT/$ABI/libffmpeg.so"
done
