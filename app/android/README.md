# SpartaGen for Android

The APK holds the whole app: the Flutter app (the same one as on Windows, macOS and Linux — native screens,
the system's document picker and "Save as", no web page), the repository's `spartagen` engine (Python 3.12
via [Chaquopy](https://chaquo.com/chaquopy/), with numpy and yt-dlp) and ffmpeg built for Android. Nothing
else to install on the phone.

| Piece | Where |
|---|---|
| The app (every page, the players) | `../lib/` (Flutter) |
| Android host: starts the engine and hands the app its port and secret token; document picker, "Save as", "Share → SpartaGen" | `app/src/main/java/gen/sparta/remix/MainActivity.java` |
| Engine service (starts Python and the engine, keeps renders going with the screen off) | `EngineService.java` → `spartagen/android.py` |
| ffmpeg + x264 for Android, packaged as `jniLibs/<abi>/libffmpeg.so` | `ffmpeg/build.sh` |
| Emulator test: the engine up (and closed to anyone without its token), ffmpeg usable, the one-click remix rendered — and still rendering after the app is sent to the background halfway | `test/smoke.sh`, `test/make_source.py` |

Android lets an app run programs only from its native-library folder, so ffmpeg ships as `libffmpeg.so`
(`useLegacyPackaging` keeps it extracted there) and the engine is pointed at it (`SPARTAGEN_FFMPEG`).

## Get the APK

GitHub → **Actions** → **Android app** → a run → **Artifacts** → `SpartaGen-Android`, or the release of a
`v*` tag (with the other apps). Pushes that change `spartagen/` or `app/` build it, and so does *Run workflow*.

## Build it yourself

Needs Flutter, JDK 17, Python 3.12 (Chaquopy builds with the app's Python version), the Android SDK and NDK
r26+, plus `make`, `pkg-config` and `nasm` (for x86_64).

```bash
ANDROID_NDK_HOME=$ANDROID_HOME/ndk/<version> ABIS="arm64-v8a" bash app/android/ffmpeg/build.sh   # ~10 min, once
cd app
flutter build apk --release --target-platform android-arm64     # build/app/outputs/flutter-apk/app-release.apk
flutter build apk --debug --target-platform android-x64         # for an x86_64 emulator (build its ffmpeg first)
```

Each ABI needs its ffmpeg from `ffmpeg/build.sh` — the build stops early with the command to run if one is
missing.

Test a debug APK on a running emulator or a phone with USB debugging:

```bash
python app/android/test/make_source.py /tmp/source.mp4
bash app/android/test/smoke.sh app/build/app/outputs/flutter-apk/app-debug.apk /tmp/source.mp4 /tmp/android-test
```

## Signing

Every build is signed with `sideload.keystore` (password `android`, alias `sparta-gen`), committed here on purpose so
that each new APK installs over the previous one without uninstalling — including the earlier SpartaGen APKs,
which had the same id (`gen.sparta.remix`) and key. It only proves "built from this repository" — to publish
the app, sign with a key of your own: set `SPARTAGEN_KEYSTORE`, `SPARTAGEN_KEYSTORE_PASSWORD`,
`SPARTAGEN_KEY_ALIAS` and `SPARTAGEN_KEY_PASSWORD` when building, or in CI add the repository secrets
`SPARTAGEN_KEYSTORE_B64` (the keystore, base64) and the three others. An APK signed with a different key does
not install over one signed with this key (uninstall first).

## Licence note

The bundled ffmpeg is built with x264, so that binary is under the GPL.
