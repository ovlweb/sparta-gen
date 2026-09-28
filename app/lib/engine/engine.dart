// The SpartaGen engine: the audio/video pipeline runs in its own process (desktop), a service (Android) or
// inside the app (iOS), with no window of its own; the app talks to it over localhost with a secret token.

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;

class EngineException implements Exception {
  EngineException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// A job the engine runs in the background (analysis, render, export …).
class JobState {
  JobState({
    required this.id,
    required this.kind,
    required this.status,
    required this.progress,
    required this.message,
    this.result,
    this.error,
  });

  factory JobState.fromJson(Map<String, dynamic> m) => JobState(
        id: '${m['id']}',
        kind: '${m['kind'] ?? ''}',
        status: '${m['status'] ?? 'running'}',
        progress: (m['progress'] as num?)?.toDouble() ?? 0.0,
        message: '${m['message'] ?? ''}',
        result: m['result'],
        error: m['error'] as String?,
      );

  final String id;
  final String kind;
  final String status;
  final double progress;
  final String message;
  final dynamic result;
  final String? error;

  bool get running => status == 'running';
}

/// What the app needs from an engine (the real one over HTTP, or a fake one in tests).
abstract class Engine {
  Future<dynamic> get(String path);
  Future<dynamic> post(String path, [Map<String, dynamic>? body]);

  /// Starts a job and follows it until it ends, reporting every update.
  Future<JobState> runJob(String path, Map<String, dynamic> body, void Function(JobState) onUpdate) async {
    var job = JobState.fromJson(await post(path, body) as Map<String, dynamic>);
    onUpdate(job);
    while (job.running) {
      await Future<void>.delayed(const Duration(milliseconds: 300));
      job = JobState.fromJson(await get('/api/job/${job.id}') as Map<String, dynamic>);
      onUpdate(job);
    }
    return job;
  }

  Future<void> cancelJob(String id) async {
    await post('/api/job/$id/cancel');
  }

  /// An absolute URL for media the engine serves (thumbnails, sample audio), token included.
  String url(String pathAndQuery);

  Future<void> shutdown() async {}
}

class HttpEngine extends Engine {
  HttpEngine(this.base, this.token) : _http = HttpClient()..connectionTimeout = const Duration(seconds: 10);

  final Uri base;
  final String token;
  final HttpClient _http;
  Process? process;

  @override
  Future<dynamic> get(String path) => _send('GET', path);

  @override
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) => _send('POST', path, body ?? const {});

  Future<dynamic> _send(String method, String path, [Object? body]) async {
    final HttpClientRequest req;
    try {
      req = await _http.openUrl(method, base.resolve(path));
    } on SocketException {
      throw EngineException('The SpartaGen engine is not running — restart the app.');
    }
    req.headers.set('X-Sparta-Token', token);
    if (body != null) {
      final bytes = utf8.encode(jsonEncode(body));
      req.headers.contentType = ContentType.json;
      req.contentLength = bytes.length; // the engine reads exactly this many bytes
      req.add(bytes);
    } else {
      req.contentLength = 0;
    }
    final res = await req.close();
    final text = await res.transform(utf8.decoder).join();
    dynamic data;
    try {
      data = text.isEmpty ? null : jsonDecode(text);
    } on FormatException {
      data = text;
    }
    if (res.statusCode >= 400) {
      final msg = data is Map && data['error'] != null ? '${data['error']}' : 'engine error ${res.statusCode}';
      throw EngineException(msg);
    }
    return data;
  }

  @override
  String url(String pathAndQuery) {
    final u = base.resolve(pathAndQuery);
    return u.replace(queryParameters: {...u.queryParameters, 'token': token}).toString();
  }

  @override
  Future<void> shutdown() async {
    try {
      await post('/api/quit').timeout(const Duration(seconds: 2));
    } catch (_) {}
    process?.kill();
    _http.close(force: true);
  }
}

