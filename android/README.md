# Sparta Gen for Android

The APK holds the whole app: the repository's `spartagen` engine (Python 3.12 via
[Chaquopy](https://chaquo.com/chaquopy/), with numpy and yt-dlp), its web app shown in a full-screen WebView, and
ffmpeg built for Android. Nothing else to install on the phone.

| Piece | Where |
|---|---|
| App shell (WebView, file picker, downloads → Movies/Music/Download, "Share → Sparta Gen") | `app/src/main/java/gen/sparta/remix/MainActivity.java`, `Saver.java` |
| Engine service (starts Python and the local server, keeps renders going with the screen off) | `EngineService.java` → `spartagen/android.py` |
| ffmpeg + x264 for Android, packaged as `jniLibs/<abi>/libffmpeg.so` | `ffmpeg/build.sh` |
| Emulator test: engine up, ffmpeg usable, one-click remix rendered | `test/smoke.sh`, `test/make_source.py` |

Android lets an app run programs only from its native-library folder, so ffmpeg ships as `libffmpeg.so`
(`useLegacyPackaging` keeps it extracted there) and the engine is pointed at it (`SPARTAGEN_FFMPEG`).

## Get the APK

GitHub → **Actions** → **android** → latest run → **Artifacts** → `SpartaGen-Android-APK`, or the release of a
`v*` tag. Every push that touches `spartagen/` or `android/` builds it.

## Build it yourself

Needs JDK 17, Python 3.12 (Chaquopy builds with the app's Python version), the Android SDK (`ANDROID_HOME`) and
NDK r26+, plus `make`, `pkg-config` and `nasm` (for x86_64).

```bash
ANDROID_NDK_HOME=$ANDROID_HOME/ndk/<version> ABIS="arm64-v8a" bash android/ffmpeg/build.sh   # ~10 min, once
cd android
./gradlew assembleRelease                       # app/build/outputs/apk/release/app-release.apk
./gradlew assembleDebug -Pabis=x86_64           # for an x86_64 emulator (build its ffmpeg first)
```

`-Pabis=` picks the ABIs (default `arm64-v8a`, set in `gradle.properties`); each needs its ffmpeg from
`ffmpeg/build.sh` — the build stops early with the command to run if one is missing.

Test an APK on a running emulator or a phone with USB debugging:

```bash
python android/test/make_source.py /tmp/source.mp4
bash android/test/smoke.sh android/app/build/outputs/apk/debug/app-debug.apk /tmp/source.mp4 /tmp/android-test
```

## Signing

Every build is signed with `sideload.keystore` (password `android`, alias `sparta-gen`), committed here on purpose so
that each new APK installs over the previous one without uninstalling. It only proves "built from this
repository" — to publish the app, sign with a key of your own: set `SPARTAGEN_KEYSTORE`,
`SPARTAGEN_KEYSTORE_PASSWORD`, `SPARTAGEN_KEY_ALIAS` and `SPARTAGEN_KEY_PASSWORD` when building, or in CI add the
repository secrets `SPARTAGEN_KEYSTORE_B64` (the keystore, base64) and the three others. An APK signed with a
different key does not install over one signed with this key (uninstall first).

## Licence note

The bundled ffmpeg is built with x264, so that binary is under the GPL.
