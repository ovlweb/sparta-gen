// The system's own Open / Save / folder dialogs (desktop: file_selector; Android: the document picker
// and "Save as" of the system, through the app's host; iOS: the Files and Photos pickers, and the share sheet
// to save).

import 'dart:convert';
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
  static const background = XTypeGroup(label: 'Video, GIF or picture', extensions: [
    'mp4', 'mkv', 'mov', 'webm', 'avi', 'm4v', 'gif', 'png', 'jpg', 'jpeg', 'webp', 'bmp', //
  ], mimeTypes: ['video/*', 'image/*'], uniformTypeIdentifiers: ['public.movie', 'public.image']);
  static const json = XTypeGroup(
      label: 'SpartaGen file', extensions: ['json'], mimeTypes: ['application/json'],
      uniformTypeIdentifiers: ['public.json']);
  static const mp4 = XTypeGroup(label: 'MP4 video', extensions: ['mp4'], uniformTypeIdentifiers: ['public.mpeg-4']);
  static const wav = XTypeGroup(label: 'WAV audio', extensions: ['wav'], uniformTypeIdentifiers: ['com.microsoft.waveform-audio']);
  static const mp3 = XTypeGroup(label: 'MP3 audio', extensions: ['mp3'], uniformTypeIdentifiers: ['public.mp3']);
  static const zip = XTypeGroup(label: 'ZIP archive', extensions: ['zip'], uniformTypeIdentifiers: ['public.zip-archive']);
  static const template = XTypeGroup(
      label: 'SpartaGen template (.zip or .spartabase.json)', extensions: ['zip', 'json'],
      mimeTypes: ['application/zip', 'application/json'], uniformTypeIdentifiers: ['public.zip-archive', 'public.json']);
  static const mid = XTypeGroup(label: 'MIDI file', extensions: ['mid'], uniformTypeIdentifiers: ['public.midi-audio']);
}

class Files {
  static const _host = MethodChannel('gen.sparta/files');
  static String? _lastDir; // where the last file was opened or saved: the next dialog starts there

  /// A phone (Android, iOS): files come from and go to the system's pickers, not to folders the app shows.
  static bool get onPhone => Platform.isAndroid || Platform.isIOS;

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

  /// Android: hand a downloaded APK to the system's installer.  "installing" when it opened, "permission" when
  /// the user has first to allow SpartaGen to install apps (the system's settings for that open).
  static Future<String?> installApk(String path) => _host.invokeMethod<String>('installApk', {'path': path});

  /// Pick a file to open; its local path (on a phone a copy the app can read).  [photos]: from the Photos
  /// library (iOS).
  static Future<String?> open(XTypeGroup kind, {bool photos = false}) async {
    lastDialog = 'system';
    if (Platform.isIOS && photos) {
      return _host.invokeMethod<String>('open', {'photos': true, 'images': kind.mimeTypes?.contains('image/*') ?? false});
    }
    if (Platform.isAndroid) {
      final mimes = kind.mimeTypes ?? const ['*/*'];
      return _host.invokeMethod<String>('open', {'mime': mimes});
    }
    final start = onPhone ? null : _startDir(kind);
    final String? path;
    try {
      path = (await openFile(acceptedTypeGroups: [kind], initialDirectory: start))?.path;
    } on PlatformException catch (e) {
      if (!Platform.isWindows) rethrow;
      return _remember(await _helperDialog('open', kind, start, error: e));
    }
    if (path == null) return null;
    if (path.isEmpty) {
      throw const FileSystemException('That file is not in a folder on this computer (a “Recent” or network '
          'location) — open it from its folder instead.');
    }
    return _remember(path);
  }

  static String? _remember(String? path) {
    if (path != null && path.isNotEmpty) _lastDir = p.dirname(path);
    return path == null || path.isEmpty ? null : path;
  }

  /// Which dialog was shown last: the system's own in the app ("system"), or the helper's (Windows, "helper").
  static String lastDialog = 'system';

