// Everything the pages show and do, over the engine.

import 'dart:async';

import 'dart:io';

import 'package:file_selector/file_selector.dart';
import 'package:flutter/foundation.dart';

import '../engine/engine.dart';
import '../platform/files.dart';

class AppMessage {
  AppMessage(this.text, {this.error = false, this.action, this.onAction});
  final String text;
  final bool error;
  final String? action;
  final VoidCallback? onAction;
}

/// Pages of the app, in order.
enum AppPage { source, base, samples, remix, look, export }

class AppState extends ChangeNotifier {
  AppState(this.engine);

  final Engine engine;

  Map<String, dynamic> status = {};
  Map<String, dynamic> project = {};
  Map<String, dynamic>? look;
  Map<String, dynamic>? catalog; // base templates, grouped
  Map<String, dynamic>? bank; // samples and their candidates
  Map<String, dynamic>? patterns; // the pattern library
  Map<String, dynamic>? arrangement; // the full arrangement, for the editor
  JobState? job;
  String jobLabel = '';
  AppPage page = AppPage.source;
  String? lastRender; // the file the preview player shows

  final _messages = StreamController<AppMessage>.broadcast();
  Stream<AppMessage> get messages => _messages.stream;

  // ── views ──
  bool get busy => job?.running ?? false;
  Map<String, dynamic>? get source => _map(project['source']);
  bool get hasSource => source != null;
  bool get analyzed => project['analyzed'] == true;
  String get variant => '${project['variant'] ?? 'unextended'}';
  Map<String, dynamic>? get midi => _map(project['midi']);
  Map<String, dynamic>? get baseMap => _map(project['base']);
  String? get basePath => project['base_path'] as String?;
  Map<String, dynamic>? get template => _map(project['template']);
  Map<String, dynamic>? get arrangementSummary => _map(project['arrangement']);
  Map<String, dynamic> get outputs => _map(project['outputs']) ?? {};
  String get key => '${project['key'] ?? 'D'}';
  String get keyMode => '${project['key_mode'] ?? 'auto'}';
  String get workspace => '${project['workspace'] ?? ''}';
  String get name => '${project['name'] ?? 'Untitled Sparta Remix'}';
  bool get ffmpegOk => status['ffmpeg'] == true;
  String get version => '${status['version'] ?? ''}';

  /// What the remix is built on, in words.
  String get builtOn {
    if (variant == 'midi' && midi != null) {
      final s = _map(midi!['summary']) ?? {};
      return 'MIDI base · ${_fmtBpm(s['bpm'])} · ${s['key'] ?? ''}';
    }
    if (variant == 'base' && baseMap != null) {
      final b = baseMap!;
      final t = _map(project['base_template_info']);
      return 'your base${t != null ? ' (${t['name']})' : ''} · ${_fmtBpm(b['bpm'])} · $key';
    }
    final t = template;
    if (t != null) return '${t['name']} · ${_fmtBpm(t['bpm'])} · ${t['key']}';
    return variant;
  }

  static String _fmtBpm(dynamic v) {
    final d = (v as num?)?.toDouble();
    if (d == null) return '';
    return '${d == d.roundToDouble() ? d.toStringAsFixed(0) : d.toStringAsFixed(1)} BPM';
  }

  static Map<String, dynamic>? _map(dynamic v) => v is Map ? v.cast<String, dynamic>() : null;

  // ── plumbing ──
  void info(String text, {String? action, VoidCallback? onAction}) =>
      _messages.add(AppMessage(text, action: action, onAction: onAction));
  void fail(Object e) => _messages.add(AppMessage('$e', error: true));

  /// The system's Open dialog; problems are shown, not thrown.
  Future<String?> pickFile(XTypeGroup kind) async {
    try {
      return await Files.open(kind);
    } on FileSystemException catch (e) {
      fail(e.message);
    } catch (e) {
      fail('Could not open the file: $e');
    }
    return null;
  }