/// Starts the engine and waits until it answers.
class EngineLauncher {
  static const _host = MethodChannel('gen.sparta/engine');
  final StringBuffer _log = StringBuffer();

  String get log => _log.toString();

  Future<HttpEngine> start({void Function(String)? status}) async {
    if (Platform.isAndroid || Platform.isIOS) {     // the engine runs inside the app; its host starts it
      status?.call(Platform.isAndroid ? 'Starting the engine (the first start unpacks it)…' : 'Starting the engine…');
      final r = await _host.invokeMapMethod<String, dynamic>('start');
      if (r == null) throw EngineException('The engine did not start.');
      final engine = HttpEngine(Uri.parse('http://127.0.0.1:${r['port']}/'), '${r['token']}');
      await _waitReady(engine, null, status);
      return engine;
    }
    final port = await _freePort();
    final token = _token();
    final (exe, args) = engineCommand();
    status?.call('Starting the engine…');
    final Process proc;
    try {
      proc = await Process.start(
        exe,
        [...args, 'engine', '--port', '$port', '--token', token, '--parent-pid', '$pid'],
        environment: {'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8'},
      );
    } on ProcessException catch (e) {
      throw EngineException('Could not start the engine ($exe): ${e.message}');
    }
    proc.stdout.transform(utf8.decoder).listen(_append);
    proc.stderr.transform(utf8.decoder).listen(_append);
    final engine = HttpEngine(Uri.parse('http://127.0.0.1:$port/'), token)..process = proc;
    await _waitReady(engine, proc, status);
    return engine;
  }

  void _append(String s) {
    _log.write(s);
    if (_log.length > 20000) {
      final keep = _log.toString().substring(_log.length - 10000);
      _log
        ..clear()
        ..write(keep);
    }
  }

  Future<void> _waitReady(HttpEngine engine, Process? proc, void Function(String)? status) async {
    int? exitCode;
    proc?.exitCode.then((c) => exitCode = c);
    final deadline = DateTime.now().add(const Duration(seconds: 180));
    while (DateTime.now().isBefore(deadline)) {
      if (exitCode != null) {
        throw EngineException('The engine stopped (exit code $exitCode).\n${_tail()}');
      }
      try {
        await engine.get('/api/status');
        return;
      } catch (_) {
        await Future<void>.delayed(const Duration(milliseconds: 300));
      }
    }
    throw EngineException('The engine did not answer in time.\n${_tail()}');
  }

  String _tail() {
    final lines = log.trim().split('\n');
    return lines.sublist(max(0, lines.length - 25)).join('\n');
  }

  /// The engine program: bundled next to the app, or `python -m spartagen` for a source install.
  /// SPARTAGEN_ENGINE overrides it (e.g. "python3 -m spartagen" while developing).
  static (String, List<String>) engineCommand() {
    final env = Platform.environment['SPARTAGEN_ENGINE'];
    if (env != null && env.trim().isNotEmpty) {
      final parts = splitCommand(env);
      return (parts.first, parts.sublist(1));
    }
    final exeDir = File(Platform.resolvedExecutable).parent.path;
    final name = Platform.isWindows ? 'spartagen-engine.exe' : 'spartagen-engine';
    final candidates = [
      p.join(exeDir, 'engine', name),
      if (Platform.isMacOS) p.normalize(p.join(exeDir, '..', 'Resources', 'engine', name)),
    ];
    for (final c in candidates) {
      if (File(c).existsSync()) return (c, const []);
    }
    return (Platform.isWindows ? 'python' : 'python3', const ['-m', 'spartagen']);
  }

  /// Words of a command line; "double quotes" keep a path with spaces in one piece.
  static List<String> splitCommand(String line) => [
        for (final m in RegExp(r'"([^"]*)"|(\S+)').allMatches(line)) m.group(1) ?? m.group(2)!,
      ];

  static Future<int> _freePort() async {
    final s = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    final port = s.port;
    await s.close();
    return port;
  }

  static String _token() {
    final r = Random.secure();
    return List.generate(24, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
  }
}
