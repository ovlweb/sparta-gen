// The app over a fake engine that answers with real responses (test/fixtures, recorded from the
// engine), so every page is built from the data it gets in use.

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sparta_gen/engine/engine.dart';
import 'package:sparta_gen/main.dart';
import 'package:sparta_gen/state/settings.dart';
import 'package:sparta_gen/ui/widgets/common.dart';

class FakeEngine extends Engine {
  FakeEngine() {
    for (final name in ['status', 'look', 'templates', 'patterns', 'samples', 'arrangement', 'project']) {
      data[name] = jsonDecode(File('test/fixtures/$name.json').readAsStringSync());
    }
  }

  final Map<String, dynamic> data = {};
  final List<(String, Map<String, dynamic>?)> posts = [];

  @override
  Future<dynamic> get(String path) async {
    final key = path.replaceFirst('/api/', '');
    if (data.containsKey(key)) return _copy(data[key]);
    if (path == '/api/projects') return {'projects': []};
    throw EngineException('no fixture for GET $path');
  }

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) async {
    posts.add((path, body));
    if (path == '/api/look') return _copy(data['look']);
    if (path == '/api/arrangement') return _copy(data['arrangement']);
    return {'project': _copy(data['project'])};
  }

  static dynamic _copy(dynamic v) => jsonDecode(jsonEncode(v));

  @override
  String url(String pathAndQuery) => 'http://127.0.0.1:9/${pathAndQuery.replaceFirst('/', '')}';
}

Future<FakeEngine> startApp(WidgetTester tester, {Size size = const Size(1400, 900)}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  final engine = FakeEngine();
  await tester.pumpWidget(SpartaGenApp(engine: engine, settings: AppSettings.memory()));
  await tester.pumpAndSettle();
  return engine;
}

Future<void> open(WidgetTester tester, String page) async {
  await tester.tap(find.descendant(of: find.byType(NavigationRail), matching: find.text(page)));
  await tester.pumpAndSettle();
}

void main() {
  setUpAll(() => Players.enabled = false);

  testWidgets('opens on the Source page with the engine’s project', (tester) async {
    await startApp(tester);
    expect(find.text('Source'), findsWidgets);
    expect(find.text('source.mp4'), findsOneWidget);
    expect(find.text('Make my Sparta Remix'), findsOneWidget);
    expect(find.textContaining('MIDI base'), findsWidgets); // what the remix is built on
  });

  testWidgets('every page opens', (tester) async {
    await startApp(tester);
    await open(tester, 'Base');
    expect(find.text('Channels'), findsOneWidget); // the project is on a MIDI base
    await open(tester, 'Samples');
    expect(find.text('Tuning'), findsOneWidget);
    expect(find.text('Chorus — part 1'), findsOneWidget);
    await open(tester, 'Remix');
    expect(find.text('Structure'), findsOneWidget);
    expect(find.text('Add before the ending'), findsOneWidget);
    await open(tester, 'Look & sound');
    expect(find.text('Visual style'), findsOneWidget);
    expect(find.text('Neon'), findsOneWidget);
    await open(tester, 'Export');
    expect(find.text('Also export'), findsOneWidget);
    expect(find.text('Export MIDI…'), findsOneWidget);
  });

  testWidgets('the templates are listed and one can be chosen', (tester) async {
    final engine = await startApp(tester);
    await open(tester, 'Base');
    await tester.tap(find.text('Template'));
    await tester.pumpAndSettle();
    expect(find.text('Base templates'), findsOneWidget);
    await tester.tap(find.textContaining('Extended (2:08)').first);
    await tester.pumpAndSettle();
    expect(engine.posts.any((p) => p.$1 == '/api/template/use' && p.$2?['id'] == 'extended'), isTrue);
  });

  testWidgets('picking a visual style sends it, and resets the effects to it', (tester) async {
    final engine = await startApp(tester);
    await open(tester, 'Look & sound');
    await tester.tap(find.text('Neon'));
    await tester.pumpAndSettle();
    final sent = engine.posts.lastWhere((p) => p.$1 == '/api/look').$2!;
    final video = sent['video'] as Map;
    expect(video['style'], 'neon');
    expect(video.containsKey('shake') && video['shake'] == null, isTrue);
  });

  testWidgets('editing the structure is saved only on Save', (tester) async {
    final engine = await startApp(tester);
    await open(tester, 'Remix');
    expect(find.text('Save structure'), findsNothing);
    await tester.tap(find.byTooltip('Duplicate').first);
    await tester.pumpAndSettle();
    expect(find.text('Save structure'), findsOneWidget);
    expect(engine.posts.where((p) => p.$1 == '/api/arrangement'), isEmpty);
    await tester.tap(find.text('Save structure'));
    await tester.pumpAndSettle();
    final saved = engine.posts.lastWhere((p) => p.$1 == '/api/arrangement').$2!;
    final before = (engine.data['arrangement']['sections'] as List).length;
    expect((saved['sections'] as List).length, before + 1);
  });

  testWidgets('a phone gets a bottom bar and a menu', (tester) async {
    await startApp(tester, size: const Size(400, 820));
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.byType(NavigationRail), findsNothing);
    await tester.tap(find.byIcon(Icons.ios_share_outlined));
    await tester.pumpAndSettle();
    expect(find.text('Export'), findsWidgets);
  });

  testWidgets('the theme button goes light, dark, then back to the system’s', (tester) async {
    await startApp(tester);
    Brightness now() => Theme.of(tester.element(find.text('Make my Sparta Remix'))).brightness;
    await tester.tap(find.byTooltip('Theme: as the system'));
    await tester.pumpAndSettle();
    expect(now(), Brightness.light);
    await tester.tap(find.byTooltip('Theme: light'));
    await tester.pumpAndSettle();
    expect(now(), Brightness.dark);
    await tester.tap(find.byTooltip('Theme: dark'));
    await tester.pumpAndSettle();
    expect(find.byTooltip('Theme: as the system'), findsOneWidget);
  });

  testWidgets('About credits Krasen', (tester) async {
    await startApp(tester);
    await tester.tap(find.byTooltip('About SpartaGen'));
    await tester.pumpAndSettle();
    expect(find.text('Inspired by Krasen (CassidyBOTRR)'), findsOneWidget);
    expect(find.text('youtube.com/c/CassidyBOTRR'), findsOneWidget);
  });

  test('an engine command keeps a quoted path with spaces in one piece', () {
    expect(EngineLauncher.splitCommand('"/home/a b/.venv/bin/python" -m spartagen'),
        ['/home/a b/.venv/bin/python', '-m', 'spartagen']);
    expect(EngineLauncher.splitCommand('python3 -m  spartagen'), ['python3', '-m', 'spartagen']);
  });

  testWidgets('when the engine does not start, the app says why and can try again', (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(SpartaGenApp(engine: _BrokenEngine(), settings: AppSettings.memory()));
    await tester.pumpAndSettle();
    expect(find.text('The engine did not start'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
  });
}

class _BrokenEngine extends FakeEngine {
  @override
  Future<dynamic> get(String path) async => throw EngineException('engine exploded');
}
