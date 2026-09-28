# SpartaGen — the app

The native app of SpartaGen for Windows, macOS, Linux, Android and iOS, written in Flutter.
It has no web page inside: the windows, menus, file dialogs and players are the system's own.

The audio/video work is done by the SpartaGen engine (the `spartagen` Python package), which the app
starts in the background and talks to over localhost with a secret token:

* **Windows / macOS / Linux** — the app starts `engine/spartagen-engine` (bundled next to it, or in
  `Contents/Resources/engine` on macOS; frozen with PyInstaller from `packaging/engine.py` by
  `scripts/build_desktop.py`). While developing, point it at a source checkout instead:
  `SPARTAGEN_ENGINE="python3 -m spartagen" flutter run -d linux` (from the repository root, or with
  `PYTHONPATH` set to it).
* **Android** — the engine runs inside the app (Chaquopy) as a foreground service; the app asks it for its
  port and token over a method channel.
* **iOS** — the engine runs inside the app too (no app may start a program on iOS): `ios/Runner/SpartaGenEngine.m`
  starts Python for iOS and hands the engine ffmpeg as a function (FFmpegKit); the same method channel gives the app
  its port and token.  `ios/Engine/prepare.sh` fetches Python, FFmpegKit and numpy for iOS before the first build
  (on a Mac), and the Xcode build phase `ios/Engine/install.sh` puts them and the engine into the app.

## Layout

```
lib/
  main.dart            starts the engine, then the app; says what went wrong when it cannot
  engine/engine.dart   the engine client (HTTP + token) and the launcher
  state/app_state.dart everything the pages show and do
  state/settings.dart  the app's own settings (the theme)
  platform/files.dart  the system's Open / Save dialogs (Android: the document picker and "Save as")
  platform/android_host.dart  Android: videos shared to the app, Back leaving it running
ios/Runner/          the iOS host: the engine inside the app (SpartaGenEngine.m), Photos picker, share sheet
  ui/shell.dart        navigation (side rail / bottom bar), menus and shortcuts, job progress
  ui/pages/*.dart      Source, Base, Samples, Remix, Look & sound, Export
  ui/about.dart        About — and the credit to Krasen (CassidyBOTRR)
```

## Build

```
flutter pub get
flutter build linux      # or windows, macos, apk (see android/README.md), ios (ios/Engine/prepare.sh first)
python ../scripts/build_desktop.py --test   # the whole desktop app: engine inside, tested, zipped
```

Linux needs `libmpv2` (Debian/Ubuntu: `sudo apt install libmpv2`) for the players.
