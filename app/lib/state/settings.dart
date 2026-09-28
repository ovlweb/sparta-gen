// The app's own settings (not the project's): kept in the app's support folder.

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';

class AppSettings extends ChangeNotifier {
  AppSettings._(this._file, this.theme);

  /// Settings that are not saved anywhere (tests, or no support folder).
  AppSettings.memory()
      : _file = null,
        theme = ThemeMode.system;

  final File? _file;
  ThemeMode theme;

  static Future<AppSettings> load() async {
    try {
      final dir = await getApplicationSupportDirectory();
      final file = File('${dir.path}${Platform.pathSeparator}settings.json');
      var theme = ThemeMode.system;
      if (file.existsSync()) {
        final m = jsonDecode(file.readAsStringSync());
        if (m is Map) theme = ThemeMode.values.asNameMap()['${m['theme']}'] ?? ThemeMode.system;
      }
      return AppSettings._(file, theme);
    } catch (_) {
      return AppSettings.memory();
    }
  }

  Future<void> setTheme(ThemeMode mode) async {
    theme = mode;
    notifyListeners();
    try {
      await _file?.parent.create(recursive: true);
      await _file?.writeAsString(jsonEncode({'theme': mode.name}));
    } catch (_) {}
  }

  /// System → light → dark → system.
  Future<void> nextTheme() => setTheme(switch (theme) {
        ThemeMode.system => ThemeMode.light,
        ThemeMode.light => ThemeMode.dark,
        ThemeMode.dark => ThemeMode.system,
      });

  static IconData iconOf(ThemeMode m) => switch (m) {
        ThemeMode.system => Icons.brightness_auto,
        ThemeMode.light => Icons.light_mode,
        ThemeMode.dark => Icons.dark_mode,
      };

  static String nameOf(ThemeMode m) => switch (m) {
        ThemeMode.system => 'Theme: as the system',
        ThemeMode.light => 'Theme: light',
        ThemeMode.dark => 'Theme: dark',
      };
}
