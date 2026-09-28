# Sparta Gen — the app

The native app of Sparta Gen for Windows, macOS, Linux and Android, written in Flutter.
It has no web page inside: the windows, menus, file dialogs and players are the system's own.

The audio/video work is done by the Sparta Gen engine (the `spartagen` Python package), which the app
starts in the background and talks to over localhost with a secret token:

* **Windows / macOS / Linux** — the app starts `engine/spartagen-engine` (bundled next to it; built with
  PyInstaller from `packaging/engine.spec`). While developing, point it at a source checkout instead:
  `SPARTAGEN_ENGINE="python3 -m spartagen" flutter run -d linux` (from the repository root, or with
  `PYTHONPATH` set to it).
* **Android** — the engine runs inside the app (Chaquopy) as a foreground service; the app asks it for its
  port and token over a method channel.

## Layout

```
lib/
  main.dart            starts the engine, then the app; says what went wrong when it cannot
  engine/engine.dart   the engine client (HTTP + token) and the launcher
  state/app_state.dart everything the pages show and do
  platform/files.dart  the system's Open / Save dialogs (Android: the document picker and "Save as")
  ui/shell.dart        navigation (side rail / bottom bar), menus and shortcuts, job progress
  ui/pages/*.dart      Source, Base, Samples, Remix, Look & sound, Export
  ui/about.dart        About — and the credit to Krasen (CassidyBOTRR)
```

## Build

```
flutter pub get
flutter build linux      # or windows, macos, apk
```

Linux needs `libmpv2` (Debian/Ubuntu: `sudo apt install libmpv2`) for the players.
