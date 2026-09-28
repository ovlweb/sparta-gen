import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:media_kit/media_kit.dart';

import 'engine/engine.dart';
import 'platform/android_host.dart';
import 'state/app_state.dart';
import 'state/settings.dart';
import 'ui/about.dart';
import 'ui/shell.dart';
import 'ui/theme.dart';
import 'ui/widgets/common.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  MediaKit.ensureInitialized();
  runApp(SpartaGenApp(settings: await AppSettings.load()));
}

class SpartaGenApp extends StatelessWidget {
  const SpartaGenApp({super.key, this.engine, required this.settings});

  /// An engine to use instead of starting one (tests).
  final Engine? engine;
  final AppSettings settings;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: settings,
      builder: (context, _) => MaterialApp(
        title: 'SpartaGen',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(Brightness.light),
        darkTheme: buildTheme(Brightness.dark),
        themeMode: settings.theme,
        home: EngineGate(engine: engine, settings: settings),
      ),
    );
  }
}

/// Starts the engine, then shows the app; says what went wrong when the engine does not start.
class EngineGate extends StatefulWidget {
  const EngineGate({super.key, this.engine, required this.settings});

  final Engine? engine;
  final AppSettings settings;

  @override
  State<EngineGate> createState() => _EngineGateState();
}

class _EngineGateState extends State<EngineGate> {
  final _launcher = EngineLauncher();
  AppState? _app;
  Engine? _engine;
  String _status = 'Starting…';
  Object? _error;
  late final AppLifecycleListener _life;
  bool _quitting = false;

  @override
  void initState() {
    super.initState();
    _life = AppLifecycleListener(onExitRequested: _onExit, onDetach: () => _engine?.shutdown());
    _start();
  }

  Future<AppExitResponse> _onExit() async {
    await _shutdown();
    return AppExitResponse.exit;
  }

  Future<void> _shutdown() async {
    if (_quitting) return;
    _quitting = true;
    try {
      await _app?.saveProject().timeout(const Duration(seconds: 3));
    } catch (_) {}
    await Players.dispose();
    await _engine?.shutdown();
  }

  Future<void> _quit() async {
    await _shutdown();
    if (Platform.isAndroid) {
      await SystemNavigator.pop();
    } else {
      final r = await ServicesBinding.instance.exitApplication(AppExitType.required);
      if (r == AppExitResponse.cancel) exit(0);
    }
  }

  Future<void> _start() async {
    setState(() {
      _error = null;
      _status = 'Starting the engine…';
    });
    try {
      final engine = widget.engine ?? await _launcher.start(status: (s) => mounted ? setState(() => _status = s) : null);
      _engine = engine;
      if (mounted) setState(() => _status = 'Opening your project…');
      final app = AppState(engine);
      await app.init();
      if (!mounted) return;
      setState(() => _app = app);
      debugPrint('SpartaGen: connected to the engine ${app.version}'); // (the emulator test waits for this)
      if (_smokeReport != null) return await _smokeDone(app, null);
      await AndroidHost.attach(app);
    } catch (e) {
      if (_smokeReport != null) return _smokeDone(null, e);
      if (mounted) setState(() => _error = e);
    }
  }

  /// `SPARTAGEN_SMOKE_REPORT=file`: the packaged app starts its bundled engine, writes what it found and quits
  /// (the release builds check with it that every app finds and starts its engine).
  static final String? _smokeReport = Platform.environment['SPARTAGEN_SMOKE_REPORT'];

  Future<void> _smokeDone(AppState? app, Object? error) async {
    final report = <String, dynamic>{
      'ok': error == null && app != null && app.ffmpegOk,
      'engine': EngineLauncher.engineCommand().$1,
      if (app != null) 'version': app.version,
      if (app != null) 'ffmpeg': app.ffmpegOk,
      if (app != null)
        'templates': [
          for (final g in (app.catalog?['groups'] as List? ?? const [])) ...((g as Map)['templates'] as List? ?? const [])
        ].length,
      if (error != null) 'error': '$error',
      if (error != null) 'log': _launcher.log,
    };
    File(_smokeReport!).writeAsStringSync(const JsonEncoder.withIndent(' ').convert(report));
    await _engine?.shutdown();
    exit(report['ok'] == true ? 0 : 1);
  }

  @override
  void dispose() {
    _life.dispose();
    _app?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final app = _app;
    if (app != null) return Shell(app: app, settings: widget.settings, onQuit: Platform.isAndroid || Platform.isIOS ? null : _quit);
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 620),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const AppLogo(size: 84),
              const SizedBox(height: 18),
              Text('SpartaGen', style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w800)),
              const SizedBox(height: 26),
              if (_error == null) ...[
                const SizedBox(width: 240, child: LinearProgressIndicator()),
                const SizedBox(height: 14),
                Text(_status, style: TextStyle(color: cs.onSurfaceVariant)),
              ] else ...[
                Icon(Icons.error_outline, color: cs.error, size: 36),
                const SizedBox(height: 10),
                const Text('The engine did not start', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
                const SizedBox(height: 10),
                Container(
                  constraints: const BoxConstraints(maxHeight: 260),
                  width: double.infinity,
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(color: cs.surfaceContainer, borderRadius: BorderRadius.circular(10)),
                  child: SingleChildScrollView(
                    child: SelectableText('$_error',
                        style: const TextStyle(fontFamily: 'monospace', fontSize: 12.5, fontFeatures: [FontFeature.tabularFigures()])),
                  ),
                ),
                const SizedBox(height: 16),
                Wrap(spacing: 12, children: [
                  FilledButton.icon(onPressed: _start, icon: const Icon(Icons.refresh), label: const Text('Try again')),
                  OutlinedButton.icon(
                    onPressed: () => Clipboard.setData(ClipboardData(text: '$_error\n\n${_launcher.log}')),
                    icon: const Icon(Icons.copy),
                    label: const Text('Copy the details'),
                  ),
                ]),
              ],
            ]),
          ),
        ),
      ),
    );
  }
}