  /// The system's Save dialog, then [write] to where the user chose; problems are shown, not thrown.
  Future<String?> saveFile({
    required String suggestedName,
    required XTypeGroup kind,
    required String mime,
    required Future<bool> Function(String path) write,
  }) async {
    try {
      return await Files.save(
          suggestedName: suggestedName,
          kind: kind,
          mime: mime,
          scratchDir: '$workspace${Platform.pathSeparator}exports',
          write: write);
    } catch (e) {
      fail('Could not save it: $e');
      return null;
    }
  }

  void go(AppPage p) {
    page = p;
    notifyListeners();
  }

  void _setProject(dynamic v) {
    final m = _map(v);
    if (m == null) return;
    if (m.containsKey('project') && m['project'] is Map) {
      project = _map(m['project'])!;
    } else if (m.containsKey('variant')) {
      project = m;
    }
  }

  Future<T?> _call<T>(Future<T> Function() fn, {String? done}) async {
    try {
      final r = await fn();
      if (done != null) info(done);
      return r;
    } catch (e) {
      fail(e);
      return null;
    } finally {
      notifyListeners();
    }
  }

  /// Runs an engine job with the progress bar; returns its result (null when it failed or was cancelled).
  Future<dynamic> runJob(String label, String path, Map<String, dynamic> body) async {
    if (busy) {
      fail('Wait for “$jobLabel” to finish (or cancel it).');
      return null;
    }
    jobLabel = label;
    job = JobState(id: '', kind: label, status: 'running', progress: 0, message: 'starting');
    notifyListeners();
    try {
      final j = await engine.runJob(path, body, (s) {
        job = s;
        notifyListeners();
      });
      if (j.status == 'cancelled') {
        info('$label cancelled.');
        return null;
      }
      if (j.status != 'done') {
        fail(j.error ?? '$label failed.');
        return null;
      }
      return j.result;
    } catch (e) {
      fail(e);
      return null;
    } finally {
      job = null;
      await refresh(quiet: true);
    }
  }

  Future<void> cancelJob() async {
    final j = job;
    if (j == null || j.id.isEmpty) return;
    await _call(() => engine.cancelJob(j.id));
  }

  // ── loading ──
  Future<void> init() async {
    status = (await engine.get('/api/status') as Map).cast<String, dynamic>();
    project = _map(status['project']) ?? {};
    look = _map(await engine.get('/api/look'));
    catalog = _map(await engine.get('/api/templates'));
    patterns = _map(await engine.get('/api/patterns'));
    if (analyzed) await loadSamples(quiet: true);
    _pickLastRender();
    notifyListeners();
  }

  Future<void> refresh({bool quiet = false}) async {
    try {
      project = _map(await engine.get('/api/project')) ?? project;
      _pickLastRender();
    } catch (e) {
      if (!quiet) fail(e);
    }
    notifyListeners();
  }

  void _pickLastRender() {
    final o = outputs;
    for (final q in ['1080p', '720p', 'preview']) {
      final out = _map(o[q]);
      if (out != null && out['file'] != null) {
        lastRender ??= '${out['file']}';
        return;
      }
    }
  }

  Future<void> loadSamples({bool quiet = false}) async {
    try {
      bank = _map(await engine.get('/api/samples'));
    } catch (e) {
      if (!quiet) fail(e);
    }
    notifyListeners();
  }

  Future<void> loadArrangement() async {
    await _call(() async => arrangement = _map(await engine.get('/api/arrangement')));
  }

  // ── source ──
  Future<bool> setSource(String path) async {
    final ok = await _call(() async {
      _setProject(await engine.post('/api/source/path', {'path': path}));
      bank = null;
      arrangement = null;
      return true;
    });
    return ok == true;
  }

  Future<bool> downloadUrl(String url) async {
    final r = await runJob('Downloading the video', '/api/source/url', {'url': url});
    if (r == null) return false;
    _setProject(r);
    bank = null;
    notifyListeners();
    return true;
  }

