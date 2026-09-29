// The app over a fake engine that answers with real responses (test/fixtures, recorded from the
// engine), so every page is built from the data it gets in use.

import 'dart:convert';
import 'dart:io';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sparta_gen/engine/engine.dart';
import 'package:sparta_gen/main.dart';
import 'package:sparta_gen/state/app_state.dart';
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
    if (path == '/api/arrangement/section') {
      final kind = body?['kind'] ?? 'chorus';
      return {'name': 'New part', 'kind': kind, 'bars': body?['bars'] ?? 8, 'layout': 'main', 'tracks': []};
    }
    if (path == '/api/samples/select') return _copy(data['samples']);
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

/// The Look page's settings column (the live preview has a column of its own beside it).
Finder _settingsList() => find.descendant(of: find.byType(PageBody), matching: find.byType(Scrollable)).first;

Future<void> open(WidgetTester tester, String page) async {
  // On a computer the side panel is icons, their words the tooltips; elsewhere the words themselves.
  final rail = find.byType(NavigationRail);
  final tip = find.descendant(of: rail, matching: find.byTooltip(page));
  await tester.tap(tip.evaluate().isNotEmpty ? tip : find.descendant(of: rail, matching: find.text(page)));
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
    expect(find.text('Add a part:'), findsOneWidget);
    expect(find.text('Picture'), findsOneWidget); // the part shown under the timeline
    await open(tester, 'Look & sound');
    expect(find.text('Visual style'), findsOneWidget);
    expect(find.text('Neon'), findsOneWidget);
    expect(find.text('Live preview'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Volumes'), 300, scrollable: _settingsList());
    expect(find.text('Volumes'), findsOneWidget);
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
    expect(find.text('Sparta Remix (Extended base)'), findsOneWidget);
    await tester.tap(find.text('Sparta Stroll Base'));          // a MIDI base: its notes, roles and parts
    await tester.pumpAndSettle();
    expect(engine.posts.any((p) => p.$1 == '/api/template/use' && p.$2?['id'] == 'stroll'), isTrue);
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

  testWidgets('a part added from the palette lands after the part shown, and is saved on Save', (tester) async {
    final engine = await startApp(tester);
    await open(tester, 'Remix');
    final before = (engine.data['arrangement']['sections'] as List).length;
    await tester.tap(find.widgetWithText(ActionChip, 'Epicness'));
    await tester.pumpAndSettle();
    expect(engine.posts.any((p) => p.$1 == '/api/arrangement/section' && p.$2?['kind'] == 'epicness'), isTrue);
    await tester.tap(find.text('Save structure'));
    await tester.pumpAndSettle();
    final saved = engine.posts.lastWhere((p) => p.$1 == '/api/arrangement').$2!;
    final sections = saved['sections'] as List;
    expect(sections.length, before + 1);
    expect((sections[1] as Map)['kind'], 'epicness'); // after the first part, the one shown
  });

  testWidgets('a volume can be switched off and back', (tester) async {
    final engine = await startApp(tester);
    await open(tester, 'Look & sound');
    await tester.scrollUntilVisible(find.byTooltip('Switch Pitches off'), 300, scrollable: _settingsList());
    await tester.tap(find.byTooltip('Switch Pitches off'));
    await tester.pumpAndSettle();
    final sent = engine.posts.lastWhere((p) => p.$1 == '/api/look').$2!;
    expect((sent['mix'] as Map)['mute_groups'], ['pitches']);
  });

  testWidgets('a sample is cut by eye, starting from its cut', (tester) async {
    final engine = await startApp(tester);
    await open(tester, 'Samples');
    await tester.tap(find.text('Cut it myself').first);
    await tester.pumpAndSettle();
    expect(find.text('Use this cut'), findsOneWidget);
    expect(find.text('Type the times'), findsOneWidget); // typing them stays possible
    await tester.tap(find.text('Use this cut'));
    await tester.pumpAndSettle();
    final sent = engine.posts.lastWhere((p) => p.$1 == '/api/samples/select').$2!;
    expect(sent['start'], isA<double>());
    expect((sent['end'] as double) > (sent['start'] as double), isTrue);
  });

  testWidgets('the cutter zooms with the wheel and a drag outside the cut moves the view, not the cut',
      (tester) async {
    final engine = await startApp(tester);
    await open(tester, 'Samples');
    await tester.tap(find.text('Cut it myself').first);
    await tester.pumpAndSettle();
    String label(String key) => (tester.widget(find.byKey(ValueKey(key))) as Text).data!;
    final view = find.byKey(const ValueKey('cutter-view'));
    final from = label('cutter-from'), to = label('cutter-to');
    // The wheel zooms out around the pointer (and the dialog does not scroll instead).
    final mouse = TestPointer(1, PointerDeviceKind.mouse);
    mouse.hover(tester.getCenter(view));
    await tester.sendEventToBinding(mouse.scroll(const Offset(0, 400)));
    await tester.pumpAndSettle();
    expect(label('cutter-from') != from || label('cutter-to') != to, isTrue);
    // Dragging near the view's edge (outside the cut) slides the view along; the cut stays where it was.
    final zoomedFrom = label('cutter-from');
    await tester.dragFrom(tester.getTopLeft(view) + const Offset(6, 130), const Offset(-160, 0));
    await tester.pumpAndSettle();
    expect(label('cutter-from'), isNot(zoomedFrom));
    await tester.tap(find.text('Use this cut'));
    await tester.pumpAndSettle();
    final sent = engine.posts.lastWhere((p) => p.$1 == '/api/samples/select').$2!;
    final sample = (engine.data['samples']['samples'] as List).first as Map;
    expect((sent['start'] as double) - (sample['src_start'] as num), closeTo(0, 0.01));
  });

  testWidgets('the bass is picked and cut like a pitch: a note of its own', (tester) async {
    final engine = await startApp(tester, size: const Size(1400, 2400));          // every card on screen
    await open(tester, 'Samples');
    final bass = find.ancestor(of: find.text('Bass'), matching: find.byType(Card)).first;     // its own card
    expect(find.descendant(of: bass, matching: find.text('Automatic (best)')), findsOneWidget);
    await tester.tap(find.descendant(of: bass, matching: find.text('Cut it myself')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Use this cut'));
    await tester.pumpAndSettle();
    final sent = engine.posts.lastWhere((p) => p.$1 == '/api/samples/select').$2!;
    expect(sent['role'], 'bass');
    expect((sent['end'] as double) > (sent['start'] as double), isTrue);
  });

  test('a new project shows the look the engine starts it with', () async {
    final engine = FakeEngine();
    final app = AppState(engine);
    await app.init();
    (engine.data['look']['video'] as Map)['style'] = 'neon'; // the engine carries the look over
    await app.newProject();
    expect(app.look!['video']['style'], 'neon');
    expect(engine.posts.any((p) => p.$1 == '/api/project/new'), isTrue);
  });

  testWidgets('on a computer the buttons show their icon alone, their words as a tooltip', (tester) async {
    await startApp(tester);
    expect(find.text('Make my Sparta Remix'), findsNothing);
    expect(find.byTooltip('Make my Sparta Remix'), findsOneWidget);
    await open(tester, 'Samples');
    expect(find.byTooltip('Cut it myself'), findsWidgets);
    await tester.tap(find.byTooltip('Cut it myself').first);
    await tester.pumpAndSettle();
    expect(find.byTooltip('Use this cut'), findsOneWidget);
  }, variant: TargetPlatformVariant.only(TargetPlatform.linux));

  testWidgets('on a computer the side panel is its icons alone, their words as tooltips', (tester) async {
    await startApp(tester);
    final rail = find.byType(NavigationRail);
    expect(tester.widget<NavigationRail>(rail).labelType, NavigationRailLabelType.none);
    expect(tester.widget<NavigationRail>(rail).extended, isFalse);
    expect(find.descendant(of: rail, matching: find.byTooltip('Samples')), findsOneWidget);
    expect(find.descendant(of: rail, matching: find.text('SpartaGen')), findsNothing);
    expect(find.descendant(of: rail, matching: find.byTooltip('SpartaGen')), findsOneWidget);
  }, variant: TargetPlatformVariant.only(TargetPlatform.linux));

  testWidgets('a tablet\'s side panel keeps its words', (tester) async {
    await startApp(tester, size: const Size(1000, 800));
    expect(tester.widget<NavigationRail>(find.byType(NavigationRail)).labelType, NavigationRailLabelType.all);
  }, variant: TargetPlatformVariant.only(TargetPlatform.android));

  testWidgets('on a phone they keep their words', (tester) async {
    await startApp(tester, size: const Size(400, 820));
    expect(find.text('Make my Sparta Remix'), findsOneWidget);
  }, variant: TargetPlatformVariant.only(TargetPlatform.android));

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
    expect(find.text('github.com/composition-cassidy'), findsOneWidget);           // Xleth's maker, and a link to it
    expect(find.textContaining('No copyright'), findsOneWidget);                   // public domain: everyone's
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
