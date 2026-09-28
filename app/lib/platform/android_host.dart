// What the Android host adds: videos shared to the app ("Share → SpartaGen"), and Back leaving the app
// running (a render goes on) instead of closing it.

import 'dart:io';

import 'package:flutter/services.dart';

import '../state/app_state.dart';

class AndroidHost {
  static const _engine = MethodChannel('gen.sparta/engine');

  /// Videos shared to the app become the source: one shared before the app was ready, and any later.
  static Future<void> attach(AppState app) async {
    if (!Platform.isAndroid) return;
    Future<void> use(String path) async {
      if (await app.setSource(path)) app.go(AppPage.source);
    }

    _engine.setMethodCallHandler((call) async {
      if (call.method == 'shared' && call.arguments is String) await use(call.arguments as String);
      return null;
    });
    try {
      final path = await _engine.invokeMethod<String>('shared');
      if (path != null && path.isNotEmpty) await use(path);
    } on PlatformException catch (_) {}
  }

  /// Back on the first page: the app goes to the background, the engine keeps working.
  static Future<void> background() async {
    try {
      await _engine.invokeMethod('background');
    } on PlatformException catch (_) {
      await SystemNavigator.pop();
    }
  }
}