  Future<bool> analyze({bool force = false}) async {
    final r = await runJob('Cutting the samples', '/api/analyze', {'force': force});
    if (r == null) return false;
    bank = _map(r);
    notifyListeners();
    return true;
  }

  /// One click: samples, the remix on the chosen base, a preview.
  Future<bool> makeRemix({String quality = 'preview'}) async {
    final r = _map(await runJob('Making your Sparta Remix', '/api/auto', {'quality': quality}));
    if (r == null) return false;
    lastRender = '${r['file']}';
    await loadSamples(quiet: true);
    arrangement = null;
    page = AppPage.export;
    notifyListeners();
    return true;
  }

  Future<bool> render(String quality) async {
    final r = _map(await runJob(
        quality == 'preview' ? 'Rendering the preview' : 'Rendering the $quality video', '/api/render', {'quality': quality}));
    if (r == null) return false;
    lastRender = '${r['file']}';
    notifyListeners();
    return true;
  }

  // ── samples ──
  Future<void> selectSample(String role, {int? index, double? start, double? end, bool reset = false}) async {
    await _call(() async {
      final body = <String, dynamic>{'role': role};
      if (reset) {
        body['reset'] = true;
      } else if (start != null && end != null) {
        body['start'] = start;
        body['end'] = end;
      } else {
        body['index'] = index ?? 0;
      }
      bank = _map(await engine.post('/api/samples/select', body));
      arrangement = null;
    });
  }

  Future<void> sampleConfig(Map<String, dynamic> cfg) async {
    await _call(() async {
      bank = _map(await engine.post('/api/samples/config', cfg));
      await refresh(quiet: true);
    });
  }

  // ── base: templates, base file, MIDI, key ──
  Future<void> useTemplate(String id, {Map<String, dynamic>? options}) async {
    await _call(() async {
      _setProject(await engine.post('/api/template/use', {'id': id, ...?options}));
      arrangement = null;
    });
  }

  Future<void> reloadCatalog() async {
    await _call(() async => catalog = _map(await engine.get('/api/templates')));
  }

  Future<void> saveTemplate(String name, String description) async {
    await _call(() async {
      final r = _map(await engine.post('/api/template/save', {'name': name, 'description': description}));
      catalog = _map(r?['catalog']) ?? catalog;
    }, done: 'Saved “$name” in My templates.');
  }

  Future<void> importTemplate(String path) async {
    await _call(() async {
      final r = _map(await engine.post('/api/template/import', {'path': path}));
      catalog = _map(r?['catalog']) ?? catalog;
    }, done: 'Template imported.');
  }

  Future<void> deleteTemplate(String id) async {
    await _call(() async {
      final r = _map(await engine.post('/api/template/delete', {'id': id}));
      catalog = _map(r?['catalog']) ?? catalog;
    }, done: 'Template deleted.');
  }

  Future<bool> openBase(String path, {String template = '', bool follow = true}) async {
    final r = _map(await runJob('Reading your base', '/api/base/open',
        {'path': path, 'template': template, 'follow': follow}));
    if (r == null) return false;
    _setProject(r);
    if (r['base_error'] != null) {
      fail('The base plays under the remix, but its parts could not be read: ${r['base_error']}');
    }
    arrangement = null;
    notifyListeners();
    return true;
  }

  Future<void> baseOptions(Map<String, dynamic> opts) async {
    await _call(() async {
      _setProject(await engine.post('/api/base/options', opts));
      arrangement = null;
    });
  }

  Future<void> clearBase() async {
    await _call(() async {
      _setProject(await engine.post('/api/base/clear'));
      arrangement = null;
    });
  }

  Future<void> openMidi(String path) async {
    await _call(() async {
      _setProject(await engine.post('/api/midi/open', {'path': path}));
      arrangement = null;
    });
  }

