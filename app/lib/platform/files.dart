// The system's own Open / Save / folder dialogs (desktop: file_selector; Android: the document picker
// and "Save as" of the system, through the app's host).

import 'dart:io';

import 'package:file_selector/file_selector.dart';
import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;

class Kinds {
  static const video = XTypeGroup(label: 'Video or audio', extensions: [
    'mp4', 'mkv', 'mov', 'webm', 'avi', 'm4v', 'flv', 'wmv', 'mpg', 'mpeg', 'ts', //
    'mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac', 'opus',
  ], mimeTypes: ['video/*', 'audio/*'], uniformTypeIdentifiers: ['public.movie', 'public.audio']);
  static const audio = XTypeGroup(
      label: 'Audio',
      extensions: ['mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac', 'opus'],
      mimeTypes: ['audio/*'],
      uniformTypeIdentifiers: ['public.audio']);
  static const midi = XTypeGroup(
      label: 'MIDI', extensions: ['mid', 'midi', 'rmi', 'kar'], mimeTypes: ['audio/midi', 'audio/x-midi'],
      uniformTypeIdentifiers: ['public.midi-audio']);
  static const json = XTypeGroup(
      label: 'Sparta Gen file', extensions: ['json'], mimeTypes: ['application/json'],
      uniformTypeIdentifiers: ['public.json']);
  static const mp4 = XTypeGroup(label: 'MP4 video', extensions: ['mp4'], uniformTypeIdentifiers: ['public.mpeg-4']);
  static const wav = XTypeGroup(label: 'WAV audio', extensions: ['wav'], uniformTypeIdentifiers: ['com.microsoft.waveform-audio']);
  static const mp3 = XTypeGroup(label: 'MP3 audio', extensions: ['mp3'], uniformTypeIdentifiers: ['public.mp3']);
  static const zip = XTypeGroup(label: 'ZIP archive', extensions: ['zip'], uniformTypeIdentifiers: ['public.zip-archive']);
  static const mid = XTypeGroup(label: 'MIDI file', extensions: ['mid'], uniformTypeIdentifiers: ['public.midi-audio']);
}

class Files {
  static const _android = MethodChannel('gen.sparta/files');
  static String? _lastDir; // where the last file was opened or saved: the next dialog starts there

  static bool get onAndroid => Platform.isAndroid;

  /// Where a dialog starts: the last folder used, else the user's Videos (or Music) folder, else home.
  static String? _startDir(XTypeGroup kind) {
    final last = _lastDir;
    if (last != null && Directory(last).existsSync()) return last;
    final home = Platform.environment[Platform.isWindows ? 'USERPROFILE' : 'HOME'];
    if (home == null || home.isEmpty) return null;
    final audio = identical(kind, Kinds.audio) || identical(kind, Kinds.mp3) || identical(kind, Kinds.wav) ||
        identical(kind, Kinds.midi) || identical(kind, Kinds.mid);
    String? dir;
    if (Platform.isLinux) {
      try {   // the desktop's own (maybe translated) folder names
        final r = Process.runSync('xdg-user-dir', [audio ? 'MUSIC' : 'VIDEOS']);
        final out = '${r.stdout}'.trim();
        if (r.exitCode == 0 && out.isNotEmpty && out != home) dir = out;
      } catch (_) {}
    }
    dir ??= p.join(home, audio ? 'Music' : (Platform.isMacOS ? 'Movies' : 'Videos'));
    return Directory(dir).existsSync() ? dir : home;
  }

  /// Pick a file to open; its local path (on Android a copy the app can read).
  static Future<String?> open(XTypeGroup kind) async {
    if (onAndroid) {
      final mimes = kind.mimeTypes ?? const ['*/*'];
      return _android.invokeMethod<String>('open', {'mime': mimes});
    }
    final f = await openFile(acceptedTypeGroups: [kind], initialDirectory: _startDir(kind));
    if (f == null) return null;
    if (f.path.isEmpty) {
      throw const FileSystemException('That file is not in a folder on this computer (a “Recent” or network '
          'location) — open it from its folder instead.');
    }
    _lastDir = p.dirname(f.path);
    return f.path;
  }

  /// Save something the engine writes: desktop asks where first and the engine writes there; Android
  /// has it written into the app's folder, then the system's "Save as" copies it where the user wants.
  static Future<String?> save({
    required String suggestedName,
    required XTypeGroup kind,
    required String mime,
    required String scratchDir,
    required Future<bool> Function(String path) write,
  }) async {
    if (onAndroid) {
      final tmp = p.join(scratchDir, suggestedName);
      await Directory(scratchDir).create(recursive: true);
      if (!await write(tmp)) return null;
      final ok = await _android.invokeMethod<bool>('saveAs', {'path': tmp, 'name': suggestedName, 'mime': mime});
      return ok == true ? suggestedName : null;
    }
    final loc = await getSaveLocation(
        suggestedName: suggestedName, acceptedTypeGroups: [kind], initialDirectory: _startDir(kind));
    if (loc == null) return null;
    var path = loc.path;
    final ext = kind.extensions?.isNotEmpty == true ? kind.extensions!.first : null;
    if (ext != null && p.extension(path).isEmpty) path = '$path.$ext';
    _lastDir = p.dirname(path);
    return await write(path) ? path : null;
  }

  /// A folder (desktop only).
  static Future<String?> folder({String? title}) async {
    if (onAndroid) return null;
    final dir = await getDirectoryPath(confirmButtonText: title, initialDirectory: _startDir(Kinds.video));
    if (dir != null) _lastDir = dir;
    return dir;
  }

  /// Show a file in the system's file manager.
  static Future<void> reveal(String path) async {
    try {
      if (Platform.isWindows) {
        await Process.run('explorer', ['/select,', path]);
      } else if (Platform.isMacOS) {
        await Process.run('open', ['-R', path]);
      } else if (Platform.isLinux) {
        await Process.run('xdg-open', [File(path).parent.path]);
      }
    } catch (_) {}
  }

  static String safeName(String name) => name.replaceAll(RegExp(r'[^\w\- ()\[\].]'), '_').trim();
}