  /// Windows: the same system dialog, shown by a helper process (PowerShell, in a COM apartment of its own) — for
  /// when the app's own could not be shown ([error]).  [mode]: open, save or folder.  The path chosen, or null.
  static Future<String?> _helperDialog(String mode, XTypeGroup? kind, String? dir,
      {String? name, PlatformException? error}) async {
    lastDialog = 'helper';
    String q(String? v) => "'${(v ?? '').replaceAll("'", "''")}'";
    final exts = kind?.extensions ?? const <String>[];
    final filter = [
      if (exts.isNotEmpty) '${kind?.label ?? 'Files'} (${exts.map((e) => '*.$e').join(', ')})|'
          '${exts.map((e) => '*.$e').join(';')}',
      'All files (*.*)|*.*',
    ].join('|');
    final dialog = switch (mode) {
      'save' => 'System.Windows.Forms.SaveFileDialog',
      'folder' => 'System.Windows.Forms.FolderBrowserDialog',
      _ => 'System.Windows.Forms.OpenFileDialog',
    };
    final settings = mode == 'folder'
        ? [r'$d.SelectedPath = ' + q(dir), r'$d.ShowNewFolderButton = $true']
        : [
            r'$d.Filter = ' + q(filter),
            r'$d.InitialDirectory = ' + q(dir),
            if (mode == 'save') ...[r'$d.FileName = ' + q(name), r'$d.OverwritePrompt = $true'],
          ];
    final script = [
      r"$ErrorActionPreference = 'Stop'",
      r'[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false',
      r'Add-Type -AssemblyName System.Windows.Forms',
      r'[System.Windows.Forms.Application]::EnableVisualStyles()',
      r'$d = New-Object ' + dialog,
      ...settings,
      // (an owner kept on top: the dialog does not open behind SpartaGen's window)
      r'$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true; ShowInTaskbar = $false}',
      r'if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {',
      '  [Console]::Out.Write(${mode == 'folder' ? r'$d.SelectedPath' : r'$d.FileName'})',
      '}',
    ].join('\n');
    final utf16 = <int>[for (final c in script.codeUnits) ...[c & 0xff, c >> 8]];
    final ProcessResult r;
    try {
      r = await Process.run('powershell.exe', [
        '-NoProfile', '-STA', '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', base64.encode(utf16),
      ], stdoutEncoding: utf8, stderrEncoding: utf8);
    } on ProcessException {
      throw FileSystemException('Windows could not show its file dialog (${error?.message ?? 'no PowerShell'}).');
    }
    if (r.exitCode != 0) {
      throw FileSystemException('Windows could not show its file dialog: ${'${r.stderr}'.trim()}');
    }
    final out = '${r.stdout}'.replaceAll('\uFEFF', '').trim();
    return out.isEmpty ? null : out;
  }

  /// Where to save (desktop): the system's Save dialog — on Windows the helper's when the app's cannot be shown.
  static Future<String?> saveLocation({required String suggestedName, required XTypeGroup kind}) async {
    final start = _startDir(kind);
    lastDialog = 'system';
    String? path;
    try {
      path = (await getSaveLocation(suggestedName: suggestedName, acceptedTypeGroups: [kind], initialDirectory: start))
          ?.path;
    } on PlatformException catch (e) {
      if (!Platform.isWindows) rethrow;
      path = await _helperDialog('save', kind, start, name: suggestedName, error: e);
    }
    if (path == null || path.isEmpty) return null;
    final ext = kind.extensions?.isNotEmpty == true ? kind.extensions!.first : null;
    if (ext != null && p.extension(path).isEmpty) path = '$path.$ext';
    return _remember(path);
  }

  /// Save something the engine writes: desktop asks where first and the engine writes there; a phone has
  /// it written into the app's folder, then the system's "Save as" (iOS: the share sheet) takes it where the
  /// user wants.
  static Future<String?> save({
    required String suggestedName,
    required XTypeGroup kind,
    required String mime,
    required String scratchDir,
    required Future<bool> Function(String path) write,
  }) async {
    if (onPhone) {
      final tmp = p.join(scratchDir, suggestedName);
      await Directory(scratchDir).create(recursive: true);
      if (!await write(tmp)) return null;
      final ok = await _host.invokeMethod<bool>('saveAs', {'path': tmp, 'name': suggestedName, 'mime': mime});
      return ok == true ? suggestedName : null;
    }
    final path = await saveLocation(suggestedName: suggestedName, kind: kind);
    if (path == null) return null;
    return await write(path) ? path : null;
  }

  /// A folder (desktop only).
  static Future<String?> folder({String? title}) async {
    if (onPhone) return null;
    final start = _startDir(Kinds.video);
    String? dir;
    try {
      dir = await getDirectoryPath(confirmButtonText: title, initialDirectory: start);
    } on PlatformException catch (e) {
      if (!Platform.isWindows) rethrow;
      dir = await _helperDialog('folder', null, start, error: e);
    }
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