  Future<void> midiMapping({Map<String, dynamic>? mapping, bool? autoPercussion, bool? autoPhrase, int? sectionBars,
      bool use = false}) async {
    await _call(() async {
      _setProject(await engine.post('/api/midi/mapping', {
        'mapping': ?mapping,
        'auto_percussion': ?autoPercussion,
        'auto_phrase': ?autoPhrase,
        'section_bars': ?sectionBars,
        if (use) 'use': true,
      }));
      arrangement = null;
    });
  }

  Future<void> clearMidi() async {
    await _call(() async {
      _setProject(await engine.post('/api/midi/clear'));
      arrangement = null;
    });
  }

  Future<void> setKey(String k) async {
    await _call(() async {
      _setProject(await engine.post('/api/key', {'key': k}));
      arrangement = null;
    });
  }

  // ── remix options & arrangement ──
  Future<void> setOptions(Map<String, dynamic> opts) async {
    await _call(() async {
      _setProject(await engine.post('/api/arrangement/variant',
          {'variant': variant, 'options': {...?_map(project['options']), ...opts}}));
      await refresh(quiet: true);
      arrangement = null;
    });
  }

  Future<void> saveArrangement(Map<String, dynamic> arr) async {
    await _call(() async {
      arrangement = _map(await engine.post('/api/arrangement', arr));
      await refresh(quiet: true);
    }, done: 'Structure saved.');
  }

  Future<Map<String, dynamic>?> newSection(String kind, int bars) => _call<Map<String, dynamic>?>(
      () async => _map(await engine.post('/api/arrangement/section', {'kind': kind, 'bars': bars})));

  // ── look & sound ──
  Future<void> setLook({Map<String, dynamic>? video, Map<String, dynamic>? mix, bool replaceVideo = false,
      bool replaceFx = false}) async {
    await _call(() async {
      look = _map(await engine.post('/api/look', {
        'video': ?video,
        'mix': ?mix,
        'replace_video': replaceVideo,
        'replace_fx': replaceFx,
      }));
    });
  }

  Future<void> setMix(Map<String, dynamic> mix) async {
    await _call(() async => _setProject(await engine.post('/api/mix', mix)));
  }

  // ── exports ──
  Future<bool> exportFile(String file, String dest, {String? audioFormat}) async {
    final r = await _call(() => engine.post('/api/export/file', {
          'file': file,
          'dest': dest,
          'audio_format': ?audioFormat,
        }));
    return r != null;
  }

  Future<bool> exportPack(String dest, {bool video = true}) async {
    final r = await runJob('Exporting the sample pack', '/api/export/pack', {'dest': dest, 'video': video});
    return r != null;
  }

  Future<bool> exportMidi(String dest) async => (await _call(() => engine.post('/api/export/midi', {'dest': dest}))) != null;

  // ── projects ──
  Future<void> rename(String name) async {
    await _call(() async => _setProject(await engine.post('/api/project/name', {'name': name})));
  }

  Future<void> saveProject() async {
    await _call(() => engine.post('/api/project/save'), done: 'Project saved.');
  }

  Future<bool> saveProjectAs(String dest) async =>
      (await _call(() => engine.post('/api/project/save_as', {'dest': dest}), done: 'Project saved.')) != null;

  Future<void> openProject(String path) async {
    await _call(() async {
      _setProject(await engine.post('/api/project/open', {'path': path}));
      bank = null;
      arrangement = null;
      lastRender = null;
      _pickLastRender();
      if (analyzed) await loadSamples(quiet: true);
      page = AppPage.source;
    });
  }

  Future<void> newProject() async {
    await _call(() async {
      _setProject(await engine.post('/api/project/new'));
      bank = null;
      arrangement = null;
      lastRender = null;
      page = AppPage.source;
    });
  }

  Future<List<Map<String, dynamic>>> recentProjects() async {
    final r = await _call(() => engine.get('/api/projects'));
    final list = _map(r)?['projects'];
    return list is List ? list.map((e) => (e as Map).cast<String, dynamic>()).toList() : [];
  }

  @override
  void dispose() {
    _messages.close();
    super.dispose();
  }
}
